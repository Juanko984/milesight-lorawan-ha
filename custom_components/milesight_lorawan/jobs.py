"""Jobs: the plan → assign → record layer on top of the sensors.

Holds the job list (stored on the gateway), exposes a "jobs" role sensor the Jobs card reads, and takes
edits over the jobs WebSocket (jobs_ws). Sensor-raised jobs come from the rules engine: a rule with a
"create a job" action raises one when it fires, and a job tied to a still-firing *sustained* rule closes
itself when the reading clears (resolved_by "sensor"). Nothing leaves the gateway.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
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
SWEEP_INTERVAL_MIN = 30               # the auto-check cadence: raise jobs for open alerts every half hour
SWEEP_FIRST_DELAY_S = 45              # a first pass soon after startup, once the alerts sensor is ready


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
    def create(self, title: str, *, assignee: Any = None, notify: Any = None, **kw: Any) -> dict[str, Any]:
        job = jc.new_job(title, ts=time.time(), assignee=assignee or None,
                         assignee_notify=notify or None, **kw)
        job["id"] = jc.make_id(self._ids())
        self.jobs.insert(0, job)
        self.refresh()
        if assignee:
            jc.log_event(job, "assigned", time.time(), note=f"Assigned to {assignee}")
            self._push_assignment(job)
            self.refresh()
        return job

    def set_status(self, jid: str, status: str, resolved_by: str | None = None,
                   resolution: str | None = None) -> None:
        j = self._get(jid)
        if j is None:
            raise ValueError("job not found")
        jc.advance(j, status, ts=time.time(), resolved_by=resolved_by, resolution=resolution)
        self.refresh()

    def assign(self, jid: str, who: str | None, notify: str | None = None, by: str | None = None) -> None:
        j = self._get(jid)
        if j is None:
            raise ValueError("job not found")
        changed = (j.get("assignee") or None) != (who or None)
        j["assignee"] = who or None
        j["assignee_notify"] = notify or None
        j["updated_ts"] = time.time()
        if changed and who:
            jc.log_event(j, "assigned", time.time(), by=by, note=f"Assigned to {who}")
            self._push_assignment(j)
        elif changed:
            jc.log_event(j, "unassigned", time.time(), by=by)
        self.refresh()

    # -- push notification on assignment ----------------------------------
    def _push_assignment(self, job: dict[str, Any]) -> None:
        """Send a push to the assignee's mobile app, if we have a notify target for them."""
        target = job.get("assignee_notify")
        if not target:
            return
        service = str(target).split(".", 1)[-1] if "." in str(target) else str(target)
        pri = {"crit": "🔴", "warn": "🟠", "info": "🔵", "ok": "🟢"}.get(job.get("priority"), "")
        title = f"New job: {job.get('title')}"
        body_bits = [job.get("description") or job.get("detail") or job.get("reason") or ""]
        if job.get("area"):
            body_bits.append(f"Area: {job['area']}")
        if job.get("device"):
            body_bits.append(f"Device: {job['device']}")
        message = f"{pri} " + " · ".join(b for b in body_bits if b) if any(body_bits) else f"{pri} You've been assigned a job."
        try:
            self.hass.async_create_task(self.hass.services.async_call(
                "notify", service, {"title": title, "message": message.strip(),
                                    "data": {"tag": f"milesight_job_{job.get('id')}"}}, blocking=False))
        except Exception:  # noqa: BLE001 - a failed push must never break assignment
            _LOGGER.warning("Job assignment push to %s failed", target, exc_info=True)

    def people(self) -> list[dict[str, Any]]:
        """Assignable people: Team workers merged with the alert notify targets, each with a push target."""
        return _assignable_people(self.hass, self.entry)

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

    # -- site-issue sweep (the "Run now" button) --------------------------
    def _open_alerts(self) -> list[dict[str, Any]] | None:
        """The site's open alerts, or None when the alerts sensor is missing / unavailable (unknown state).

        Returning None (not []) when we can't read the alerts is important: it stops sync_alerts from
        closing every swept job on a transient empty read (e.g. during a restart). An empty list means a
        readable sensor that genuinely has no open alerts.
        """
        try:
            states = self.hass.states.async_all()
        except Exception:  # noqa: BLE001 - no state machine (tests)
            return None
        for st in states:
            a = getattr(st, "attributes", {}) or {}
            if a.get("milesight_role") == "alerts_open":
                if str(getattr(st, "state", "")).lower() in ("unavailable", "unknown", "none", ""):
                    return None
                return list(a.get("alerts") or [])
        return None

    def _on_call_assignee(self, al: dict[str, Any]) -> str | None:
        """Who a swept job is auto-assigned to: whoever acknowledged it, else the on-call person paged."""
        by = al.get("acknowledged_by")
        if by:
            return by
        notified = al.get("notified") or []
        return notified[0] if notified else None

    def _job_alert_key(self, j: dict[str, Any]) -> Any:
        sa = j.get("source_alert") or {}
        return sa.get("alert_key") or sa.get("alert_id")

    def sweep(self) -> dict[str, Any]:
        """Create a job for every open site alert that doesn't already have one. Auto-assigns to on-call."""
        alerts = self._open_alerts()
        if alerts is None:
            return {"created": 0, "total": 0, "error": "the alerts sensor isn't ready yet"}
        have = {self._job_alert_key(j) for j in self.jobs if jc.is_open(j) and j.get("source") == "alert"}
        created = 0
        for al in alerts:
            key = jc.alert_key(al)
            if key in have:
                continue
            job = jc.from_alert(al, time.time(), assignee=self._on_call_assignee(al))
            job["id"] = jc.make_id(self._ids())
            self.jobs.insert(0, job)
            have.add(key)
            created += 1
        if created:
            self.refresh()
        return {"created": created, "total": len(alerts)}

    def sync_alerts(self) -> None:
        """Keep open alert-sourced jobs in step with the live alerts, and close them when the fault clears.

        Keyed on the alert's stable key, and a no-op when the alerts can't be read. A job is NOT closed the
        instant its alert drops off the list: a flapping device (a LoRaWAN node that misses a few uplinks)
        briefly disappears from the open-alerts set, and closing on that blip is exactly the bug where an
        offline device's job kept getting marked done and then re-raised. Instead we stamp when the alert
        first went quiet (clear_seen_ts) and only close once it has stayed gone for jc.CLEAR_GRACE_S. While
        the alert is present we refresh the live trigger count and last-seen stamp.
        """
        alerts = self._open_alerts()
        if alerts is None:
            return
        open_by_key = {jc.alert_key(a): a for a in alerts}
        now = time.time()
        changed = False
        for j in self.jobs:
            if not jc.is_open(j) or j.get("source") != "alert":
                continue
            al = open_by_key.get(self._job_alert_key(j))
            if al is not None:                       # still firing — keep it current, cancel any pending close
                if j.get("clear_seen_ts") is not None:
                    j["clear_seen_ts"] = None
                    changed = True
                j["last_seen_ts"] = now
                triggers = jc.alert_triggers(al)
                if triggers != j.get("trigger_count"):
                    j["trigger_count"] = triggers
                    changed = True
                continue
            if j.get("clear_seen_ts") is None:       # first time we've seen it gone — start the grace, don't close
                j["clear_seen_ts"] = now
                changed = True
            elif now - j["clear_seen_ts"] >= jc.CLEAR_GRACE_S:
                jc.advance(j, "done", ts=now, resolved_by="sensor",
                           resolution="Fault cleared — the device reported again and the alert resolved.")
                changed = True
        if changed:
            self.refresh()

    # -- the periodic auto-check (every 30 min; see async_setup_jobs) ------
    def auto_check(self, _now: Any = None) -> dict[str, Any]:
        """Raise jobs for any new open alerts and reconcile existing ones. Runs on a timer and on demand."""
        self.sync_alerts()
        return self.sweep()

    def sync_auto(self, active_keys: set[str]) -> None:
        """Close open RULE-sourced auto-close jobs whose rule/target is no longer firing (the reading cleared).

        Only rule-sourced jobs are matched on a rule key. Alert-sourced jobs (source == "alert") are owned by
        sync_alerts, which keys them on the alert and gives them a clearance grace — they must NOT be closed
        here, or every offline/alert job would be marked "cleared by sensor" within a minute (their rule key is
        'None::None', never in active_keys). This was why open alerts like an offline device showed no job.
        """
        changed = False
        for j in self.jobs:
            if not jc.is_open(j) or j.get("source") != "rule" or not j.get("auto_close"):
                continue
            sr = j.get("source_rule") or {}
            if jc.rule_job_key(sr.get("rule_id"), sr.get("target_key")) not in active_keys:
                jc.advance(j, "done", ts=time.time(), resolved_by="sensor")
                changed = True
        if changed:
            self.refresh()


