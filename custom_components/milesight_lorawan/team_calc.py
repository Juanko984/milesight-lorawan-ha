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

# time & attendance tunables
SHIFT_GRACE_MIN = 5        # minutes of grace before a clock-in counts as "late" / a clock-out as "early"
OT_MULT_DEFAULT = 1.5      # overtime paid at 1.5× the hourly rate
LEAVE_KINDS = ("leave", "sick", "off", "public")   # annual leave, sick leave, unpaid day off, public holiday


def minutes_of(hhmm: Any) -> int | None:
    """Parse 'HH:MM' into minutes since local midnight. None for blank / malformed values."""
    if not hhmm:
        return None
    try:
        h, m = str(hhmm).strip().split(":")
        mins = int(h) * 60 + int(m)
        return mins if 0 <= mins < 24 * 60 else None
    except (ValueError, AttributeError):
        return None


def is_self(by: Any, worker_name: Any) -> bool:
    """Did the worker clock themselves? True when no actor is recorded, or the actor is the worker."""
    if not by:
        return True
    return str(by).strip().lower() == str(worker_name or "").strip().lower()


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
               days_per_week: int = 5, shift_start: Any = None, shift_end: Any = None,
               ot_weekly_h: Any = None, wid: str = "") -> dict[str, Any]:
    return {"id": wid, "name": str(name), "initials": initials(name), "role": str(role or ""),
            "tracker": tracker or None, "method": method, "active": bool(active),
            "pay_type": pay_type if pay_type in PAY_TYPES else "none",
            "rate": _num(rate), "salary": _num(salary),
            "days_per_week": int(days_per_week) if days_per_week else 5,
            # scheduled shift (local 'HH:MM') for late/early flags, and a weekly overtime threshold in hours
            "shift_start": _hhmm(shift_start), "shift_end": _hhmm(shift_end), "ot_weekly_h": _num(ot_weekly_h)}


def _hhmm(v: Any) -> str | None:
    """Normalise a shift time to 'HH:MM', or None if blank / invalid."""
    mins = minutes_of(v)
    return None if mins is None else f"{mins // 60:02d}:{mins % 60:02d}"


def migrate_worker(w: dict[str, Any]) -> dict[str, Any]:
    """Backfill fields added in later versions onto a worker loaded from storage."""
    if isinstance(w, dict):
        w.setdefault("shift_start", None)
        w.setdefault("shift_end", None)
        w.setdefault("ot_weekly_h", None)
    return w


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
                distance_m: float | None = None, accuracy: Any = None, worker_name: Any = None,
                by: Any = None, late_min: Any = None, early_min: Any = None, note: Any = None) -> dict[str, Any]:
    """One clock event. `by` is who performed it (for clock-on-behalf accountability); `self` records
    whether that was the worker. late_min / early_min carry the shift deviation when a shift is set."""
    return {"worker": worker_id, "kind": kind, "ts": ts, "status": status,
            "lat": _num(lat), "lon": _num(lon), "distance_m": distance_m, "accuracy": _num(accuracy),
            "by": (str(by).strip() or None) if by else None, "self": is_self(by, worker_name),
            "late_min": None if late_min is None else int(late_min),
            "early_min": None if early_min is None else int(early_min),
            "note": (str(note).strip() or None) if note else None}


def shift_deviation(worker: dict[str, Any], kind: str, local_minutes: Any,
                    grace: int = SHIFT_GRACE_MIN) -> int | None:
    """Minutes a clock-in is late (kind 'in' vs shift_start) or a clock-out is early (kind 'out' vs shift_end).

    0 means on time; a positive number is the overage past the grace; None when no shift is set or the
    local time is unknown. Keeps the pure layer tz-free — the HA wrapper passes local minutes-since-midnight.
    """
    lm = _num(local_minutes)
    if lm is None:
        return None
    if kind == IN:
        start = minutes_of(worker.get("shift_start"))
        return None if start is None else max(0, int(lm) - start - int(grace))
    end = minutes_of(worker.get("shift_end"))
    return None if end is None else max(0, end - int(lm) - int(grace))


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
    """On-site hours worked, the distinct days worked, and hours-per-day for one worker within [lo, hi].

    Each worked interval's hours are attributed to the day it was clocked in on (by_day) — enough for
    weekly overtime bucketing without splitting shifts across midnight.
    """
    end = min(hi, now)
    evs = sorted((e for e in events if e.get("worker") == worker_id), key=lambda e: e.get("ts") or 0)
    hours_s = 0.0
    worked: set = set()
    by_day: dict[str, float] = {}
    open_in: float | None = None

    def _bank(start: float, stop: float) -> None:
        nonlocal hours_s
        sec = _overlap(start, stop, lo, end)
        if sec > 0:
            hours_s += sec
            by_day[day_of(start)] = by_day.get(day_of(start), 0.0) + sec

    for e in evs:
        ts = _num(e.get("ts"))
        if ts is None:
            continue
        if e.get("kind") == IN and e.get("status") == ON_SITE:
            open_in = ts
            if lo <= ts < hi:
                worked.add(day_of(ts))
        elif e.get("kind") == OUT and open_in is not None:
            _bank(open_in, ts)
            open_in = None
    if open_in is not None:
        _bank(open_in, now)
    return {"hours": round(hours_s / 3600.0, 2), "worked_days": worked,
            "by_day": {d: round(s / 3600.0, 2) for d, s in by_day.items()}}


