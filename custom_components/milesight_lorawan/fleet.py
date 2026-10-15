"""Gateway-level fleet overview sensors (online / offline / low battery, device list)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_DEVICE, ENTRY_TYPE_HUB, MANUFACTURER, SIGNAL_FLEET

KINDS = {   # key -> (name, icon)
    "total": ("Devices", "mdi:access-point-network"),
    "online": ("Devices online", "mdi:lan-connect"),
    "offline": ("Devices offline", "mdi:lan-disconnect"),
    "battery_low": ("Devices with low battery", "mdi:battery-alert-variant-outline"),
}


def fleet_devices(hass: HomeAssistant, hub_entry: ConfigEntry) -> list[dict[str, Any]]:
    """All device entries this gateway serves (every device when there is only one gateway)."""
    hubs = [e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB]
    hub = getattr(hub_entry, "runtime_data", None)
    heard = set(hub.last_uplink) if hub is not None else set()
    out = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        rt = getattr(entry, "runtime_data", None)
        if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE or rt is None:
            continue
        if len(hubs) > 1 and rt.deveui not in heard:
            continue
        v = rt.values
        last = rt.meta.get("last_seen")
        out.append({
            "name": entry.title, "model": rt.model.key, "deveui": rt.deveui.upper(),
            "area": entry.data.get("area"), "online": bool(v.get("online")),
            "battery": v.get("battery"), "battery_low": bool(v.get("battery_low")),
            "rssi": rt.meta.get("rssi"), "snr": rt.meta.get("snr"),
            "last_seen": dt_util.utc_from_timestamp(last).isoformat() if last else None,
        })
    return sorted(out, key=lambda d: (d["online"], d["name"].lower()))


class FleetSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, kind: str) -> None:
        self.hass = hass
        self.entry = entry
        self.kind = kind
        name, icon = KINDS[kind]
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_fleet_{kind}"
        self._attr_native_unit_of_measurement = "devices"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")}, name=entry.title,
                                            manufacturer=MANUFACTURER, model="LoRaWAN gateway")
        self._devices: list[dict] = []

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_FLEET, self._refresh))
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, timedelta(seconds=60)))
        self._refresh()

    @callback
    def _tick(self, _now) -> None:
        self._refresh()

    @callback
    def _refresh(self) -> None:
        self._devices = fleet_devices(self.hass, self.entry)
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    def _selected(self) -> list[dict]:
        if self.kind == "online":
            return [d for d in self._devices if d["online"]]
        if self.kind == "offline":
            return [d for d in self._devices if not d["online"]]
        if self.kind == "battery_low":
            return [d for d in self._devices if d["battery_low"]]
        return self._devices

    @property
    def native_value(self) -> int:
        return len(self._selected())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sel = self._selected()
        if self.kind == "total":
            return {"devices": sel}
        return {"devices": [d["name"] for d in sel],
                "details": [{k: d[k] for k in ("name", "model", "area", "battery", "last_seen")} for d in sel]}


def fleet_sensors(hass: HomeAssistant, entry: ConfigEntry) -> list[FleetSensor]:
    return [FleetSensor(hass, entry, kind) for kind in KINDS]
