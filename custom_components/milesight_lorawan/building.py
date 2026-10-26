"""Building overview entities: Site (company / contact / logo …) and building health, comfort, air quality,
people, alerts and averages on the gateway device. The maths is in building_calc.py."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from .const import (
    CONF_BRAND_SIDEBAR,
    CONF_CO2_ALERT,
    CONF_SIDEBAR_TITLE,
    CONF_SITE_ADDRESS,
    CONF_SITE_AREAS,
    CONF_SITE_COMPANY,
    CONF_SITE_CONTACT,
    CONF_SITE_EMAIL,
    CONF_SITE_LOGO,
    CONF_SITE_OUTSIDE,
    CONF_SITE_PHONE,
    DEFAULT_CO2_ALERT,
    DEFAULT_SITE_LOGO,
    DOMAIN,
    MANUFACTURER,
)

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .building_calc import AIR_LEVELS, AVERAGES, compute_building
from .models import entity_specs

SIGNAL_BUILDING = f"{DOMAIN}_building_{{}}"   # .format(hub entry_id)

KINDS = {  # kind -> (name, unit, icon, state_class)
    "health": ("Building health", "%", "mdi:heart-pulse", SensorStateClass.MEASUREMENT),
    "comfort": ("Building comfort", "%", "mdi:emoticon-happy-outline", SensorStateClass.MEASUREMENT),
    "air_quality": ("Air quality", None, "mdi:air-filter", None),
    "systems": ("Systems health", "%", "mdi:router-network", SensorStateClass.MEASUREMENT),
    "people": ("People in building", "people", "mdi:account-group", SensorStateClass.MEASUREMENT),
    "alerts": ("Alerts", "alerts", "mdi:alert-outline", SensorStateClass.MEASUREMENT),
}


def hub_device(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")}, name=entry.title, manufacturer=MANUFACTURER,
                      model="LoRaWAN gateway")


def site_info(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Site details: Home Assistant's own settings, completed by the gateway's Site information options."""
    o = entry.options
    cfg = hass.config
    contact_id = o.get(CONF_SITE_CONTACT) or None
    contact = hass.states.get(contact_id) if contact_id else None
    company = (o.get(CONF_SITE_COMPANY) or "").strip() or cfg.location_name
    # the text the sidebar header shows instead of "Home Assistant" (custom override, else the company name);
    # "" means the feature is off and the frontend leaves the default title alone
    brand = o.get(CONF_BRAND_SIDEBAR, True)
    sidebar_title = (((o.get(CONF_SIDEBAR_TITLE) or "").strip() or company) if brand else "")
    return {
        "company": company,
        "sidebar_title": sidebar_title,
        "site": entry.title,
        "address": o.get(CONF_SITE_ADDRESS) or None,
        "contact": (contact.attributes.get("friendly_name") if contact else None) or None,
        "contact_entity": contact_id,
        "contact_picture": contact.attributes.get("entity_picture") if contact else None,
        "phone": o.get(CONF_SITE_PHONE) or None,
        "email": o.get(CONF_SITE_EMAIL) or None,
        "logo": (o[CONF_SITE_LOGO] if CONF_SITE_LOGO in o else DEFAULT_SITE_LOGO) or None,
        "country": getattr(cfg, "country", None),
        "time_zone": cfg.time_zone,
        "latitude": cfg.latitude,
        "longitude": cfg.longitude,
        "outside_sensor": o.get(CONF_SITE_OUTSIDE) or None,
        "co2_alert": float(o.get(CONF_CO2_ALERT, DEFAULT_CO2_ALERT)),
    }


