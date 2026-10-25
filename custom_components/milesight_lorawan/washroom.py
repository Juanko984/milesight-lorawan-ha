"""Smart-washroom entities: a single 'washroom' sensor on the gateway carrying one entry per restroom (grouped by
Home Assistant area) with cleanliness (odour), supplies, traffic, air, noise and events. Recomputed every minute.
The pure maths is in washroom_calc.py."""
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

from .const import DOMAIN, MANUFACTURER, SIGNAL_FLEET
from .washroom_calc import compute_washroom

SIGNAL_WASHROOM = f"{DOMAIN}_washroom_{{}}"

# models that make an area a washroom on their own
CORE_MODELS = {"GS301", "GS601", "WS201", "VS330"}


def hub_device(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")}, name=entry.title,
                      manufacturer=MANUFACTURER, model="LoRaWAN gateway")


def _is_core(model_key: str, purpose: str | None) -> bool:
    return model_key in CORE_MODELS or purpose == "toilet"


class WashroomTracker:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.data: dict[str, Any] = {}

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
            v = rt.values or {}
            purpose = rt.entry.options.get("purpose")
            core = _is_core(rt.model.key, purpose)
            ambient = any(k in v for k in ("co2", "sound_level", "leak_active", "occ_occupied", "remaining", "odour_level"))
            if not core and not ambient:
                continue
            out.append({
                "area": rt.entry.data.get("area"), "name": rt.entry.title, "core": core,
                "odour": v.get("odour_level"), "nh3": v.get("nh3"), "h2s": v.get("h2s"),
                "co2": v.get("co2"), "sound_db": v.get("sound_level"),
                "occupied": v.get("occ_occupied"), "people": v.get("occ_people_count"),
                "remaining": v.get("remaining"), "supply_name": rt.entry.title,
                "visits_since_clean": v.get("visits_since_clean"), "clean_due": v.get("clean_due"),
                "clean_visits": (rt.pcfg.get("clean_visits") if purpose == "toilet" and getattr(rt, "pcfg", None) else None),
                "vape": v.get("vape_active"), "leak": v.get("leak_active"), "smoke": v.get("smoke_active"),
            })
        return out

    @callback
    def update(self, _now: Any = None) -> None:
        self.data = compute_washroom(self._devices())
        async_dispatcher_send(self.hass, SIGNAL_WASHROOM.format(self.entry.entry_id))

    @callback
    def maybe_update(self) -> None:
        self.update()


class WashroomSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Washrooms"
    _attr_icon = "mdi:human-male-female"
    _attr_native_unit_of_measurement = "washrooms"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, tracker: WashroomTracker) -> None:
        self.hass, self.entry, self.tracker = hass, entry, tracker
        self._attr_device_info = hub_device(entry)
        self._attr_unique_id = f"{entry.entry_id}_washroom"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_WASHROOM.format(self.entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self):
        return self.tracker.data.get("count") if self.tracker.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"milesight_role": "washroom", "site": self.entry.title, **(self.tracker.data or {})}


def has_washroom(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        if _is_core(e.options.get("model", e.data.get("model")), e.options.get("purpose")):
            return True
    return False


def washroom_sensors(hass: HomeAssistant, entry: ConfigEntry) -> tuple[WashroomTracker, list]:
    tracker = WashroomTracker(hass, entry)
    tracker.update()
    entry.async_on_unload(async_track_time_interval(hass, tracker.update, timedelta(seconds=60)))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_FLEET, tracker.maybe_update))
    return tracker, [WashroomSensor(hass, entry, tracker)]
