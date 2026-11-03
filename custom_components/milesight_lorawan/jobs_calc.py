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


def make_id(existing: Iterable[str], prefix: str = "job") -> str:
    have = set(existing or [])
    i = 1
    while f"{prefix}_{i}" in have:
        i += 1
    return f"{prefix}_{i}"


def new_job(title: str, *, detail: str = "", priority: str = "info", area: Any = None,
            assignee: Any = None, checklist: Iterable[str] | None = None, source: str = "manual",
            source_rule: dict | None = None, source_alert: dict | None = None, auto_close: bool = False,
            due: Any = None, ts: float = 0.0, jid: str = "") -> dict[str, Any]:
    return {"id": jid, "title": str(title), "detail": str(detail or ""),
            "status": "todo", "priority": priority if priority in PRIORITIES else "info",
            "area": area, "assignee": assignee or None,
            "checklist": [{"text": str(c), "done": False} for c in (checklist or [])],
            "source": source, "source_rule": source_rule, "source_alert": source_alert,
            "auto_close": bool(auto_close), "due": due, "created_ts": ts, "done_ts": None, "resolved_by": None}


def rule_job_key(rule_id: Any, target_key: Any) -> str:
    """Stable key for 'one open job per (rule, target)' de-duping and auto-close matching."""
    return f"{rule_id}::{target_key}"


def severity_priority(sev: Any) -> str:
    return {"critical": "crit", "warning": "warn", "info": "info"}.get(str(sev), "info")


def alert_key(alert: dict[str, Any]) -> Any:
    """The stable identity of an alert (its key — e.g. 'deveui:offline'), falling back to its id."""
    return alert.get("key") or alert.get("id")


def from_alert(alert: dict[str, Any], ts: float, *, assignee: Any = None) -> dict[str, Any]:
    """Build a job from an open site alert (used by the Jobs 'Run now' sweep). Closes when the alert clears."""
    return new_job(alert.get("title") or "Site issue", detail=alert.get("message") or "",
                   priority=severity_priority(alert.get("severity")), assignee=assignee,
                   source="alert", auto_close=True, ts=ts,
                   source_alert={"alert_id": alert.get("id"), "alert_key": alert_key(alert),
                                 "severity": alert.get("severity"), "category": alert.get("category")})


def from_rule_fire(fire: dict[str, Any], *, priority: str, auto_close: bool, ts: float) -> dict[str, Any]:
    """Build a work-order job from a rules-engine fire dict.

    The catalog title reads like a sentence ("Fridge over limit → notify"); the job keeps the condition
    half and drops the action half, so it reads as a task: "Fridge over limit · Fridge 1".
    """
    target = fire.get("target_name") or "site"
    base = str(fire.get("title") or "Check").split("→")[0].strip() or "Check"
    tkey = fire.get("target_key") or target
    return new_job(f"{base} · {target}", detail=fire.get("message") or "", priority=priority,
                   area=fire.get("area"), source="rule", auto_close=auto_close, ts=ts,
                   source_rule={"rule_id": fire.get("recipe_id"), "target_key": tkey,
                                "icon": fire.get("icon"), "catalog": fire.get("catalog")})


def advance(job: dict[str, Any], status: str, *, ts: float = 0.0, resolved_by: str | None = None) -> dict[str, Any]:
    status = status if status in STATUSES else job.get("status", "todo")
    job["status"] = status
    if status == "done":
        job["done_ts"] = ts
        job["resolved_by"] = resolved_by or "person"
    else:
        job["done_ts"] = None
        job["resolved_by"] = None
    return job


def is_open(job: dict[str, Any]) -> bool:
    return job.get("status") != "done"


def is_overdue(job: dict[str, Any], now: float) -> bool:
    due = job.get("due")
    return bool(due) and is_open(job) and isinstance(due, (int, float)) and now > due


def summarize(jobs: list[dict[str, Any]], now: float = 0.0) -> dict[str, Any]:
    counts = {"todo": 0, "doing": 0, "done": 0}
    overdue = from_sensor_open = 0
    for j in jobs:
        s = j.get("status", "todo")
        counts[s] = counts.get(s, 0) + 1
        if is_open(j) and j.get("source") in ("rule", "alert"):
            from_sensor_open += 1
        if is_overdue(j, now):
            overdue += 1
    return {"open": counts["todo"] + counts["doing"], "todo": counts["todo"], "doing": counts["doing"],
            "done": counts["done"], "overdue": overdue, "from_sensor_open": from_sensor_open,
            "total": len(jobs)}
