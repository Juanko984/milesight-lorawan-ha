"""Gateway: forecast-aware irrigation advice and frost warnings (Home Assistant side of irrigation.py).

Reads the weather entity's forecast (hourly, else daily) every 30 minutes and the soil moisture sensors whenever
they change, and offers:
* sensor 'Irrigation advice' (irrigate / skip) with the reason and suggested minutes (for the valve blueprint),
* binary sensor 'Rain expected' and binary sensor 'Frost tonight' (on from the afternoon before),
* event milesight_lorawan_frost once per night and an 'irrigation' alert for the escalation."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_ALERTS
from .irrigation import advice, frost_tonight, irrigation_config, rain_ahead

_LOGGER = logging.getLogger(__name__)
SIGNAL_IRRIGATION = f"{DOMAIN}_irrigation_{{}}"   # .format(hub entry_id)


def _purpose_runtimes(hass: HomeAssistant, keys: tuple[str, ...]) -> list:
    out = []
    for e in hass.config_entries.async_entries(DOMAIN):
        rt = getattr(e, "runtime_data", None)
        if getattr(rt, "purpose", None) is not None and rt.purpose.key in keys:
            out.append(rt)
    return out


def gauge_rain(hass: HomeAssistant) -> float | None:
    """Rain measured by the site's rain gauges in the last 24 h (the highest one)."""
    vals = [rt.values.get("rain_24h") for rt in _purpose_runtimes(hass, ("rain_gauge",))]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return max(vals) if vals else None


def soil_values(hass: HomeAssistant, entity_ids: tuple[str, ...]) -> list[float]:
    """The chosen soil moisture sensors plus every Milesight device fitted as field / greenhouse / garden soil."""
    from .purposes import SOIL_PURPOSES
    out = []
    chosen = set()                                   # Milesight moisture entities already in the list
    if entity_ids:
        try:
            from homeassistant.helpers import entity_registry as er
            reg = er.async_get(hass)
            chosen = {getattr(reg.async_get(eid), "unique_id", None) for eid in entity_ids}
        except Exception:  # noqa: BLE001
            chosen = set()
    for rt in _purpose_runtimes(hass, SOIL_PURPOSES):
        v = rt.values.get("moisture")
        if f"{rt.deveui}_moisture" in chosen:
            continue                                 # counted below as a chosen sensor
        if isinstance(v, (int, float)) and rt.values.get("online") is not False:
            out.append(float(v))
    for e in hass.config_entries.async_entries(DOMAIN):          # soil probes on UC controllers (channel map)
        rt = getattr(e, "runtime_data", None)
        for key, ch in (getattr(rt, "channels", None) or {}).items():
            v = rt.values.get(key) if ch.device_class == "moisture" else None
            if isinstance(v, (int, float)) and f"{rt.deveui}_{key}" not in chosen:
                out.append(float(v))
    for eid in entity_ids:
        st = hass.states.get(eid)
        try:
            out.append(float(st.state))           # type: ignore[union-attr]
        except (AttributeError, TypeError, ValueError):
            continue                               # unavailable / unknown: leave it out
    return out


class IrrigationManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.cfg = irrigation_config(dict(entry.options))
        self.forecast: list[dict[str, Any]] = []
        self.daily = False
        self.fetched_at: float | None = None
        self.error: str | None = None
        self.data: dict[str, Any] = {}
        self._frost_night: str | None = None      # the morning date a frost event was sent for
        self._unsubs: list = []

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.weather or self.cfg.soil)

    async def async_start(self) -> None:
        if not self.enabled:
            return
        self._unsubs.append(async_track_time_interval(self.hass, self._refresh, timedelta(minutes=30)))
        if self.cfg.soil:
            self._unsubs.append(async_track_state_change_event(self.hass, list(self.cfg.soil), self._soil_changed))
        self._unsubs.append(async_call_later(self.hass, 20, self._refresh))   # weather integrations load first
        self._evaluate()

    async def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    async def _fetch(self) -> None:
        if not self.cfg.weather:
            return
        for kind in ("hourly", "daily"):
            try:
                resp = await self.hass.services.async_call(
                    "weather", "get_forecasts", {"entity_id": self.cfg.weather, "type": kind},
                    blocking=True, return_response=True)
            except Exception as err:  # noqa: BLE001 - the weather integration may not offer this forecast type
                self.error = str(err)
                continue
            items = ((resp or {}).get(self.cfg.weather) or {}).get("forecast") or []
            if items:
                self.forecast, self.daily = items, kind == "daily"
                self.fetched_at, self.error = dt_util.utcnow().timestamp(), None
                return
        if self.fetched_at and dt_util.utcnow().timestamp() - self.fetched_at > 6 * 3600:
            self.forecast = []                       # too old to rely on

    async def _refresh(self, _now: Any = None) -> None:
        await self._fetch()
        self._evaluate()

    @callback
    def _soil_changed(self, _event: Any) -> None:
        self._evaluate()

    @callback
    def _evaluate(self) -> None:
        now = dt_util.now()
        rain = rain_ahead(self.forecast, now, self.cfg.rain_hours, self.daily)
        frost = frost_tonight(self.forecast, now, self.cfg.frost_c, self.cfg.warn_from, self.daily)
        adv = advice(soil_values(self.hass, self.cfg.soil), rain, self.cfg, gauge_rain(self.hass))
        if not self.forecast and self.cfg.weather:
            adv["reason"] += " – no forecast available"
        old_frost = (self.data.get("frost") or {}).get("active")
        self.data = {"advice": adv, "rain": rain, "frost": frost}
        if frost["active"]:
            night = (now + timedelta(days=1 if now.hour >= 10 else 0)).date().isoformat()
            if night != self._frost_night:
                self._frost_night = night
                self.hass.bus.async_fire(f"{DOMAIN}_frost", {"site": self.entry.title, "low": frost["low"],
                                                             "at": frost["at"], "threshold": self.cfg.frost_c})
        if bool(frost["active"]) != bool(old_frost):
            async_dispatcher_send(self.hass, SIGNAL_ALERTS)
        async_dispatcher_send(self.hass, SIGNAL_IRRIGATION.format(self.entry.entry_id))

    def alerts(self) -> dict[str, dict[str, Any]]:
        frost = self.data.get("frost") or {}
        if not frost.get("active"):
            return {}
        at = frost.get("at")
        when = ""
        if at:
            try:
                when = f" around {dt_util.as_local(dt_util.parse_datetime(at)).strftime('%H:%M')}"
            except (TypeError, ValueError, AttributeError):
                when = ""
        return {f"frost:{self.entry.entry_id}": {
            "title": f"Frost tonight – {self.entry.title}", "severity": "warning", "category": "irrigation",
            "message": f"Forecast low {frost['low']:g} °C{when} (warning at {self.cfg.frost_c:g} °C). "
                       f"Protect plants, drain exposed pipes or run frost protection."}}


# ------------------------------------------------------------------ entities
class _Base:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mgr: IrrigationManager, key: str) -> None:
        self.hass, self.entry, self.mgr = hass, entry, mgr
        self._attr_unique_id = f"{entry.entry_id}_irr_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_IRRIGATION.format(self.entry.entry_id), self.async_write_ha_state))


class IrrigationAdviceSensor(_Base, SensorEntity):
    _attr_name = "Irrigation advice"
    _attr_icon = "mdi:sprinkler-variant"
    _attr_device_class = "enum"
    _attr_options = ["irrigate", "skip"]
    _attr_translation_key = "irrigation_advice"

    @property
    def native_value(self) -> str | None:
        return (self.mgr.data.get("advice") or {}).get("advice")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        a, r = self.mgr.data.get("advice") or {}, self.mgr.data.get("rain") or {}
        return {"milesight_role": "irrigation", "site": self.entry.title, "reason": a.get("reason"),
                "minutes": a.get("minutes"), "base_minutes": self.mgr.cfg.base_minutes,
                "soil_moisture": a.get("soil_moisture"), "target_moisture": self.mgr.cfg.target,
                "rain_mm": r.get("mm"), "rain_probability": r.get("probability"),
                "rain_window_h": self.mgr.cfg.rain_hours, "forecast": "daily" if self.mgr.daily else "hourly",
                "forecast_error": self.mgr.error}


class RainExpectedSensor(_Base, BinarySensorEntity):
    _attr_name = "Rain expected"
    _attr_icon = "mdi:weather-pouring"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    @property
    def is_on(self) -> bool | None:
        a = self.mgr.data.get("advice")
        return a.get("rain_expected") if a and self.mgr.forecast else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self.mgr.data.get("rain") or {}
        return {"rain_mm": r.get("mm"), "probability": r.get("probability"), "window_h": self.mgr.cfg.rain_hours}


class FrostTonightSensor(_Base, BinarySensorEntity):
    _attr_name = "Frost tonight"
    _attr_icon = "mdi:snowflake-alert"
    _attr_device_class = BinarySensorDeviceClass.COLD

    @property
    def is_on(self) -> bool | None:
        f = self.mgr.data.get("frost")
        return f.get("active") if f and self.mgr.forecast else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        f = self.mgr.data.get("frost") or {}
        return {"milesight_role": "frost", "site": self.entry.title, "forecast_low": f.get("low"),
                "low_at": f.get("at"), "expected": f.get("expected"), "threshold": self.mgr.cfg.frost_c}


def irrigation_entities(hass: HomeAssistant, entry: ConfigEntry, platform: str) -> list:
    mgr = getattr(getattr(entry, "runtime_data", None), "irrigation", None)
    if mgr is None or not mgr.enabled:
        return []
    if platform == "sensor":
        return [IrrigationAdviceSensor(hass, entry, mgr, "advice")]
    return [RainExpectedSensor(hass, entry, mgr, "rain"), FrostTonightSensor(hass, entry, mgr, "frost")] \
        if mgr.cfg.weather else []