def _notify_name(target: str) -> str:
    """'notify.mobile_app_juan' -> 'juan'; keep a non-mobile target's trailing name as-is."""
    n = str(target).split(".", 1)[-1]
    return n[len("mobile_app_"):] if n.startswith("mobile_app_") else n


def _assignable_people(hass: HomeAssistant, entry: ConfigEntry) -> list[dict[str, Any]]:
    """People a job can be assigned to: Team workers merged with the alert notify targets.

    Each entry is {name, notify, source}. `notify` is a push target (notify.* service) when we have one —
    from the alert config directly, or matched to a worker by first name — else None (assignable, no push).
    """
    rt = getattr(entry, "runtime_data", None)
    out: dict[str, dict[str, Any]] = {}

    # 1) notify targets configured for alerts (these have real push)
    targets: set[str] = set()
    cfg = getattr(getattr(rt, "alerts", None), "cfg", None)
    if cfg is not None:
        targets |= set(getattr(cfg, "primary", []) or [])
        for sh in (getattr(cfg, "rota", []) or []):
            targets |= set(getattr(sh, "targets", []) or [])
        targets |= set(getattr(cfg, "backup", []) or [])
    targets = {t for t in targets if "." in str(t)}
    for t in sorted(targets):
        nm = _notify_name(t)
        out[nm.lower()] = {"name": nm.replace("_", " ").title(), "notify": t, "source": "notify"}

    def _match(name: str) -> str | None:
        first = name.split()[0].lower() if name.split() else name.lower()
        for t in targets:
            tn = _notify_name(t).lower()
            if tn == first or tn == name.lower().replace(" ", "_"):
                return t
        return None

    # 2) Team workers (prefer their full name; link a push target by first-name match when possible)
    team = getattr(rt, "team", None)
    for w in (getattr(team, "workers", []) or []):
        wname = str(w.get("name") or "").strip()
        if not wname:
            continue
        notify = _match(wname)
        key = (notify and _notify_name(notify).lower()) or wname.lower()
        if key in out:
            out[key]["name"] = wname
            out[key]["source"] = "worker"
            out[key]["notify"] = out[key].get("notify") or notify
        else:
            out[wname.lower()] = {"name": wname, "notify": notify, "source": "worker"}
    return sorted(out.values(), key=lambda p: p["name"].lower())


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
    from homeassistant.helpers.event import async_call_later, async_track_time_interval

    mgr = JobsManager(hass, entry)
    mgr.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.jobs_{entry.entry_id}")
    saved = await mgr.store.async_load()
    if isinstance(saved, dict) and isinstance(saved.get("jobs"), list):
        mgr.jobs = [jc.migrate(j) for j in saved["jobs"]]
    mgr.refresh()

    @callback
    def _auto(now: Any = None) -> None:
        # sweep open alerts into jobs and reconcile the existing ones, so jobs appear without "Run now"
        try:
            mgr.auto_check()
        except Exception:  # noqa: BLE001 - a bad tick must never take the integration down
            _LOGGER.warning("Jobs auto-check failed", exc_info=True)

    entry.async_on_unload(async_track_time_interval(hass, _auto, timedelta(minutes=SWEEP_INTERVAL_MIN)))
    entry.async_on_unload(async_call_later(hass, SWEEP_FIRST_DELAY_S, _auto))
    return mgr, [JobsSensor(hass, entry, mgr)]
