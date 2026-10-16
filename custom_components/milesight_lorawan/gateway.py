"""Gateway health: one Home Assistant device per physical LoRaWAN gateway, plus network counters on the hub.

Everything comes from MQTT: the gateways listed in each uplink's rxInfo (traffic), optional gateway status
reports (Milesight "Gateway Information", ChirpStack gateway stats / connection state) and the network
server's ACK / join / error notifications.
"""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER, SIGNAL_GATEWAY, SIGNAL_GATEWAY_NEW

HUB_KINDS = {   # key -> (name, icon)
    "uplinks": ("Uplinks today", "mdi:upload-network"),
    "downlinks": ("Downlinks today", "mdi:download-network"),
    "joins": ("Joins today", "mdi:login-variant"),
    "acks": ("Downlink ACKs today", "mdi:check-network"),
    "gateways_online": ("Gateways online", "mdi:router-wireless"),
}
GW_KINDS = {    # key -> (name, icon, unit, device_class, state_class, diagnostic)
    "packets_today": ("Packets today", "mdi:counter", "packets", None, SensorStateClass.TOTAL_INCREASING, False),
    "packets_last_hour": ("Packets this hour", "mdi:chart-bar", "packets", None, SensorStateClass.MEASUREMENT, False),
    "devices_today": ("Devices heard today", "mdi:access-point", "devices", None, SensorStateClass.MEASUREMENT,
                      False),
    "last_heard": ("Last packet", "mdi:clock-outline", None, SensorDeviceClass.TIMESTAMP, None, True),
    "rx_today": ("Radio packets received today", "mdi:radio-tower", "packets", None,
                 SensorStateClass.TOTAL_INCREASING, True),
    "tx_today": ("Radio packets sent today", "mdi:radio-tower", "packets", None, SensorStateClass.TOTAL_INCREASING,
                 True),
    "cpu_temperature": ("CPU temperature", "mdi:thermometer", "°C", SensorDeviceClass.TEMPERATURE,
                        SensorStateClass.MEASUREMENT, True),
}
_STATS_KINDS = ("rx_today", "tx_today")          # only when the gateway publishes stats (ChirpStack)