def _iso_week(date_str: str) -> str:
    """ISO year-week key ('2026-W45') for a 'YYYY-MM-DD' date, for grouping overtime by week."""
    import datetime as _dt
    try:
        y, m, d = (int(x) for x in str(date_str).split("-")[:3])
        iso = _dt.date(y, m, d).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except (ValueError, TypeError):
        return str(date_str)


def overtime_hours(by_day: dict[str, float], weekly_h: Any) -> float:
    """Hours over the weekly threshold, summed across the ISO weeks the days fall in. 0 if no threshold."""
    thr = _num(weekly_h)
    if thr is None or thr <= 0:
        return 0.0
    weeks: dict[str, float] = {}
    for d, h in (by_day or {}).items():
        weeks[_iso_week(d)] = weeks.get(_iso_week(d), 0.0) + (h or 0.0)
    return round(sum(max(0.0, wh - thr) for wh in weeks.values()), 2)


def leave_days(leave: list[dict[str, Any]] | None, worker_id: str,
               in_month: Any) -> dict[str, int]:
    """Count leave entries for a worker within the month, by kind and total. `in_month(date_str)->bool`."""
    out = {"total": 0, **{k: 0 for k in LEAVE_KINDS}}
    for lv in (leave or []):
        if lv.get("worker") != worker_id:
            continue
        d = lv.get("date")
        if not d or not in_month(d):
            continue
        k = lv.get("kind") if lv.get("kind") in LEAVE_KINDS else "leave"
        out[k] += 1
        out["total"] += 1
    return out


def gross_pay(worker: dict[str, Any], hours: float, ot_hours: float = 0.0,
              ot_mult: float = OT_MULT_DEFAULT) -> float:
    """Gross for the period. Hourly → regular hours × rate + overtime hours × rate × multiplier.
    Salary → the fixed monthly salary (attendance and OT shown alongside, not added or docked)."""
    pt = worker.get("pay_type")
    if pt == "hourly":
        rate = _num(worker.get("rate")) or 0.0
        reg = max(0.0, hours - (ot_hours or 0.0))
        return round(reg * rate + (ot_hours or 0.0) * rate * ot_mult, 2)
    if pt == "salary":
        return round(_num(worker.get("salary")) or 0.0, 2)
    return 0.0