def area_names(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Configured dashboard areas (area ids) -> names, in order."""
    ids = entry.options.get(CONF_SITE_AREAS) or []
    if not ids:
        return []
    try:
        from homeassistant.helpers import area_registry as ar
        reg = ar.async_get(hass)
        return [a.name for a in (reg.async_get_area(i) for i in ids) if a is not None]
    except Exception:  # noqa: BLE001 - registry not available (tests)
        return list(ids)


class BuildingTracker:
    """Recomputes the building overview every minute (and when a device's online / battery state changes)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, areas_tracker) -> None:
        self.hass, self.entry, self.areas = hass, entry, areas_tracker
        self.data: dict[str, Any] = {}
        self.since: dict[str, float] = {}
        self._last = 0.0

    def _devices(self) -> list[dict[str, Any]]:
        from .fleet import fleet_devices
        out = []
        by_eui = {}
        for e in self.hass.config_entries.async_entries(DOMAIN):
            rt = getattr(e, "runtime_data", None)
            if rt is not None and hasattr(rt, "deveui"):
                by_eui[rt.deveui.upper()] = rt
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
        for d in fleet_devices(self.hass, self.entry):
            rt = by_eui.get(d["deveui"])
            last = rt.commands.last if rt is not None else None
            failed = None
            if last and last.get("status") == "failed" and time.time() - (last.get("time") or 0) < 86400:
                failed = f"{last['command'].replace('_', ' ')}: {last.get('detail') or 'no answer'}"
            seen = rt.meta.get("last_seen") if rt is not None else None
            units = {s.key: s.unit for s in entity_specs(rt.model.key)} if rt is not None else {}
            out.append({**d, "values": rt.values if rt is not None else {}, "units": units, "command_failed": failed,
                        "last_seen_text": datetime.fromtimestamp(seen, tz).strftime("%d %b %H:%M") if seen else None})
        return out

    def _gateways(self) -> list[dict[str, Any]]:
        hub = getattr(self.entry, "runtime_data", None)
        if hub is None or not hasattr(hub, "stats"):
            return []
        ts = time.time()
        return [{"name": g.get("name") or gid, "online": hub.stats.online(gid, ts, hub.offline_s)}
                for gid, g in hub.stats.gateways.items()]

    @callback
    def update(self, _now: Any = None) -> None:
        site = site_info(self.hass, self.entry)
        summary = dict(self.areas.summary) if self.areas is not None else {}
        data = compute_building(self._devices(), summary, self._gateways(), site["co2_alert"],
                                area_names(self.hass, self.entry))
        ts = time.time()
        keys = {a["key"] for a in data["alerts"]}
        self.since = {k: v for k, v in self.since.items() if k in keys}
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
        for a in data["alerts"]:
            self.since.setdefault(a["key"], ts)
            a["since"] = datetime.fromtimestamp(self.since[a["key"]], tz).strftime("%H:%M")
        if self.areas is not None:
            for a in data["areas"]:
                if a in summary:
                    summary[a] = {**summary[a], "occupied_today": self.areas.today_share(a)}
        data["area_details"] = {a: summary.get(a, {}) for a in data["areas"]}
        self.data = data
        async_dispatcher_send(self.hass, SIGNAL_BUILDING.format(self.entry.entry_id))

    @callback
    def maybe_update(self) -> None:
        if time.monotonic() - self._last >= 10:
            self._last = time.monotonic()
            self.update()


class _BuildingBase(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, tracker: BuildingTracker) -> None:
        self.hass, self.entry, self.tracker = hass, entry, tracker
        self._attr_device_info = hub_device(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_BUILDING.format(self.entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()


class SiteSensor(_BuildingBase):
    """State: the company name. Attributes: everything the banner shows."""

    _attr_name = "Site"
    _attr_icon = "mdi:office-building-marker"

    def __init__(self, hass, entry, tracker) -> None:
        super().__init__(hass, entry, tracker)
        self._attr_unique_id = f"{entry.entry_id}_site"

    @property
    def native_value(self) -> str | None:
        return (site_info(self.hass, self.entry)["company"] or "")[:255] or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = site_info(self.hass, self.entry)
        d = self.tracker.data
        info.update({"milesight_role": "site", "areas": d.get("areas", []), "alerts": len(d.get("alerts", [])),
                     "status": (f"{len(d['alerts'])} item{'s' if len(d['alerts']) != 1 else ''} need attention"
                                if d.get("alerts") else "All systems normal")})
        return info


class BuildingSensor(_BuildingBase):
    def __init__(self, hass, entry, tracker, kind: str) -> None:
        super().__init__(hass, entry, tracker)
        self.kind = kind
        if kind.startswith("avg_"):
            name, unit, dc, prec = AVERAGES[kind[4:]]
            self._attr_name = name
            self._attr_native_unit_of_measurement = unit
            self._attr_device_class = SensorDeviceClass(dc) if dc else None
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = prec
            self._attr_icon = "mdi:molecule" if dc is None else None
        else:
            name, unit, icon, sc = KINDS[kind]
            self._attr_name, self._attr_native_unit_of_measurement, self._attr_icon = name, unit, icon
            self._attr_state_class = sc
            if kind == "air_quality":
                self._attr_device_class = SensorDeviceClass.ENUM
                self._attr_options = AIR_LEVELS
        self._attr_unique_id = f"{entry.entry_id}_building_{kind}"

    @property
    def native_value(self):
        d = self.tracker.data
        if self.kind.startswith("avg_"):
            return d.get("averages", {}).get(self.kind[4:])
        if self.kind == "alerts":
            return len(d.get("alerts", [])) if d else None
        return d.get(self.kind)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Every building sensor carries milesight_role / site, so dashboards can find it whatever its entity id."""
        return {"milesight_role": f"building_{self.kind}", "site": self.entry.title, **(self._attrs() or {})}

    def _attrs(self) -> dict[str, Any] | None:
        d = self.tracker.data
        if not d:
            return None
        if self.kind == "alerts":
            return {"alerts": [{k: a.get(k) for k in ("severity", "where", "what", "detail", "since")}
                               for a in d["alerts"]]}
        if self.kind == "health":
            return {"comfort": d["comfort"], "air_score": d["air_score"], "systems": d["systems"]}
        if self.kind == "comfort":
            return {"comfortable_areas": d["comfortable_areas"], "areas": d["areas_with_comfort"]}
        if self.kind == "air_quality":
            return {"score": d["air_score"], **{k: v for k, v in d["averages"].items()}}
        if self.kind == "systems":
            return {"devices": d["devices"], "devices_online": d["devices_online"]}
        if self.kind == "people":
            return {"occupied_areas": d["occupied_areas"], "areas": d["areas_with_occupancy"]}
        return None


def building_sensors(hass: HomeAssistant, entry: ConfigEntry, areas_tracker) -> tuple[BuildingTracker, list]:
    tracker = BuildingTracker(hass, entry, areas_tracker)
    tracker.update()
    ents: list = [SiteSensor(hass, entry, tracker)] + [BuildingSensor(hass, entry, tracker, k) for k in KINDS]
    keys: set[str] = set()
    for e in hass.config_entries.async_entries(DOMAIN):
        rt = getattr(e, "runtime_data", None)
        if rt is not None and hasattr(rt, "model"):
            keys |= {s.key for s in entity_specs(rt.model.key) if s.key in AVERAGES and s.unit == AVERAGES[s.key][1]}
    ents += [BuildingSensor(hass, entry, tracker, f"avg_{k}") for k in AVERAGES if k in keys]
    entry.async_on_unload(async_track_time_interval(hass, tracker.update, timedelta(seconds=60)))
    from .const import SIGNAL_FLEET
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_FLEET, tracker.maybe_update))
    return tracker, ents
