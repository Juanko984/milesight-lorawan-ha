"""Team & clock-in: workers, geofenced clock-in, and timesheets. Pure Python (no Home Assistant imports).

A worker and a clock event are plain dicts so they store as JSON on the gateway. The HA layer (team.py)
owns the lists, the "team" role sensor, the clock_in / clock_out services (which read the worker's phone
GPS from the Home Assistant mobile app) and the WebSocket. Clocking in outside the site's radius is
*blocked* and recorded, never counted as on-site. Same pure/wrapper split as jobs_calc / recipes_calc.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

# clock event kinds and the status a clock-in resolves to
IN, OUT = "in", "out"
ON_SITE, OFF_SITE_BLOCKED, CLOCKED_OUT = "on_site", "off_site_blocked", "clocked_out"
DEFAULT_RADIUS_M = 300.0


def haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def make_id(existing: Iterable[str], prefix: str = "w") -> str:
    have = set(existing or [])
    i = 1
    while f"{prefix}_{i}" in have:
        i += 1
    return f"{prefix}_{i}"


def initials(name: str) -> str:
    parts = [p for p in str(name).split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


PAY_TYPES = ("none", "hourly", "salary")


def new_worker(name: str, *, role: str = "", tracker: str | None = None, method: str = "app",
               active: bool = True, pay_type: str = "none", rate: Any = None, salary: Any = None,
               days_per_week: int = 5, wid: str = "") -> dict[str, Any]:
    return {"id": wid, "name": str(name), "initials": initials(name), "role": str(role or ""),
            "tracker": tracker or None, "method": method, "active": bool(active),
            "pay_type": pay_type if pay_type in PAY_TYPES else "none",
            "rate": _num(rate), "salary": _num(salary),
            "days_per_week": int(days_per_week) if days_per_week else 5}


def work_weekdays(n: Any) -> set[int]:
    """Which weekday indices (0 = Mon) count as expected working days for N days/week."""
    n = int(n or 5)
    if n >= 7:
        return {0, 1, 2, 3, 4, 5, 6}
    if n == 6:
        return {0, 1, 2, 3, 4, 5}       # Mon–Sat
    return set(range(max(1, min(5, n))))  # the first N of Mon–Fri (5 → Mon–Fri, 4 → Mon–Thu …)


def validate_clock_in(site_lat: Any, site_lon: Any, lat: Any, lon: Any,
                      radius_m: float = DEFAULT_RADIUS_M) -> tuple[bool, float | None, str]:
    """Decide whether a clock-in is on-site. Returns (allowed, distance_m_or_None, status).

    With no site centre or no worker coordinates we cannot measure distance, so the clock-in is allowed
    (status on_site) and the distance is None. When coordinates are present and the worker is beyond the
    radius, the clock-in is blocked.
    """
    s_lat, s_lon, w_lat, w_lon = _num(site_lat), _num(site_lon), _num(lat), _num(lon)
    if None in (s_lat, s_lon, w_lat, w_lon):
        return True, None, ON_SITE
    dist = haversine_m(s_lat, s_lon, w_lat, w_lon)
    if dist <= float(radius_m):
        return True, dist, ON_SITE
    return False, dist, OFF_SITE_BLOCKED


def clock_event(worker_id: str, kind: str, ts: float, *, status: str, lat: Any = None, lon: Any = None,
                distance_m: float | None = None, accuracy: Any = None) -> dict[str, Any]:
    return {"worker": worker_id, "kind": kind, "ts": ts, "status": status,
            "lat": _num(lat), "lon": _num(lon), "distance_m": distance_m, "accuracy": _num(accuracy)}


def _overlap(a: float, b: float, lo: float, hi: float) -> float:
    return max(0.0, min(b, hi) - max(a, lo))


def timesheet(events: list[dict[str, Any]], worker_id: str, now: float,
              day_start: float, week_start: float) -> dict[str, Any]:
    """Pair in→out events for one worker into worked seconds today / this week, and whether on site now.

    Only successful on-site clock-ins (status on_site) open an interval; blocked clock-ins are ignored.
    """
    evs = sorted((e for e in events if e.get("worker") == worker_id), key=lambda e: e.get("ts") or 0)
    today_s = week_s = 0.0
    open_in: float | None = None
    for e in evs:
        ts = _num(e.get("ts"))
        if ts is None:
            continue
        if e.get("kind") == IN and e.get("status") == ON_SITE:
            open_in = ts
        elif e.get("kind") == OUT and open_in is not None:
            today_s += _overlap(open_in, ts, day_start, now)
            week_s += _overlap(open_in, ts, week_start, now)
            open_in = None
    on_site = open_in is not None
    if on_site:
        today_s += _overlap(open_in, now, day_start, now)
        week_s += _overlap(open_in, now, week_start, now)
    return {"today_s": today_s, "week_s": week_s, "on_site": on_site, "since": open_in}


def worker_month(events: list[dict[str, Any]], worker_id: str, lo: float, hi: float, now: float,
                 day_of: Any) -> dict[str, Any]:
    """On-site hours worked and the set of distinct days worked for one worker within [lo, hi]."""
    end = min(hi, now)
    evs = sorted((e for e in events if e.get("worker") == worker_id), key=lambda e: e.get("ts") or 0)
    hours_s = 0.0
    worked: set = set()
    open_in: float | None = None
    for e in evs:
        ts = _num(e.get("ts"))
        if ts is None:
            continue
        if e.get("kind") == IN and e.get("status") == ON_SITE:
            open_in = ts
            if lo <= ts < hi:
                worked.add(day_of(ts))
        elif e.get("kind") == OUT and open_in is not None:
            hours_s += _overlap(open_in, ts, lo, end)
            open_in = None
    if open_in is not None:
        hours_s += _overlap(open_in, now, lo, end)
    return {"hours": round(hours_s / 3600.0, 2), "worked_days": worked}


def gross_pay(worker: dict[str, Any], hours: float) -> float:
    """Gross for the period. Hourly → hours × rate. Salary → the fixed monthly salary (attendance shown, not docked)."""
    pt = worker.get("pay_type")
    if pt == "hourly":
        return round(hours * (_num(worker.get("rate")) or 0.0), 2)
    if pt == "salary":
        return round(_num(worker.get("salary")) or 0.0, 2)
    return 0.0


def payroll(workers: list[dict[str, Any]], events: list[dict[str, Any]], lo: float, hi: float, now: float,
            day_of: Any, cal_days: list) -> dict[str, Any]:
    """Monthly payroll rows + total. cal_days is [(date_str, weekday_int)] for the elapsed month."""
    rows = []
    total = 0.0
    for w in workers:
        m = worker_month(events, w["id"], lo, hi, now, day_of)
        wdays = work_weekdays(w.get("days_per_week", 5))
        expected = [d for d, wd in cal_days if wd in wdays]
        absent = sum(1 for d in expected if d not in m["worked_days"])
        gross = gross_pay(w, m["hours"])
        total += gross
        rows.append({"id": w["id"], "name": w.get("name"), "initials": w.get("initials"),
                     "role": w.get("role"), "pay_type": w.get("pay_type") or "none",
                     "rate": _num(w.get("rate")), "salary": _num(w.get("salary")),
                     "days_per_week": int(w.get("days_per_week") or 5),
                     "hours": m["hours"], "days_worked": len(m["worked_days"]),
                     "expected_days": len(expected), "days_absent": absent, "gross": round(gross, 2)})
    return {"rows": rows, "total": round(total, 2)}


def summarize(workers: list[dict[str, Any]], events: list[dict[str, Any]], now: float,
              day_start: float, week_start: float, recent: int = 8) -> dict[str, Any]:
    names = {w["id"]: w.get("name", w["id"]) for w in workers}
    rows = []
    on_now = 0
    for w in workers:
        ts = timesheet(events, w["id"], now, day_start, week_start)
        on_now += 1 if ts["on_site"] else 0
        rows.append({**w, "on_site": ts["on_site"], "since": ts["since"],
                     "today_h": round(ts["today_s"] / 3600.0, 1), "week_h": round(ts["week_s"] / 3600.0, 1)})
    ev = sorted(events, key=lambda e: e.get("ts") or 0, reverse=True)[:recent]
    ev = [{**e, "worker_name": names.get(e.get("worker"), e.get("worker"))} for e in ev]
    blocked_today = sum(1 for e in events if e.get("status") == OFF_SITE_BLOCKED and (_num(e.get("ts")) or 0) >= day_start)
    return {"workers": rows, "events": ev, "on_site": on_now, "total": len(workers),
            "blocked_today": blocked_today}
