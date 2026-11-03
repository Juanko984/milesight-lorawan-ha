"""Team & clock-in: the people layer on top of the sensors.

Workers clock in and out from the Home Assistant mobile app (an actionable notification, a widget or an NFC
tag that calls the clock_in / clock_out services), or from the Team card. Each clock-in stamps the time and
the worker's GPS (from their linked device_tracker, which the Companion app keeps live). A clock-in outside
the site's radius is **blocked and recorded** — never counted as on-site. Everything runs on the gateway.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.util import dt as dt_util

from . import team_calc as tc
from .building import hub_device
from .const import DOMAIN, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)
SIGNAL_TEAM = f"{DOMAIN}_team_{{}}"   # .format(hub entry_id)
SERVICE_CLOCK_IN, SERVICE_CLOCK_OUT = "clock_in", "clock_out"


class TeamManager:
    """Holds workers + clock events, the sensor snapshot, and the clock / mutation logic."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.store = None
        self.workers: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.radius_m: float = tc.DEFAULT_RADIUS_M
        self.data: dict[str, Any] = {}

    # -- time windows (local) ---------------------------------------------
    def _windows(self, now: float) -> tuple[float, float]:
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
        local = datetime.fromtimestamp(now, tz)
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        week = day - timedelta(days=local.weekday())
        return day.timestamp(), week.timestamp()

    def refresh(self) -> None:
        now = time.time()
        day_start, week_start = self._windows(now)
        self.data = {"radius_m": self.radius_m,
                     **tc.summarize(self.workers, self.events, now, day_start, week_start)}
        if self.store is not None:
            self.store.async_delay_save(self._to_store, 20)
        async_dispatcher_send(self.hass, SIGNAL_TEAM.format(self.entry.entry_id))

    def _to_store(self) -> dict[str, Any]:
        return {"workers": self.workers, "events": self.events[-2000:], "radius_m": self.radius_m}

    def _get(self, wid: str) -> dict[str, Any] | None:
        return next((w for w in self.workers if w["id"] == wid), None)

    def resolve(self, who: str) -> dict[str, Any] | None:
        """Find a worker by id or (case-insensitive) name."""
        w = self._get(who)
        if w:
            return w
        low = str(who).strip().lower()
        return next((x for x in self.workers if str(x.get("name", "")).strip().lower() == low), None)

    # -- mutations (WebSocket) --------------------------------------------
    def add_worker(self, name: str, **kw: Any) -> dict[str, Any]:
        w = tc.new_worker(name, wid=tc.make_id(x["id"] for x in self.workers), **kw)
        self.workers.append(w)
        self.refresh()
        return w

    def update_worker(self, wid: str, patch: dict[str, Any]) -> None:
        w = self._get(wid)
        if w is None:
            raise ValueError("worker not found")
        for k in ("name", "role", "tracker", "method", "active"):
            if k in patch:
                w[k] = patch[k]
        if "name" in patch:
            w["initials"] = tc.initials(w["name"])
        self.refresh()

    def delete_worker(self, wid: str) -> None:
        self.workers = [w for w in self.workers if w["id"] != wid]
        self.refresh()

    def set_radius(self, radius_m: float) -> None:
        self.radius_m = max(20.0, float(radius_m))
        self.refresh()

    # -- clocking ---------------------------------------------------------
    def _tracker_gps(self, tracker: str | None):
        if not tracker:
            return None, None, None
        st = self.hass.states.get(tracker)
        if st is None:
            return None, None, None
        a = st.attributes or {}
        return a.get("latitude"), a.get("longitude"), a.get("gps_accuracy")

    def clock(self, who: str, kind: str, *, lat: Any = None, lon: Any = None,
              accuracy: Any = None) -> dict[str, Any]:
        """Clock a worker in or out. Returns {ok, status, distance_m, worker}."""
        w = self.resolve(who)
        if w is None:
            return {"ok": False, "error": f"no worker '{who}'"}
        if lat is None or lon is None:                         # fall back to the worker's phone tracker
            t_lat, t_lon, t_acc = self._tracker_gps(w.get("tracker"))
            lat = t_lat if lat is None else lat
            lon = t_lon if lon is None else lon
            accuracy = t_acc if accuracy is None else accuracy
        ts = time.time()
        if kind == tc.OUT:
            ev = tc.clock_event(w["id"], tc.OUT, ts, status=tc.CLOCKED_OUT, lat=lat, lon=lon, accuracy=accuracy)
            self.events.append(ev)
            self.refresh()
            return {"ok": True, "status": tc.CLOCKED_OUT, "worker": w["name"]}
        site_lat = getattr(self.hass.config, "latitude", None)
        site_lon = getattr(self.hass.config, "longitude", None)
        allowed, dist, status = tc.validate_clock_in(site_lat, site_lon, lat, lon, self.radius_m)
        ev = tc.clock_event(w["id"], tc.IN, ts, status=status, lat=lat, lon=lon, distance_m=dist, accuracy=accuracy)
        self.events.append(ev)
        self.refresh()
        if not allowed:
            _LOGGER.warning("Clock-in blocked for %s: %.0f m from site (radius %.0f m)", w["name"], dist or 0, self.radius_m)
        return {"ok": allowed, "status": status, "distance_m": dist, "worker": w["name"]}

    def delete_event(self, ts: float, worker: str) -> None:
        self.events = [e for e in self.events if not (e.get("ts") == ts and e.get("worker") == worker)]
        self.refresh()


class TeamSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Team"
    _attr_icon = "mdi:account-group"
    _attr_native_unit_of_measurement = "on site"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mgr: TeamManager) -> None:
        self.hass, self.entry, self.mgr = hass, entry, mgr
        self._attr_device_info = hub_device(entry)
        self._attr_unique_id = f"{entry.entry_id}_team"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_TEAM.format(self.entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self):
        return self.mgr.data.get("on_site") if self.mgr.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"milesight_role": "team", "site": self.entry.title, "hub": self.entry.entry_id,
                **(self.mgr.data or {})}


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_CLOCK_IN):
        return
    try:  # Home Assistant 2026.x replaced voluptuous with probatio (same API)
        import probatio as vol
    except ImportError:  # older Home Assistant
        import voluptuous as vol

    def _team(call) -> TeamManager | None:
        for hub in hass.data.get(DOMAIN, {}).get("hubs", {}).values():
            if getattr(hub, "team", None) is not None:
                return hub.team
        return None

    async def _clock_in(call) -> None:
        mgr = _team(call)
        if mgr is not None:
            mgr.clock(call.data["worker"], tc.IN, lat=call.data.get("latitude"),
                      lon=call.data.get("longitude"), accuracy=call.data.get("gps_accuracy"))

    async def _clock_out(call) -> None:
        mgr = _team(call)
        if mgr is not None:
            mgr.clock(call.data["worker"], tc.OUT, lat=call.data.get("latitude"),
                      lon=call.data.get("longitude"), accuracy=call.data.get("gps_accuracy"))

    schema = vol.Schema({vol.Required("worker"): str, vol.Optional("latitude"): vol.Coerce(float),
                         vol.Optional("longitude"): vol.Coerce(float), vol.Optional("gps_accuracy"): vol.Coerce(float)})
    hass.services.async_register(DOMAIN, SERVICE_CLOCK_IN, _clock_in, schema=schema)
    hass.services.async_register(DOMAIN, SERVICE_CLOCK_OUT, _clock_out, schema=schema)


async def async_setup_team(hass: HomeAssistant, entry: ConfigEntry) -> tuple[TeamManager, list]:
    from homeassistant.helpers.storage import Store

    mgr = TeamManager(hass, entry)
    mgr.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.team_{entry.entry_id}")
    saved = await mgr.store.async_load()
    if isinstance(saved, dict):
        mgr.workers = saved.get("workers") or []
        mgr.events = saved.get("events") or []
        if saved.get("radius_m"):
            mgr.radius_m = float(saved["radius_m"])
    mgr.refresh()
    _register_services(hass)
    return mgr, [TeamSensor(hass, entry, mgr)]
