"""Gateway-level fleet overview sensors (online / offline / low battery, device list)."""
from __future__ import annotations

import time

from datetime import datetime, timedelta, timezone
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


def maintenance_fields(rt, entry, ts: float) -> dict[str, Any]:
    """For the maintenance dashboard and the handover report."""
    v, meta = rt.values, rt.meta
    last = meta.get("last_seen")
    rb = v.get("battery_replace_by")
    log = list(meta.get("_service_log") or [])
    fw = rt.raw.get("firmware_version")
    return {
        "battery_days_left": v.get("battery_days_left"),
        "battery_replace_by": datetime.fromtimestamp(rb, rt.cal.tz).date().isoformat() if rb else None,
        "battery_forecast": (rt.attrs.get("battery_replace_by") or {}).get("reason") or
                            (rt.attrs.get("battery_replace_by") or {}).get("method"),
        "firmware": str(fw) if fw is not None else None,
        "hardware": str(rt.raw.get("hardware_version")) if rt.raw.get("hardware_version") is not None else None,
        "purpose": getattr(getattr(rt, "purpose", None), "label", None),
        "network_server": v.get("network_server"),
        "latitude": (rt.fixed_location() or (None, None))[0] if hasattr(rt, "fixed_location") else None,
        "longitude": (rt.fixed_location() or (None, None))[1] if hasattr(rt, "fixed_location") else None,
        "offline_hours": round((ts - last) / 3600, 1) if last and v.get("online") is False else None,
        "service": [{"at": datetime.fromtimestamp(e["at"], timezone.utc).isoformat(timespec="seconds"), "kind": e["kind"], "text": e["text"],
                     "by": e.get("by")} for e in log[-3:]][::-1],
    }


def fleet_devices(hass: HomeAssistant, hub_entry: ConfigEntry) -> list[dict[str, Any]]:
    """All device entries this gateway serves (every device when there is only one gateway)."""
    hubs = [e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB]
    hub = getattr(hub_entry, "runtime_data", None)
    heard = set(hub.last_uplink) if hub is not None else set()
    ts_now = time.time()
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
            "sf": rt.meta.get("spreading_factor"), "gateway": v.get("gateway"),
            "gateways_heard": v.get("gateways_heard"), "signal": v.get("signal_quality"),
            "packet_loss": v.get("packet_loss_today"), "command": v.get("command_status"),
            "last_seen": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
            **maintenance_fields(rt, entry, ts_now),
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
        role = {"milesight_role": f"fleet_{self.kind}", "site": self.entry.title}
        if self.kind == "total":
            return {**role, "devices": sel}
        return {**role, "devices": [d["name"] for d in sel],
                "details": [{k: d[k] for k in ("name", "model", "area", "battery", "last_seen")} for d in sel]}


def fleet_sensors(hass: HomeAssistant, entry: ConfigEntry) -> list[FleetSensor]:
    return [FleetSensor(hass, entry, kind) for kind in KINDS]


# --------------------------------------------------------------------------
# Building analytics per area: comfort score, occupancy, utilisation, hourly occupancy heat map
# --------------------------------------------------------------------------
def _band(v: float, good_lo: float, good_hi: float, zero_lo: float, zero_hi: float) -> float:
    """100 inside [good_lo, good_hi], falling linearly to 0 at zero_lo / zero_hi."""
    if good_lo <= v <= good_hi:
        return 100.0
    if v < good_lo:
        return max(0.0, 100 * (v - zero_lo) / (good_lo - zero_lo))
    return max(0.0, 100 * (zero_hi - v) / (zero_hi - good_hi))


def comfort_score(temperature: float | None, humidity: float | None, co2: float | None) -> int | None:
    """0-100: temperature 20-24 °C, humidity 30-60 %, CO2 up to 800 ppm count as fully comfortable."""
    parts = []
    if isinstance(temperature, (int, float)):
        parts.append(_band(temperature, 20, 24, 15, 29))
    if isinstance(humidity, (int, float)):
        parts.append(_band(humidity, 30, 60, 15, 80))
    if isinstance(co2, (int, float)):
        parts.append(_band(co2, 0, 800, -1, 1800))
    return round(sum(parts) / len(parts)) if parts else None


def _area_name(hass: HomeAssistant, rt, entry) -> str | None:
    try:
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr
        dev = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, rt.deveui)})
        if dev is not None and dev.area_id:
            area = ar.async_get(hass).async_get_area(dev.area_id)
            if area is not None:
                return area.name
    except Exception:  # noqa: BLE001 - registries unavailable (tests)
        pass
    return entry.data.get("area")