def payroll(workers: list[dict[str, Any]], events: list[dict[str, Any]], lo: float, hi: float, now: float,
            day_of: Any, cal_days: list, leave: list[dict[str, Any]] | None = None,
            ot_mult: float = OT_MULT_DEFAULT) -> dict[str, Any]:
    """Monthly payroll rows + total. cal_days is [(date_str, weekday_int)] for the elapsed month.

    Adds overtime (per worker's weekly threshold), and leave/absence: a day marked as leave is not an
    unexplained absence, so days_absent counts only expected days that were neither worked nor on leave.
    """
    month_dates = {d for d, _ in cal_days}

    def _in_month(ds: str) -> bool:
        return ds in month_dates

    rows = []
    total = ot_total = 0.0
    for w in workers:
        m = worker_month(events, w["id"], lo, hi, now, day_of)
        wdays = work_weekdays(w.get("days_per_week", 5))
        expected = [d for d, wd in cal_days if wd in wdays]
        lv = leave_days(leave, w["id"], _in_month)
        leave_on = {x.get("date") for x in (leave or []) if x.get("worker") == w["id"]}
        absent = sum(1 for d in expected if d not in m["worked_days"] and d not in leave_on)
        ot = overtime_hours(m.get("by_day"), w.get("ot_weekly_h"))
        gross = gross_pay(w, m["hours"], ot, ot_mult)
        # total pay attributed to the overtime hours (hours × rate × multiplier), for display next to the OT hours
        ot_pay = round(ot * (_num(w.get("rate")) or 0.0) * ot_mult, 2) if w.get("pay_type") == "hourly" else 0.0
        total += gross
        ot_total += ot
        rows.append({"id": w["id"], "name": w.get("name"), "initials": w.get("initials"),
                     "role": w.get("role"), "pay_type": w.get("pay_type") or "none",
                     "rate": _num(w.get("rate")), "salary": _num(w.get("salary")),
                     "days_per_week": int(w.get("days_per_week") or 5),
                     "hours": m["hours"], "reg_hours": round(max(0.0, m["hours"] - ot), 2),
                     "ot_hours": ot, "ot_pay": ot_pay, "ot_weekly_h": _num(w.get("ot_weekly_h")),
                     "days_worked": len(m["worked_days"]), "expected_days": len(expected),
                     "days_absent": absent, "leave_days": lv["total"], "leave_by_kind": lv,
                     "gross": round(gross, 2)})
    return {"rows": rows, "total": round(total, 2), "ot_hours": round(ot_total, 2),
            "ot_mult": ot_mult}


def _late_today(events: list[dict[str, Any]], worker_id: str, day_start: float) -> int | None:
    """Minutes late on today's first on-site clock-in, or None if there's no shift / no clock-in today."""
    todays = [e for e in events if e.get("worker") == worker_id and e.get("kind") == IN
              and e.get("status") == ON_SITE and (_num(e.get("ts")) or 0) >= day_start]
    todays.sort(key=lambda e: e.get("ts") or 0)
    return todays[0].get("late_min") if todays else None


def summarize(workers: list[dict[str, Any]], events: list[dict[str, Any]], now: float,
              day_start: float, week_start: float, recent: int = 8) -> dict[str, Any]:
    names = {w["id"]: w.get("name", w["id"]) for w in workers}
    rows = []
    on_now = late_now = 0
    for w in workers:
        ts = timesheet(events, w["id"], now, day_start, week_start)
        on_now += 1 if ts["on_site"] else 0
        late = _late_today(events, w["id"], day_start)
        if late:
            late_now += 1
        rows.append({**w, "on_site": ts["on_site"], "since": ts["since"], "late_today": late,
                     "today_h": round(ts["today_s"] / 3600.0, 1), "week_h": round(ts["week_s"] / 3600.0, 1)})
    ev = sorted(events, key=lambda e: e.get("ts") or 0, reverse=True)[:recent]
    ev = [{**e, "worker_name": names.get(e.get("worker"), e.get("worker"))} for e in ev]
    blocked_today = sum(1 for e in events if e.get("status") == OFF_SITE_BLOCKED and (_num(e.get("ts")) or 0) >= day_start)
    on_behalf_today = sum(1 for e in events if e.get("self") is False and (_num(e.get("ts")) or 0) >= day_start)
    return {"workers": rows, "events": ev, "on_site": on_now, "total": len(workers),
            "blocked_today": blocked_today, "late_today": late_now, "on_behalf_today": on_behalf_today}


def _csv_cell(v: Any) -> str:
    s = "" if v is None else str(v)
    return '"' + s.replace('"', '""') + '"' if any(c in s for c in ',"\n') else s


def payroll_csv(data: dict[str, Any]) -> str:
    """Render a payroll/attendance month as CSV text (one row per worker)."""
    cur = data.get("currency") or ""
    cols = ["Worker", "Role", "Pay type", f"Rate/Salary ({cur})", "Days worked", "Expected", "Absent",
            "Leave", "Hours", "Overtime h", f"Gross ({cur})"]
    lines = [",".join(cols)]
    for r in data.get("rows", []):
        pay = r.get("rate") if r.get("pay_type") == "hourly" else r.get("salary") if r.get("pay_type") == "salary" else ""
        lines.append(",".join(_csv_cell(x) for x in [
            r.get("name"), r.get("role"), r.get("pay_type"), pay, r.get("days_worked"),
            r.get("expected_days"), r.get("days_absent"), r.get("leave_days"), r.get("hours"),
            r.get("ot_hours"), r.get("gross")]))
    lines.append(",".join(_csv_cell(x) for x in ["TOTAL", "", "", "", "", "", "", "", "", data.get("ot_hours"), data.get("total")]))
    return "\n".join(lines) + "\n"
