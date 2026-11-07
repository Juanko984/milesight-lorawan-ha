"""Jobs: the plan → assign → record loop. Pure job-model helpers (no Home Assistant imports).

A job is a plain dict so it stores as JSON on the gateway. The HA layer (jobs.py) owns the list, the
"jobs" role sensor and the WebSocket; sensor-raised jobs come from the rules engine and — when they are
tied to a *sustained* rule — close themselves when the reading clears. Same pure/wrapper split as
costs_calc / recipes_calc.
"""
from __future__ import annotations

from typing import Any, Iterable

STATUSES = ("todo", "doing", "done")
PRIORITIES = ("crit", "warn", "info", "ok")

# which rule category a raised job inherits its priority from
CAT_PRIORITY = {"cold_chain": "crit", "pumps": "crit", "security": "crit",
                "water": "warn", "energy": "warn", "devices": "info", "farm": "info"}
# rule condition types that resolve themselves (so a job raised from one can auto-close when it clears)
SUSTAINED = ("threshold", "boolean", "offline", "geofence")

# how long an alert must stay gone before its swept job auto-closes. A flapping device (e.g. a LoRaWAN
# node that misses a few uplinks then checks in) drops out of the open-alerts list for a moment; without
# this grace, sync_alerts would close the job on that blip and a later sweep would raise a duplicate. The
# alert has to be continuously absent for this long before we accept the fault as cleared.
CLEAR_GRACE_S = 1200.0   # 20 minutes


def make_id(existing: Iterable[str], prefix: str = "job") -> str:
    have = set(existing or [])
    i = 1
    while f"{prefix}_{i}" in have:
        i += 1
    return f"{prefix}_{i}"


def new_job(title: str, *, detail: str = "", description: str = "", priority: str = "info", area: Any = None,
            device: Any = None, assignee: Any = None, assignee_notify: Any = None,
            checklist: Iterable[str] | None = None, source: str = "manual",
            source_rule: dict | None = None, source_alert: dict | None = None, auto_close: bool = False,
            due: Any = None, ts: float = 0.0, jid: str = "", reason: str = "",
            trigger_count: int = 1, last_seen_ts: Any = None) -> dict[str, Any]:
    job = {"id": jid, "title": str(title), "detail": str(detail or ""), "description": str(description or ""),
           "status": "todo", "priority": priority if priority in PRIORITIES else "info",
           "area": area, "device": device or None, "assignee": assignee or None,
           "assignee_notify": assignee_notify or None,
           "checklist": [{"text": str(c), "done": False} for c in (checklist or [])],
           "source": source, "source_rule": source_rule, "source_alert": source_alert,
           "auto_close": bool(auto_close), "due": due, "created_ts": ts, "updated_ts": ts, "done_ts": None,
           "resolved_by": None, "resolution": "",
           # why it was raised (shown on auto-created cards), how many times the fault has fired, and the
           # clearance tracking the sensor sync uses so a flapping device doesn't close the job prematurely.
           "reason": str(reason or ""), "trigger_count": int(trigger_count or 1),
           "last_seen_ts": last_seen_ts if last_seen_ts is not None else (ts or None),
           "clear_seen_ts": None, "history": []}
    how = "Raised from an alert" if source == "alert" else "Raised by a rule" if source == "rule" else "Created"
    log_event(job, "created", ts, note=how + ((" — " + str(reason)) if reason else ""))
    return job


def log_event(job: dict[str, Any], kind: str, ts: float, *, by: Any = None, note: Any = None) -> dict[str, Any]:
    """Append one entry to a job's activity timeline (created / started / done / reopened / assigned / note)."""
    job.setdefault("history", [])
    entry = {"kind": kind, "ts": ts, "by": (str(by).strip() or None) if by else None,
             "note": (str(note).strip() or None) if note else None}
    job["history"].append(entry)
    return entry


def migrate(job: dict[str, Any]) -> dict[str, Any]:
    """Backfill fields added in later versions onto a job loaded from storage, so old jobs render fully."""
    if not isinstance(job, dict):
        return job
    job.setdefault("resolution", "")
    job.setdefault("reason", job.get("detail") or "")
    job.setdefault("description", "")
    job.setdefault("device", None)
    job.setdefault("assignee_notify", None)
    job.setdefault("updated_ts", job.get("done_ts") or job.get("created_ts") or None)
    job.setdefault("trigger_count", 1)
    job.setdefault("last_seen_ts", job.get("created_ts") or None)
    job.setdefault("clear_seen_ts", None)
    if "history" not in job:   # synthesize a minimal timeline for jobs stored before history existed
        hist = [{"kind": "created", "ts": job.get("created_ts"), "by": None, "note": None}]
        if job.get("done_ts"):
            hist.append({"kind": "done", "ts": job.get("done_ts"), "by": job.get("resolved_by"),
                         "note": job.get("resolution") or None})
        job["history"] = hist
    return job


def rule_job_key(rule_id: Any, target_key: Any) -> str:
    """Stable key for 'one open job per (rule, target)' de-duping and auto-close matching."""
    return f"{rule_id}::{target_key}"


def severity_priority(sev: Any) -> str:
    return {"critical": "crit", "warning": "warn", "info": "info"}.get(str(sev), "info")


