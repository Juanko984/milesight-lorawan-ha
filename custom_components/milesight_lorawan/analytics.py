"""Time-based analytics: binary event stats (door/leak/input) and occupancy.

Pure Python (no Home Assistant imports). All timestamps are epoch seconds;
day / week / month boundaries use the supplied time zone (DST-safe).
State lives in plain dicts so it can be stored as JSON.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

PERIODS = ("day", "week", "month")


# --------------------------------------------------------------------------
# Calendar helpers
# --------------------------------------------------------------------------
class Calendar:
    def __init__(self, tz: tzinfo) -> None:
        self.tz = tz

    def local_date(self, ts: float) -> date:
        return datetime.fromtimestamp(ts, self.tz).date()

    def day_start(self, d: date) -> float:
        return datetime.combine(d, time(0), self.tz).timestamp()

    def next_midnight(self, ts: float) -> float:
        return self.day_start(self.local_date(ts) + timedelta(days=1))

    def key(self, period: str, ts: float) -> str:
        return self.key_for_date(period, self.local_date(ts))

    @staticmethod
    def key_for_date(period: str, d: date) -> str:
        if period == "day":
            return d.isoformat()
        if period == "week":
            return "W" + (d - timedelta(days=d.weekday())).isoformat()
        return d.strftime("%Y-%m")

    def prev_key(self, period: str, ts: float) -> str:
        d = self.local_date(ts)
        if period == "day":
            return self.key_for_date("day", d - timedelta(days=1))
        if period == "week":
            return self.key_for_date("week", d - timedelta(days=7))
        first = d.replace(day=1)
        return self.key_for_date("month", first - timedelta(days=1))

    def segments(self, start: float, end: float):
        """Split [start, end) at local midnights."""
        a = start
        while a < end:
            b = min(end, self.next_midnight(a))
            yield a, b
            a = b


# --------------------------------------------------------------------------
# Binary event tracker (door open, leak detected, input high ...)
# --------------------------------------------------------------------------
class BinaryEventTracker:
    """Tracks how long / how often a binary input is active, per day/week/month."""

    def __init__(self, cal: Calendar, state: dict | None = None,
                 max_gap_s: float = 7200, left_open_s: float = 600) -> None:
        self.cal = cal
        self.max_gap_s = max_gap_s
        self.left_open_s = left_open_s
        self.s: dict[str, Any] = state or {
            "active": None, "since": None, "last_seen": None, "credited_until": None,
            "last_duration": None, "last_on_at": None, "last_off_at": None,
            "cur": {}, "prev": {},
        }

    # -- internals ---------------------------------------------------------
    def _roll(self, ts: float) -> None:
        for p in PERIODS:
            k = self.cal.key(p, ts)
            cur = self.s["cur"].get(p)
            if not cur or cur["key"] != k:
                if cur:
                    self.s["prev"][p] = cur
                self.s["cur"][p] = {"key": k, "on_s": 0.0, "count": 0, "longest_s": 0.0}

    def _credit(self, ts: float) -> None:
        s = self.s
        if not s["active"] or s["last_seen"] is None or s["credited_until"] is None:
            return
        end = min(ts, s["last_seen"] + self.max_gap_s)
        if end <= s["credited_until"]:
            return
        for a, b in self.cal.segments(s["credited_until"], end):
            self._roll(a)
            for p in PERIODS:
                s["cur"][p]["on_s"] += b - a
        s["credited_until"] = end

    # -- public ------------------------------------------------------------
    def update(self, ts: float, active: bool | None) -> None:
        s = self.s
        self._credit(ts)
        self._roll(ts)
        if active is not None:
            if active and s["active"] is not True:
                s["since"] = ts
                if s["active"] is False:              # real off -> on (not first reading)
                    s["last_on_at"] = ts
                    for p in PERIODS:
                        s["cur"][p]["count"] += 1
            elif not active and s["active"] is True:
                dur = ts - s["since"] if s["since"] else None
                s["last_duration"] = dur
                s["last_off_at"] = ts
                if dur is not None:
                    for p in PERIODS:
                        s["cur"][p]["longest_s"] = max(s["cur"][p]["longest_s"], dur)
                s["since"] = None
            s["active"] = active
        s["last_seen"] = ts
        s["credited_until"] = ts

    def tick(self, ts: float) -> None:
        self._credit(ts)
        self._roll(ts)

    def values(self, ts: float) -> dict[str, Any]:
        s = self.s
        self._roll(ts)
        cur_s = (ts - s["since"]) if s["active"] and s["since"] else 0.0

        def prev(p: str, f: str) -> float:
            pv = s["prev"].get(p)
            return pv[f] if pv and pv["key"] == self.cal.prev_key(p, ts) else 0

        day, week, month = (s["cur"][p] for p in PERIODS)
        return {
            "active": s["active"],
            "since": s["since"] if s["active"] else None,
            "current_s": cur_s,
            "left_open": cur_s >= self.left_open_s,
            "last_duration_s": s["last_duration"],
            "last_on_at": s["last_on_at"],
            "last_off_at": s["last_off_at"],
            "today_s": day["on_s"], "yesterday_s": prev("day", "on_s"),
            "week_s": week["on_s"], "last_week_s": prev("week", "on_s"),
            "month_s": month["on_s"], "last_month_s": prev("month", "on_s"),
            "count_today": day["count"], "count_yesterday": prev("day", "count"),
            "count_week": week["count"], "count_last_week": prev("week", "count"),
            "count_month": month["count"], "count_last_month": prev("month", "count"),
            "longest_today_s": max(day["longest_s"], cur_s),
            "longest_week_s": max(week["longest_s"], cur_s),
            "avg_today_s": day["on_s"] / day["count"] if day["count"] else 0.0,
        }


# --------------------------------------------------------------------------
# Daily min / max
# --------------------------------------------------------------------------
class MinMaxTracker:
    def __init__(self, cal: Calendar, state: dict | None = None) -> None:
        self.cal = cal
        self.s: dict[str, Any] = state or {"key": None, "min": {}, "max": {}}

    def update(self, ts: float, values: dict[str, float]) -> None:
        k = self.cal.key("day", ts)
        if self.s["key"] != k:
            self.s = {"key": k, "min": {}, "max": {}}
        for f, v in values.items():
            if isinstance(v, (int, float)):
                self.s["min"][f] = v if f not in self.s["min"] else min(self.s["min"][f], v)
                self.s["max"][f] = v if f not in self.s["max"] else max(self.s["max"][f], v)

    def get(self, ts: float, kind: str, f: str) -> float | None:
        if self.s["key"] != self.cal.key("day", ts):
            return None
        return self.s[kind].get(f)


# --------------------------------------------------------------------------
# Occupancy (people counter) with debounce, peak, person-minutes, utilisation
# --------------------------------------------------------------------------
def _new_day(key: str) -> dict[str, Any]:
    return {"key": key, "occ_s": 0.0, "open_occ_s": 0.0, "person_s": 0.0,
            "sessions": 0, "peak": 0, "peak_at": None, "longest_s": 0.0}


class OccupancyTracker:
    def __init__(self, cal: Calendar, state: dict | None = None, *,
                 grace_s: float = 120, max_gap_s: float = 1800,
                 open_hour: int = 8, close_hour: int = 17,
                 open_days: tuple[int, ...] = (0, 1, 2, 3, 4)) -> None:
        self.cal = cal
        self.grace_s = grace_s
        self.max_gap_s = max_gap_s
        self.open_hour = open_hour
        self.close_hour = close_hour
        self.open_days = tuple(open_days)
        self.s: dict[str, Any] = state or {
            "occupied": False, "since": None, "empty_since": None,
            "pend": [0.0, 0.0, 0.0],                     # occ_s, open_occ_s, person_s
            "last_seen": None, "credited_until": None, "last_count": 0,
            "last_session_s": None, "day": None, "prev_day": None,
        }

    # -- internals ---------------------------------------------------------
    def _roll(self, ts: float) -> None:
        k = self.cal.key("day", ts)
        if not self.s["day"] or self.s["day"]["key"] != k:
            if self.s["day"]:
                self.s["prev_day"] = self.s["day"]
            self.s["day"] = _new_day(k)

    def _open_window(self, d: date) -> tuple[float, float] | None:
        if d.weekday() not in self.open_days or self.close_hour <= self.open_hour:
            return None
        start = datetime.combine(d, time(self.open_hour), self.cal.tz).timestamp()
        if self.close_hour >= 24:
            end = self.cal.day_start(d + timedelta(days=1))
        else:
            end = datetime.combine(d, time(self.close_hour), self.cal.tz).timestamp()
        return start, end

    def _open_overlap(self, a: float, b: float) -> float:
        w = self._open_window(self.cal.local_date(a))
        return max(0.0, min(b, w[1]) - max(a, w[0])) if w else 0.0

    def _credit(self, ts: float) -> None:
        s = self.s
        if not s["occupied"] or s["last_seen"] is None or s["credited_until"] is None:
            return
        end = min(ts, s["last_seen"] + self.max_gap_s)
        if end <= s["credited_until"]:
            return
        people = max(s["last_count"], 1)
        for a, b in self.cal.segments(s["credited_until"], end):
            self._roll(a)
            sec, open_sec = b - a, self._open_overlap(a, b)
            if s["empty_since"] is None:
                d = s["day"]
                d["occ_s"] += sec
                d["open_occ_s"] += open_sec
                d["person_s"] += people * sec
            else:
                s["pend"][0] += sec
                s["pend"][1] += open_sec
                s["pend"][2] += people * sec
        s["credited_until"] = end

    def _confirm_empty_if_due(self, ts: float) -> None:
        s = self.s
        if s["occupied"] and s["empty_since"] is not None and ts - s["empty_since"] >= self.grace_s:
            dur = s["empty_since"] - s["since"]
            s["last_session_s"] = dur
            s["day"]["longest_s"] = max(s["day"]["longest_s"], dur)
            s["occupied"] = False
            s["since"] = None
            s["empty_since"] = None
            s["pend"] = [0.0, 0.0, 0.0]

    # -- public ------------------------------------------------------------
    def update(self, ts: float, count: int) -> None:
        s = self.s
        self._credit(ts)
        self._roll(ts)
        if count > 0:
            if not s["occupied"]:
                s["occupied"] = True
                s["since"] = ts
                s["day"]["sessions"] += 1
            elif s["empty_since"] is not None:          # back within grace: same session
                d = s["day"]
                d["occ_s"] += s["pend"][0]
                d["open_occ_s"] += s["pend"][1]
                d["person_s"] += s["pend"][2]
            s["empty_since"] = None
            s["pend"] = [0.0, 0.0, 0.0]
        elif s["occupied"] and s["empty_since"] is None:
            s["empty_since"] = ts
            s["pend"] = [0.0, 0.0, 0.0]
        if count > s["day"]["peak"]:
            s["day"]["peak"] = count
            s["day"]["peak_at"] = ts
        s["last_count"] = count
        s["last_seen"] = ts
        s["credited_until"] = ts
        self._confirm_empty_if_due(ts)

    def tick(self, ts: float) -> None:
        self._credit(ts)
        self._roll(ts)
        self._confirm_empty_if_due(ts)

    def values(self, ts: float) -> dict[str, Any]:
        s = self.s
        self._roll(ts)
        d = s["day"]
        pd = s["prev_day"]
        y = pd if pd and pd["key"] == self.cal.prev_key("day", ts) else _new_day("")
        cur = (ts - s["since"]) if s["occupied"] and s["since"] else 0.0

        today = self.cal.local_date(ts)
        w = self._open_window(today)
        open_so_far = max(0.0, min(ts, w[1]) - w[0]) if w else 0.0
        yw = self._open_window(today - timedelta(days=1))
        y_open_total = (yw[1] - yw[0]) if yw else 0.0

        def pct(a: float, b: float) -> float | None:
            return round(a / b * 100, 1) if b > 0 else None

        return {
            "occupied": s["occupied"],
            "vacancy_pending": s["empty_since"] is not None,
            "people_count": s["last_count"],
            "occupied_since": s["since"] if s["occupied"] else None,
            "occupied_duration_s": cur,
            "last_session_s": s["last_session_s"],
            "longest_session_today_s": max(d["longest_s"], cur),
            "occupied_today_s": d["occ_s"],
            "occupied_yesterday_s": y["occ_s"],
            "sessions_today": d["sessions"],
            "sessions_yesterday": y["sessions"],
            "peak_today": d["peak"],
            "peak_today_at": d["peak_at"],
            "peak_yesterday": y["peak"],
            "person_minutes_today": round(d["person_s"] / 60),
            "person_minutes_yesterday": round(y["person_s"] / 60),
            "avg_people_today": round(d["person_s"] / d["occ_s"], 1) if d["occ_s"] > 0 else 0.0,
            "open_now": bool(w and w[0] <= ts < w[1]),
            "utilisation_today_pct": pct(d["open_occ_s"], open_so_far),
            "utilisation_yesterday_pct": pct(y["open_occ_s"], y_open_total),
        }


# --------------------------------------------------------------------------
# Distance travelled (GNSS trackers)
# --------------------------------------------------------------------------
EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(min(1.0, sqrt(a)))


class DistanceTracker:
    """Sums the straight-line distance between successive position fixes per day / week / month.
    Moves shorter than ``min_move_m`` are treated as GNSS jitter: the reference point is kept, so
    slow movement still adds up once it exceeds the threshold."""

    def __init__(self, cal: Calendar, state: dict | None = None, min_move_m: float = 50,
                 max_speed_kmh: float = 300) -> None:
        self.cal = cal
        self.min_move_m = min_move_m
        self.max_speed_kmh = max_speed_kmh
        self.s: dict[str, Any] = state or {"ref": None, "cur": {}, "prev": {}}

    def _roll(self, ts: float) -> None:
        for p in PERIODS:
            k = self.cal.key(p, ts)
            cur = self.s["cur"].get(p)
            if cur is None or cur["key"] != k:
                if cur is not None:
                    self.s["prev"][p] = cur
                self.s["cur"][p] = {"key": k, "m": 0.0}

    def update(self, ts: float, lat: float | None, lon: float | None) -> None:
        self._roll(ts)
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or (lat == 0 and lon == 0):
            return
        ref = self.s["ref"]
        if ref is None:
            self.s["ref"] = [lat, lon, ts]
            return
        d = haversine_m(ref[0], ref[1], lat, lon)
        if d < self.min_move_m:
            return
        dt_h = max(ts - ref[2], 1) / 3600
        if d / 1000 / dt_h <= self.max_speed_kmh:          # ignore impossible jumps (bad fix)
            for p in PERIODS:
                self.s["cur"][p]["m"] += d
        self.s["ref"] = [lat, lon, ts]

    def values(self, ts: float) -> dict[str, float | None]:
        self._roll(ts)
        out: dict[str, float | None] = {}
        names = {"day": ("today", "yesterday"), "week": ("week", "last_week"), "month": ("month", "last_month")}
        for p, (now_name, prev_name) in names.items():
            out[f"distance_{now_name}_km"] = round(self.s["cur"][p]["m"] / 1000, 2)
            prev = self.s["prev"].get(p)
            out[f"distance_{prev_name}_km"] = (round(prev["m"] / 1000, 2)
                                               if prev and prev["key"] == self.cal.prev_key(p, ts) else 0.0)
        return out


# --------------------------------------------------------------------------
# Period counters (people counters: sums of the per-report in / out counts)
# --------------------------------------------------------------------------
class CounterTracker:
    """Adds up per-report counts (e.g. people_in / people_out) per day / week / month."""

    NAMES = {"day": ("today", "yesterday"), "week": ("week", "last_week"), "month": ("month", "last_month")}

    def __init__(self, cal: Calendar, fields: tuple[str, ...], state: dict | None = None) -> None:
        self.cal = cal
        self.fields = fields
        self.s: dict[str, Any] = state or {"cur": {}, "prev": {}}

    def _roll(self, ts: float) -> None:
        for p in PERIODS:
            k = self.cal.key(p, ts)
            cur = self.s["cur"].get(p)
            if cur is None or cur["key"] != k:
                if cur is not None:
                    self.s["prev"][p] = cur
                self.s["cur"][p] = {"key": k, "sums": {}}

    def update(self, ts: float, values: dict[str, Any]) -> None:
        self._roll(ts)
        for f in self.fields:
            v = values.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                for p in PERIODS:
                    sums = self.s["cur"][p]["sums"]
                    sums[f] = sums.get(f, 0) + v

    def values(self, ts: float) -> dict[str, Any]:
        self._roll(ts)
        out: dict[str, Any] = {}
        for p, (now_name, prev_name) in self.NAMES.items():
            prev = self.s["prev"].get(p)
            prev_ok = prev is not None and prev["key"] == self.cal.prev_key(p, ts)
            for f in self.fields:
                out[f"{f}_{now_name}"] = self.s["cur"][p]["sums"].get(f, 0)
                out[f"{f}_{prev_name}"] = prev["sums"].get(f, 0) if prev_ok else 0
        return out
