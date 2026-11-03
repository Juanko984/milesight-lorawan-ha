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


def new_worker(name: str, *, role: str = "", tracker: str | None = None, method: str = "app",
               active: bool = True, wid: str = "") -> dict[str, Any]:
    return {"id": wid, "name": str(name), "initials": initials(name), "role": str(role or ""),
            "tracker": tracker or None, "method": method, "active": bool(active)}


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
