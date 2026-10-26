"""Gateway health: one Home Assistant device per physical LoRaWAN gateway, plus network counters on the hub.

Everything comes from MQTT: the gateways listed in each uplink's rxInfo (traffic), optional gateway status
reports (Milesight "Gateway Information", ChirpStack gateway stats / connection state) and the network
server's ACK / join / error notifications.
"""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.button import ButtonEntity
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
    "connection": ("Connection", "mdi:lan-connect", None, None, None, True),
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
    from .gateway_discovery import connection_label
    info = g.get("info") or {}
    conn = connection_label(g.get("conn"), short=True)
    model = info.get("model") or g.get("model") or "LoRaWAN gateway"
    return DeviceInfo(identifiers={(DOMAIN, f"gw_{gid}")}, name=g.get("name") or f"Gateway {gid}",
                      manufacturer=MANUFACTURER if info or gid.startswith("24e124") else None,
                      model=f"{model} · {conn}" if g.get("conn") else model, serial_number=info.get("sn") or gid.upper(),
                      sw_version=info.get("firmware_version"), hw_version=info.get("hardware_version"),
                      via_device=(DOMAIN, f"hub_{entry.entry_id}"), suggested_area=g.get("area"),
                      configuration_url=f"http://{g['ip']}" if g.get("ip") else None)


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
        if self.kind == "connection":
            from .gateway_discovery import connection_label
            return connection_label(g.get("conn"))
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
        if self.kind == "connection":
            from .gateway_discovery import found_label
            return {"milesight_role": "gateway_connection", "gateway_id": self.gid.upper(),
                    "found_via": found_label(g.get("found"), g.get("ip")), "network_servers": g.get("conn") or [],
                    "ip_address": g.get("ip"), "mac_address": (g.get("mac") or "").upper() or None,
                    "web_page": f"http://{g['ip']}" if g.get("ip") else None,
                    "first_seen": dt_util.utc_from_timestamp(g["first_seen"]).isoformat() if g.get("first_seen") else None,
                    "confirmed": bool(g.get("approved"))}
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
    if platform == "button":
        return [GatewayConfigureButton(hass, entry, gid)]
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
    if platform in ("sensor", "binary_sensor", "button"):
        pass
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


class GatewayConfigureButton(_Base, ButtonEntity):
    """Configure this gateway over the LAN (point it at Home Assistant, set up its network server) – opens a form
    for the gateway's admin login under Settings -> Devices & services."""

    _attr_name = "Configure over LAN"
    _attr_icon = "mdi:cog-transfer-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, gid: str) -> None:
        super().__init__(hass, entry)
        self.gid = gid
        self._attr_unique_id = f"{entry.entry_id}_gw_{gid}_configure"
        self._attr_device_info = _gw_device(entry, gid, _hub(entry).stats.gateways.get(gid, {}))

    async def async_press(self) -> None:
        g = (_hub(self.entry).stats.gateways.get(self.gid) or {}) if _hub(self.entry) else {}
        await self.hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "gateway_reconfigure"},
            data={"gateway_id": self.gid, "ip": g.get("ip"), "hub_entry_id": self.entry.entry_id,
                  "model": (g.get("info") or {}).get("model") or g.get("model")})


class GatewayDevicesSensor(_Base, SensorEntity):
    """Devices registered on the gateway's network server (read with 'Sync devices with gateway')."""

    _attr_name = "Devices on gateway"
    _attr_icon = "mdi:format-list-checks"
    _attr_native_unit_of_measurement = "devices"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_ns_devices"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")})

    @property
    def native_value(self) -> int | None:
        hub = _hub(self.entry)
        devs = hub.gateway_devices.get("devices") if hub else None
        return len(devs) if devs is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hub = _hub(self.entry)
        g = hub.gateway_devices if hub else {}
        known = {e.unique_id for e in self.hass.config_entries.async_entries(DOMAIN)}
        at = g.get("at")
        devs = g.get("devices", [])
        # keep the attribute well under Home Assistant's 16 KB recorder limit on big gateways: a compact list,
        # capped, with only what the dashboard and sync need.
        compact = [{"deveui": d.get("deveui"), "name": d.get("name"),
                    "in_home_assistant": d.get("deveui") in known} for d in devs[:200]]
        return {"milesight_role": "net_registered", "site": self.entry.title,
                "devices": compact, "devices_total": len(devs), "devices_shown": len(compact),
                "not_in_home_assistant": sum(1 for d in devs if d.get("deveui") not in known
                                             and (not hub or not hub.ns_application
                                                  or d.get("application_id") in ("", hub.ns_application))),
                "application_id": hub.ns_application if hub else None, "profile_id": hub.ns_profile if hub else None,
                "last_sync": dt_util.utc_from_timestamp(at).isoformat() if at else None, "error": g.get("error")}