def area_summary(hass: HomeAssistant, hub_entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    hubs = [e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB]
    hub = getattr(hub_entry, "runtime_data", None)
    heard = set(hub.last_uplink) if hub is not None else set()
    acc: dict[str, dict[str, list]] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        rt = getattr(entry, "runtime_data", None)
        if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE or rt is None:
            continue
        if len(hubs) > 1 and rt.deveui not in heard:
            continue
        area = _area_name(hass, rt, entry)
        if not area:
            continue
        v = rt.values
        a = acc.setdefault(area, {"temperature": [], "humidity": [], "co2": [], "occupied": [], "utilisation": [],
                                  "people": [], "devices": []})
        a["devices"].append(entry.title)
        if not v.get("online"):
            continue
        for k in ("temperature", "humidity", "co2"):
            if isinstance(v.get(k), (int, float)):
                a[k].append(v[k])
        if v.get("occ_occupied") is not None:
            a["occupied"].append(bool(v["occ_occupied"]))
        if isinstance(v.get("occ_utilisation_today_pct"), (int, float)):
            a["utilisation"].append(v["occ_utilisation_today_pct"])
        if isinstance(v.get("people_count_all"), (int, float)):
            a["people"].append(v["people_count_all"])
    out = {}
    for area, a in acc.items():
        t = round(sum(a["temperature"]) / len(a["temperature"]), 1) if a["temperature"] else None
        h = round(sum(a["humidity"]) / len(a["humidity"]), 1) if a["humidity"] else None
        c = max(a["co2"]) if a["co2"] else None
        out[area] = {
            "temperature": t, "humidity": h, "co2": c, "comfort": comfort_score(t, h, c),
            "occupied": any(a["occupied"]) if a["occupied"] else None,
            "utilisation_today": round(sum(a["utilisation"]) / len(a["utilisation"]), 1) if a["utilisation"] else None,
            "people": sum(a["people"]) if a["people"] else None,
            "devices": a["devices"],
        }
    return out


AREA_KINDS = {  # kind -> (name suffix, unit, icon)
    "comfort": ("comfort", "%", "mdi:emoticon-happy-outline"),
    "occupancy": ("occupancy", "%", "mdi:account-clock"),
}


class AreaSensor(SensorEntity):
    """<area> comfort (0-100) or <area> occupancy (occupied share of today, with hourly heat map)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, area: str, kind: str, tracker: "AreaTracker") -> None:
        self.hass = hass
        self.entry = entry
        self.area = area
        self.kind = kind
        self.tracker = tracker
        suffix, unit, icon = AREA_KINDS[kind]
        slug = "".join(ch if ch.isalnum() else "_" for ch in area.lower())
        self._attr_name = f"{area} {suffix}"
        self._attr_unique_id = f"{entry.entry_id}_area_{slug}_{kind}"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")}, name=entry.title,
                                            manufacturer=MANUFACTURER, model="LoRaWAN gateway")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_FLEET, self._refresh))
        self.async_on_remove(async_dispatcher_connect(self.hass, f"{DOMAIN}_areas_{self.entry.entry_id}", self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()

    @property
    def _data(self) -> dict[str, Any]:
        return self.tracker.summary.get(self.area, {})

    @property
    def native_value(self):
        if self.kind == "comfort":
            return self._data.get("comfort")
        return self.tracker.today_share(self.area)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._data
        if self.kind == "comfort":
            return {"area": self.area, "kind": "comfort",
                    **{k: d.get(k) for k in ("temperature", "humidity", "co2", "devices")}}
        return {"area": self.area, "kind": "occupancy", "occupied_now": d.get("occupied"), "people_now": d.get("people"),
                "utilisation_today": d.get("utilisation_today"), "hourly_today": self.tracker.hourly(self.area),
                "hourly_yesterday": self.tracker.hourly(self.area, yesterday=True)}


class AreaTracker:
    """Samples every area once a minute: hourly share of minutes occupied (today / yesterday)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
        self.hass = hass
        self.entry = entry
        self.add = async_add_entities
        self.summary: dict[str, dict] = {}
        self.known: set[tuple[str, str]] = set()
        self.data: dict[str, dict] = {}       # area -> {"day": iso, "occ": [24], "n": [24], "prev": [24] | None}
        self.store = None                     # Store: the hourly history survives restarts and reloads

    @callback
    def sample(self, _now=None) -> None:
        self.summary = area_summary(self.hass, self.entry)
        now = dt_util.now()
        day, hour = now.date().isoformat(), now.hour
        for area, s in self.summary.items():
            d = self.data.get(area)
            if d is None or d["day"] != day:
                prev = d["occ_pct"] if d and d.get("day") == (now.date() - timedelta(days=1)).isoformat() else None
                d = self.data[area] = {"day": day, "occ": [0] * 24, "n": [0] * 24, "prev": prev, "occ_pct": [None] * 24}
            if s.get("occupied") is not None:
                d["n"][hour] += 1
                d["occ"][hour] += 1 if s["occupied"] else 0
                d["occ_pct"][hour] = round(100 * d["occ"][hour] / d["n"][hour])
        new = []
        for area, s in self.summary.items():
            kinds = ["comfort"] if s.get("comfort") is not None or ("comfort", area) in self.known else []
            if s.get("occupied") is not None or ("occupancy", area) in self.known:
                kinds.append("occupancy")
            for kind in kinds:
                if (kind, area) not in self.known:
                    self.known.add((kind, area))
                    new.append(AreaSensor(self.hass, self.entry, area, kind, self))
        if new:
            self.add(new)
        if self.store is not None:
            self.store.async_delay_save(lambda: self.data, 120)
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(self.hass, f"{DOMAIN}_areas_{self.entry.entry_id}")

    def hourly(self, area: str, yesterday: bool = False) -> list[int | None]:
        d = self.data.get(area)
        if d is None:
            return [None] * 24
        return list(d["prev"] or [None] * 24) if yesterday else list(d["occ_pct"])

    def today_share(self, area: str) -> int | None:
        d = self.data.get(area)
        if d is None or not sum(d["n"]):
            return None
        return round(100 * sum(d["occ"]) / sum(d["n"]))


async def async_setup_areas(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> AreaTracker:
    from homeassistant.helpers.storage import Store
    from .const import STORAGE_VERSION
    tracker = AreaTracker(hass, entry, async_add_entities)
    tracker.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.areas_{entry.entry_id}")
    saved = await tracker.store.async_load()
    if isinstance(saved, dict):
        tracker.data = {a: d for a, d in saved.items() if isinstance(d, dict) and "day" in d}
    entry.async_on_unload(lambda: hass.async_create_task(tracker.store.async_save(tracker.data)))
    tracker.sample()
    entry.async_on_unload(async_track_time_interval(hass, tracker.sample, timedelta(seconds=60)))
    return tracker
