"""Retail insights entities: a single 'retail' sensor on the gateway carrying store footfall, in-store-now,
average dwell, per-entrance in/out, per-zone dwell and staff-zone coverage, plus an hourly in/out series for the
footfall chart. Samples every minute (like the area tracker) and persists the hourly history across restarts.
The pure maths is in retail_calc.py."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER, SIGNAL_FLEET, STORAGE_VERSION
from .models import MODELS
from .retail_calc import compute_retail

SIGNAL_RETAIL = f"{DOMAIN}_retail_{{}}"


def hub_device(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")}, name=entry.title,
                      manufacturer=MANUFACTURER, model="LoRaWAN gateway")


def _classify(model_key: str, purpose: str | None) -> str | None:
    """'counter' (footfall in/out), 'staff' (a counter / staff zone), 'zone' (customer dwell), or None."""
    if purpose == "counter_zone":
        return "staff"
    m = MODELS.get(model_key)
    if m is None:
        return None
    if m.counters:                                   # VS132 / VS133 / VS135 / VS350 — entrance in/out
        return "counter"
    if m.occupancy_fn is not None and m.counting:    # VS121 / VS321 — AI people counting in an area
        return "zone"
    return None


class RetailTracker:
    """Builds the retail snapshot every minute and integrates the hourly footfall series."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.data: dict[str, Any] = {}
        self.store = None
        # persisted state: current day's hourly series + accumulators, and yesterday's totals
        self.s: dict[str, Any] = {"day": None, "hourly_in": [0] * 24, "hourly_out": [0] * 24,
                                  "last_in": None, "last_out": None, "person_minutes": 0.0,
                                  "peak": 0, "peak_at": None, "visitors_yesterday": None,
                                  "prev_hourly_in": None, "prev_hourly_out": None}

    # -- device snapshot ---------------------------------------------------
    def _devices(self) -> list[dict[str, Any]]:
        from .fleet import fleet_devices
        by_eui = {}
        for e in self.hass.config_entries.async_entries(DOMAIN):
            rt = getattr(e, "runtime_data", None)
            if rt is not None and hasattr(rt, "deveui"):
                by_eui[rt.deveui.upper()] = rt
        out: list[dict[str, Any]] = []
        for d in fleet_devices(self.hass, self.entry):
            rt = by_eui.get(d["deveui"])
            if rt is None:
                continue
            model_key = rt.model.key
            purpose = rt.entry.options.get("purpose")
            kind = _classify(model_key, purpose)
            if kind is None:
                continue
            v = rt.values
            net = int(v.get("people_in_today") or 0) - int(v.get("people_out_today") or 0)
            out.append({
                "name": rt.entry.title, "area": rt.entry.data.get("area"), "kind": kind,
                "in_today": v.get("people_in_today"), "out_today": v.get("people_out_today"),
                "people_now": v.get("occ_people_count") if v.get("occ_people_count") is not None else (net if kind == "counter" else None),
                "dwell_s": v.get("dwell_time_avg"),
                "occ_person_minutes": v.get("occ_person_minutes_today"),
                "occ_sessions": v.get("occ_sessions_today"),
                "occ_occupied_s": v.get("occ_occupied_today_s"),
            })
        return out

    # -- per-minute sampler ------------------------------------------------
    @callback
    def update(self, _now: Any = None) -> None:
        import time
        devices = self._devices()
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
        now = dt_util.utc_from_timestamp(time.time()).astimezone(tz)
        day, hour = now.date().isoformat(), now.hour
        s = self.s
        if s["day"] != day:                                   # new day: archive yesterday, reset
            if s["day"] is not None:
                s["visitors_yesterday"] = (s["last_in"] or 0)
                s["prev_hourly_in"], s["prev_hourly_out"] = s["hourly_in"], s["hourly_out"]
            s.update({"day": day, "hourly_in": [0] * 24, "hourly_out": [0] * 24,
                      "last_in": None, "last_out": None, "person_minutes": 0.0, "peak": 0, "peak_at": None})

        counters = [d for d in devices if d["kind"] == "counter"]
        in_tot = sum(int(d.get("in_today") or 0) for d in counters)
        out_tot = sum(int(d.get("out_today") or 0) for d in counters)
        # bucket the increase since the last sample into the current hour (guard counter resets)
        if s["last_in"] is not None and in_tot >= s["last_in"]:
            s["hourly_in"][hour] += in_tot - s["last_in"]
        if s["last_out"] is not None and out_tot >= s["last_out"]:
            s["hourly_out"][hour] += out_tot - s["last_out"]
        s["last_in"], s["last_out"] = in_tot, out_tot
        net_now = max(0, in_tot - out_tot)
        s["person_minutes"] += net_now                        # one minute of this many people in store
        if net_now > s["peak"]:
            s["peak"], s["peak_at"] = net_now, now.strftime("%H:%M")

        snap = compute_retail(devices, person_minutes=s["person_minutes"], peak=s["peak"],
                              peak_at=s["peak_at"], visitors_yesterday=s["visitors_yesterday"])
        snap["hourly_in"] = list(s["hourly_in"])
        snap["hourly_out"] = list(s["hourly_out"])
        self.data = snap
        if self.store is not None:
            self.store.async_delay_save(lambda: self.s, 120)
        async_dispatcher_send(self.hass, SIGNAL_RETAIL.format(self.entry.entry_id))

    @callback
    def maybe_update(self) -> None:
        self.update()


class RetailSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Retail"
    _attr_icon = "mdi:storefront-outline"
    _attr_native_unit_of_measurement = "visitors"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, tracker: RetailTracker) -> None:
        self.hass, self.entry, self.tracker = hass, entry, tracker
        self._attr_device_info = hub_device(entry)
        self._attr_unique_id = f"{entry.entry_id}_retail"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_RETAIL.format(self.entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self):
        return self.tracker.data.get("visitors_today") if self.tracker.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"milesight_role": "retail", "site": self.entry.title, **(self.tracker.data or {})}


def has_retail(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """True when at least one people-counter / counting occupancy device is set up (so the page is worth showing)."""
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        model_key = e.options.get("model", e.data.get("model"))
        if _classify(model_key, e.options.get("purpose")) in ("counter", "zone"):
            return True
    return False


async def async_setup_retail(hass: HomeAssistant, entry: ConfigEntry) -> tuple[RetailTracker, list]:
    from homeassistant.helpers.storage import Store
    tracker = RetailTracker(hass, entry)
    tracker.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.retail_{entry.entry_id}")
    saved = await tracker.store.async_load()
    if isinstance(saved, dict) and "hourly_in" in saved:
        tracker.s.update({k: saved[k] for k in tracker.s if k in saved})
    entry.async_on_unload(lambda: tracker.store.async_save(tracker.s))
    tracker.update()
    entry.async_on_unload(async_track_time_interval(hass, tracker.update, timedelta(seconds=60)))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_FLEET, tracker.maybe_update))
    return tracker, [RetailSensor(hass, entry, tracker)]