def _hub(entry: ConfigEntry):
    return getattr(entry, "runtime_data", None)


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class _Base:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_GATEWAY.format(self.entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()


class HubCounter(_Base, SensorEntity):
    """Network counters for the whole site (on the hub device)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, kind: str) -> None:
        super().__init__(hass, entry)
        self.kind = kind
        self._attr_name, self._attr_icon = HUB_KINDS[kind]
        self._attr_unique_id = f"{entry.entry_id}_net_{kind}"
        if kind != "gateways_online":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")}, name=entry.title,
                                            manufacturer=MANUFACTURER, model="LoRaWAN gateway")

    @property
    def native_value(self) -> int | None:
        hub = _hub(self.entry)
        if hub is None:
            return None
        if self.kind == "gateways_online":
            ts = time.time()
            return sum(1 for gid in hub.stats.gateways if hub.stats.online(gid, ts, hub.offline_s))
        return hub.stats.counts.get(self.kind, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"milesight_role": f"net_{self.kind}", "site": self.entry.title, **(self._attrs() or {})}

    def _attrs(self) -> dict[str, Any] | None:
        hub = _hub(self.entry)
        if hub is None:
            return None
        if self.kind == "gateways_online":
            ts = time.time()
            return {"gateways": [{"id": gid, "name": g.get("name"), "online": hub.stats.online(gid, ts, hub.offline_s),
                                  "packets_today": g.get("packets_today", 0),
                                  "devices_today": len(g.get("devices_today", []))}
                                 for gid, g in hub.stats.gateways.items()]}
        if self.kind == "acks":
            return {"not_acknowledged": hub.stats.counts.get("nacks", 0)}
        if self.kind == "uplinks":
            return {"duplicates": hub.stats.counts.get("duplicates", 0), "errors": hub.stats.counts.get("errors", 0)}
        return None


def _gw_device(entry: ConfigEntry, gid: str, g: dict[str, Any]) -> DeviceInfo:
    info = g.get("info") or {}
    return DeviceInfo(identifiers={(DOMAIN, f"gw_{gid}")}, name=g.get("name") or f"Gateway {gid}",
                      manufacturer=MANUFACTURER if info or gid.startswith("24e124") else None,
                      model=info.get("model") or "LoRaWAN gateway", serial_number=info.get("sn") or gid.upper(),
                      sw_version=info.get("firmware_version"), hw_version=info.get("hardware_version"),
                      via_device=(DOMAIN, f"hub_{entry.entry_id}"))


class GatewaySensor(_Base, SensorEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, gid: str, kind: str) -> None:
        super().__init__(hass, entry)
        self.gid, self.kind = gid, kind
        name, icon, unit, dc, sc, diag = GW_KINDS[kind]
        self._attr_name, self._attr_icon = name, icon
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class, self._attr_state_class = dc, sc
        if diag:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{entry.entry_id}_gw_{gid}_{kind}"
        self._attr_device_info = _gw_device(entry, gid, _hub(entry).stats.gateways.get(gid, {}))

    @property
    def native_value(self):
        hub = _hub(self.entry)
        g = hub.stats.gateways.get(self.gid) if hub else None
        if g is None:
            return None
        ts = time.time()
        if self.kind == "packets_last_hour":
            return hub.stats.packets_last_hour(self.gid, ts)
        if self.kind == "devices_today":
            return len(g.get("devices_today", []))
        if self.kind == "last_heard":
            return dt_util.utc_from_timestamp(g["last_heard"]) if g.get("last_heard") else None
        if self.kind == "cpu_temperature":
            return _num((g.get("info") or {}).get("cpu_tempeture", (g.get("info") or {}).get("cpu_temperature")))
        return g.get(self.kind)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        hub = _hub(self.entry)
        g = hub.stats.gateways.get(self.gid) if hub else None
        if g is None:
            return None
        if self.kind == "packets_last_hour":
            return {"hourly_last_24h": hub.stats.hourly(self.gid, time.time())}
        if self.kind == "devices_today":
            names = {e.data.get("deveui"): e.title for e in self.hass.config_entries.async_entries(DOMAIN)}
            return {"devices": [names.get(d, d.upper()) for d in g.get("devices_today", [])]}
        return None


class GatewayOnline(_Base, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Online"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, gid: str) -> None:
        super().__init__(hass, entry)
        self.gid = gid
        self._attr_unique_id = f"{entry.entry_id}_gw_{gid}_online"
        self._attr_device_info = _gw_device(entry, gid, _hub(entry).stats.gateways.get(gid, {}))

    @property
    def is_on(self) -> bool | None:
        hub = _hub(self.entry)
        return hub.stats.online(self.gid, time.time(), hub.offline_s) if hub else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        hub = _hub(self.entry)
        g = hub.stats.gateways.get(self.gid) if hub else None
        if not g:
            return None
        info = g.get("info") or {}
        out = {"gateway_id": self.gid, "source": "status report" if g.get("state_ts") or g.get("info_ts")
               else "device traffic", "last_rssi": g.get("last_rssi")}
        for k in ("wan_ip", "wan_status", "cellular_status", "cellular_ip", "modem_status", "region",
                  "battery_level"):
            if k in info:
                out[k] = info[k]
        return out


def _entities_for(hass: HomeAssistant, entry: ConfigEntry, gid: str, platform: str) -> list:
    if platform == "binary_sensor":
        return [GatewayOnline(hass, entry, gid)]
    g = _hub(entry).stats.gateways.get(gid, {})
    out = []
    for k in GW_KINDS:
        e = GatewaySensor(hass, entry, gid, k)
        # status-report values: enabled when the gateway already sends them, otherwise available to enable
        if (k in _STATS_KINDS and not g.get("stats_ts")) or (k == "cpu_temperature" and not g.get("info")):
            e._attr_entity_registry_enabled_default = False
        out.append(e)
    return out


def async_setup_gateway_entities(hass: HomeAssistant, entry: ConfigEntry, async_add_entities, platform: str) -> None:
    hub = _hub(entry)
    if hub is None:
        return
    if platform == "sensor":
        async_add_entities([HubCounter(hass, entry, k) for k in HUB_KINDS])
    added: set[str] = set()

    @callback
    def _add(gid: str) -> None:
        if gid in added:
            return
        added.add(gid)
        async_add_entities(_entities_for(hass, entry, gid, platform))

    for gid in list(hub.stats.gateways):
        _add(gid)
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_GATEWAY_NEW.format(entry.entry_id), _add))
