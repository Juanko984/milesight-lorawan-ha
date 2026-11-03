"""Jobs: the plan → assign → record layer on top of the sensors.

Holds the job list (stored on the gateway), exposes a "jobs" role sensor the Jobs card reads, and takes
edits over the jobs WebSocket (jobs_ws). Sensor-raised jobs come from the rules engine: a rule with a
"create a job" action raises one when it fires, and a job tied to a still-firing *sustained* rule closes
itself when the reading clears (resolved_by "sensor"). Nothing leaves the gateway.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send

from . import jobs_calc as jc
from .building import hub_device
from .const import DOMAIN, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)
SIGNAL_JOBS = f"{DOMAIN}_jobs_{{}}"   # .format(hub entry_id)


class JobsManager:
    """Holds the job list, the sensor snapshot, and the mutations the WebSocket and rules engine call."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.store = None
        self.jobs: list[dict[str, Any]] = []
        self.data: dict[str, Any] = {}

    def refresh(self) -> None:
        self.data = {"jobs": self.jobs, **jc.summarize(self.jobs, time.time())}
        if self.store is not None:
            self.store.async_delay_save(self._to_store, 20)
        async_dispatcher_send(self.hass, SIGNAL_JOBS.format(self.entry.entry_id))

    def _to_store(self) -> dict[str, Any]:
        return {"jobs": self.jobs}

    def _ids(self) -> list[str]:
        return [j["id"] for j in self.jobs]

    def _get(self, jid: str) -> dict[str, Any] | None:
        return next((j for j in self.jobs if j["id"] == jid), None)

    # -- mutations (WebSocket) ---------------------------------------------
    def create(self, title: str, **kw: Any) -> dict[str, Any]:
        job = jc.new_job(title, ts=time.time(), **kw)
        job["id"] = jc.make_id(self._ids())
        self.jobs.insert(0, job)
        self.refresh()
        return job

    def set_status(self, jid: str, status: str, resolved_by: str | None = None) -> None:
        j = self._get(jid)
        if j is None:
            raise ValueError("job not found")
        jc.advance(j, status, ts=time.time(), resolved_by=resolved_by)
        self.refresh()

    def assign(self, jid: str, who: str | None) -> None:
        j = self._get(jid)
        if j is None:
            raise ValueError("job not found")
        j["assignee"] = who or None
        self.refresh()

    def toggle_check(self, jid: str, index: int, done: bool) -> None:
        j = self._get(jid)
        if j is None:
            raise ValueError("job not found")
        cl = j.get("checklist") or []
        if 0 <= index < len(cl):
            cl[index]["done"] = bool(done)
        self.refresh()

    def delete(self, jid: str) -> None:
        self.jobs = [j for j in self.jobs if j["id"] != jid]
        self.refresh()

    # -- the sensor → job loop (called by the rules engine) ----------------
    def raise_from_rule(self, fire: dict[str, Any], *, priority: str, auto_close: bool) -> dict[str, Any] | None:
        """Raise a job from a firing rule — but only one open job per (rule, target)."""
        key = jc.rule_job_key(fire.get("recipe_id"), fire.get("target_key") or fire.get("target_name"))
        for j in self.jobs:
            sr = j.get("source_rule") or {}
            if jc.is_open(j) and jc.rule_job_key(sr.get("rule_id"), sr.get("target_key")) == key:
                return None
        job = jc.from_rule_fire(fire, priority=priority, auto_close=auto_close, ts=time.time())
        job["id"] = jc.make_id(self._ids())
        self.jobs.insert(0, job)
        self.refresh()
        return job

    def sync_auto(self, active_keys: set[str]) -> None:
        """Close every open auto-close job whose rule/target is no longer firing (the reading cleared)."""
        changed = False
        for j in self.jobs:
            if not jc.is_open(j) or not j.get("auto_close"):
                continue
            sr = j.get("source_rule") or {}
            if jc.rule_job_key(sr.get("rule_id"), sr.get("target_key")) not in active_keys:
                jc.advance(j, "done", ts=time.time(), resolved_by="sensor")
                changed = True
        if changed:
            self.refresh()


class JobsSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Jobs"
    _attr_icon = "mdi:clipboard-check-outline"
    _attr_native_unit_of_measurement = "open"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mgr: JobsManager) -> None:
        self.hass, self.entry, self.mgr = hass, entry, mgr
        self._attr_device_info = hub_device(entry)
        self._attr_unique_id = f"{entry.entry_id}_jobs"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_JOBS.format(self.entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self):
        return self.mgr.data.get("open") if self.mgr.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"milesight_role": "jobs", "site": self.entry.title, "hub": self.entry.entry_id,
                **(self.mgr.data or {})}


async def async_setup_jobs(hass: HomeAssistant, entry: ConfigEntry) -> tuple[JobsManager, list]:
    from homeassistant.helpers.storage import Store

    mgr = JobsManager(hass, entry)
    mgr.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.jobs_{entry.entry_id}")
    saved = await mgr.store.async_load()
    if isinstance(saved, dict) and isinstance(saved.get("jobs"), list):
        mgr.jobs = saved["jobs"]
    mgr.refresh()
    return mgr, [JobsSensor(hass, entry, mgr)]