class OpenAlertsSensor(SensorEntity):
    """Alerts that nobody has acknowledged yet (alert escalation)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Open alerts"
    _attr_icon = "mdi:bell-ring-outline"
    _attr_native_unit_of_measurement = "alerts"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_alerts_open"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")})

    async def async_added_to_hass(self) -> None:
        from .const import SIGNAL_ALERTS_CHANGED
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_ALERTS_CHANGED.format(self.entry.entry_id), self.async_write_ha_state))

    @property
    def native_value(self) -> int | None:
        hub = _hub(self.entry)
        return len(hub.alerts.engine.unacknowledged()) if hub else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hub = _hub(self.entry)
        if hub is None:
            return {"milesight_role": "alerts_open"}
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
        level = {0: "waiting", 1: "notified", 2: "escalated"}

        def fmt(ts: float | None) -> str | None:
            return dt_util.utc_from_timestamp(ts).astimezone(tz).strftime("%d %b %H:%M") if ts else None
        alerts = [{"id": a["id"], "title": a["title"], "message": a["message"], "severity": a.get("severity"),
                   "category": a.get("category"), "since": fmt(a.get("first")),
                   "status": "acknowledged" if a.get("acked") else ("quiet hours" if a.get("held")
                                                                    else level.get(a.get("level", 0))),
                   "acknowledged_by": (a.get("acked") or {}).get("by"), "notified": a.get("notified")}
                  for a in sorted(hub.alerts.engine.open_alerts(), key=lambda x: x.get("first") or 0)]
        last = hub.alerts.last_sent
        cfg = hub.alerts.cfg
        now_local = dt_util.utc_from_timestamp(time.time()).astimezone(tz)

        def who(targets: list[str]) -> list[str]:
            # "notify.mobile_app_juan" -> "juan"; keep anything that isn't a mobile_app target as-is
            out = []
            for t in targets:
                n = t.split(".", 1)[-1]
                out.append(n[len("mobile_app_"):] if n.startswith("mobile_app_") else n)
            return out
        def hhmm(hour: int | None) -> str | None:
            return f"{int(hour):02d}:00" if isinstance(hour, (int, float)) else None
        quiet = (f"{hhmm(cfg.quiet_start)} – {hhmm(cfg.quiet_end)}"
                 if cfg.quiet_start is not None and cfg.quiet_end is not None else None)
        return {"milesight_role": "alerts_open", "site": self.entry.title, "alerts": alerts,
                "escalation_enabled": cfg.enabled,
                "on_call": who(cfg.first_line(now_local)) if cfg.enabled else [],
                "backup": who(list(cfg.backup)),
                "primary": who(list(cfg.primary)),
                "escalate_min": cfg.escalate_min,
                "quiet_hours": quiet,
                "has_rota": bool(cfg.rota),
                "snooze_min": cfg.snooze_min,
                "last_notification": {**last, "at": fmt(last["at"])} if last else None}


class AlertSummarySensor(SensorEntity):
    """Alerts in the last 7 days; categories, noisiest devices and mean time to acknowledge as attributes."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Alerts last 7 days"
    _attr_icon = "mdi:chart-timeline-variant"
    _attr_native_unit_of_measurement = "alerts"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_alerts_week"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")})

    async def async_added_to_hass(self) -> None:
        from .const import SIGNAL_ALERTS_CHANGED
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_ALERTS_CHANGED.format(self.entry.entry_id), self.async_write_ha_state))

    @property
    def native_value(self) -> int | None:
        hub = _hub(self.entry)
        return hub.alerts.summary()["alerts"] if hub else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hub = _hub(self.entry)
        if hub is None:
            return {}
        from .alerts import summary_text
        s = hub.alerts.summary()
        cfg = hub.alerts.cfg
        from datetime import datetime
        now = datetime.now(dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC)
        return {"milesight_role": "alerts_summary", **{k: v for k, v in s.items() if k != "alerts"},
                "summary": summary_text(s), "on_call_now": cfg.first_line(now),
                "escalation_chain": list(cfg.backup)}


class ComplianceReportsSensor(SensorEntity):
    """Cold-chain compliance reports: when the last ones were made; the recent reports (unit, period, status,
    PDF link) as attributes for the Cold chain dashboard."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Compliance reports"
    _attr_icon = "mdi:file-certificate-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_compliance_reports"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")})

    async def async_added_to_hass(self) -> None:
        from .compliance_ha import SIGNAL_COMPLIANCE
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_COMPLIANCE.format(self.entry.entry_id), self.async_write_ha_state))

    def _mgr(self):
        return getattr(_hub(self.entry), "compliance", None)

    @property
    def native_value(self):
        mgr = self._mgr()
        reps = mgr.reports(1) if mgr else []
        return dt_util.parse_datetime(reps[0]["created"]) if reps else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from .compliance_ha import CONF_COMPLIANCE_NOTIFY, CONF_COMPLIANCE_SCHEDULE, DEFAULT_COMPLIANCE_SCHEDULE
        mgr = self._mgr()
        o = self.entry.options
        return {"milesight_role": "compliance_reports", "reports": mgr.reports(40) if mgr else [],
                "schedule": o.get(CONF_COMPLIANCE_SCHEDULE, DEFAULT_COMPLIANCE_SCHEDULE),
                "email": o.get(CONF_COMPLIANCE_NOTIFY) or None}


def hub_extra_sensors(hass: HomeAssistant, entry: ConfigEntry) -> list:
    hub = _hub(entry)
    out: list = [OpenAlertsSensor(hass, entry), AlertSummarySensor(hass, entry), ComplianceReportsSensor(hass, entry)]
    if hub is not None and hub.ns is not None:
        out.append(GatewayDevicesSensor(hass, entry))
    if hub is not None and getattr(hub, "lns", None) is not None:
        from .lns_ha import NetworkServerSensor
        out.append(NetworkServerSensor(hass, entry))
    return out