def alert_key(alert: dict[str, Any]) -> Any:
    """The stable identity of an alert (its key — e.g. 'deveui:offline'), falling back to its id."""
    return alert.get("key") or alert.get("id")


def alert_triggers(alert: dict[str, Any]) -> int:
    """How many times this fault has fired: first raise + each flap (resolve → re-raise) the engine counted."""
    try:
        return int(alert.get("flaps") or 0) + 1
    except (TypeError, ValueError):
        return 1


def from_alert(alert: dict[str, Any], ts: float, *, assignee: Any = None) -> dict[str, Any]:
    """Build a job from an open site alert (used by the Jobs 'Run now' sweep). Closes when the alert clears."""
    msg = alert.get("message") or ""
    return new_job(alert.get("title") or "Site issue", detail=msg,
                   priority=severity_priority(alert.get("severity")), assignee=assignee,
                   device=alert.get("device") or _device_from_title(alert.get("title")),
                   source="alert", auto_close=True, ts=ts, last_seen_ts=ts,
                   reason=msg or (alert.get("title") or ""), trigger_count=alert_triggers(alert),
                   source_alert={"alert_id": alert.get("id"), "alert_key": alert_key(alert),
                                 "severity": alert.get("severity"), "category": alert.get("category"),
                                 "since": alert.get("since")})


def _device_from_title(title: Any) -> Any:
    """Best-effort device name from an alert title like 'Offline – WS301' → 'WS301'."""
    if not title:
        return None
    for sep in (" – ", " - ", " — "):
        if sep in str(title):
            return str(title).split(sep, 1)[1].strip() or None
    return None


def from_rule_fire(fire: dict[str, Any], *, priority: str, auto_close: bool, ts: float) -> dict[str, Any]:
    """Build a work-order job from a rules-engine fire dict.

    The catalog title reads like a sentence ("Fridge over limit → notify"); the job keeps the condition
    half and drops the action half, so it reads as a task: "Fridge over limit · Fridge 1".
    """
    target = fire.get("target_name") or "site"
    base = str(fire.get("title") or "Check").split("→")[0].strip() or "Check"
    tkey = fire.get("target_key") or target
    msg = fire.get("message") or ""
    return new_job(f"{base} · {target}", detail=msg, priority=priority,
                   area=fire.get("area"), device=fire.get("target_name"), source="rule",
                   auto_close=auto_close, ts=ts, reason=msg or base,
                   source_rule={"rule_id": fire.get("recipe_id"), "target_key": tkey,
                                "icon": fire.get("icon"), "catalog": fire.get("catalog")})


def advance(job: dict[str, Any], status: str, *, ts: float = 0.0, resolved_by: str | None = None,
            resolution: str | None = None) -> dict[str, Any]:
    prev = job.get("status", "todo")
    status = status if status in STATUSES else prev
    job["status"] = status
    job["updated_ts"] = ts
    if status == "done":
        job["done_ts"] = ts
        job["resolved_by"] = resolved_by or "person"
        if resolution is not None:
            job["resolution"] = str(resolution)
        log_event(job, "done", ts, by=resolved_by, note=resolution or None)
    else:
        job["done_ts"] = None
        job["resolved_by"] = None
        job["resolution"] = ""          # reopening clears the old write-up
        job["clear_seen_ts"] = None     # and the clearance tracking, so it can auto-close cleanly again
        if prev != status:
            log_event(job, "started" if status == "doing" else "reopened", ts, by=resolved_by)
    return job


def is_open(job: dict[str, Any]) -> bool:
    return job.get("status") != "done"


def clearing_remaining(job: dict[str, Any], now: float, grace: float = CLEAR_GRACE_S) -> float | None:
    """Seconds left before a self-closing alert-job auto-closes, once its alert has gone quiet.

    None while the alert is still present (clear_seen_ts unset) or the job isn't self-closing. 0 means the
    grace is up and the next sync will close it.
    """
    if not is_open(job) or not job.get("auto_close"):
        return None
    seen = job.get("clear_seen_ts")
    if not isinstance(seen, (int, float)):
        return None
    return max(0.0, grace - (now - seen))


def is_overdue(job: dict[str, Any], now: float) -> bool:
    due = job.get("due")
    return bool(due) and is_open(job) and isinstance(due, (int, float)) and now > due


def summarize(jobs: list[dict[str, Any]], now: float = 0.0) -> dict[str, Any]:
    counts = {"todo": 0, "doing": 0, "done": 0}
    overdue = from_sensor_open = clearing = unassigned = 0
    for j in jobs:
        s = j.get("status", "todo")
        counts[s] = counts.get(s, 0) + 1
        if is_open(j) and j.get("source") in ("rule", "alert"):
            from_sensor_open += 1
        if is_open(j) and not j.get("assignee"):
            unassigned += 1
        if clearing_remaining(j, now) is not None:
            clearing += 1
        if is_overdue(j, now):
            overdue += 1
    return {"open": counts["todo"] + counts["doing"], "todo": counts["todo"], "doing": counts["doing"],
            "done": counts["done"], "overdue": overdue, "from_sensor_open": from_sensor_open,
            "clearing": clearing, "unassigned": unassigned, "total": len(jobs)}
