"""Analytics that follow a device's purpose. Pure Python (unit-tested):
* LoadTracker – a compressor / motor / AC / circuit on a current clamp or smart socket: duty cycle today and over
  24 h, run time and starts today, ran too long, not running (should cycle), on outside working hours, service due.
* TempWatch   – a fridge / freezer / geyser / pipe / silo probe: out of range for longer than a delay (door
  openings do not count), time out of range and excursions per day, a 31-day cold-chain log, rise per 24 h.
* Trend       – thinned samples for rates (bin fill per day, flood level per hour, rain in the last 24 h)."""
from __future__ import annotations

from typing import Any

DAY = 86400.0


class LoadTracker:
    AFTER_HOURS_S = 1800           # running this long outside working hours = 'on after hours'

    def __init__(self, state: dict | None = None) -> None:
        s = state or {}
        self.s: dict[str, Any] = {
            "running": s.get("running"), "since": s.get("since"), "last_ts": s.get("last_ts"),
            "first_ts": s.get("first_ts"), "day": s.get("day"), "day_start": s.get("day_start"),
            "run_today_s": float(s.get("run_today_s", 0)), "starts_today": int(s.get("starts_today", 0)),
            "total_s": float(s.get("total_s", 0)), "service_base_s": float(s.get("service_base_s", 0)),
            "runs": [list(r) for r in s.get("runs", [])], "last_stop": s.get("last_stop"),
            "cycled": bool(s.get("cycled", False)), "after_s": float(s.get("after_s", 0)),
            "after_hours": s.get("after_hours"),
        }

    def update(self, ts: float, running: bool | None, day: str, day_start: float, in_hours: bool) -> list[dict]:
        s, events = self.s, []
        if s["first_ts"] is None:
            s["first_ts"] = ts
        if s["day"] != day:
            s.update(day=day, day_start=day_start, run_today_s=0.0, starts_today=0)
        if s["running"] and s["last_ts"] is not None and ts > s["last_ts"]:
            gap = min(ts - s["last_ts"], 3600)
            s["run_today_s"] += min(gap, max(0.0, ts - day_start))
            s["total_s"] += gap
            s["after_s"] = 0.0 if in_hours else s["after_s"] + gap
        if in_hours:
            s["after_s"], s["after_hours"] = 0.0, None        # the working day started: a new night
        if running is not None:
            if running and s["running"] is False:
                s.update(since=ts)
                s["starts_today"] += 1
                events.append({"type": "start"})
            elif running and s["running"] is None:
                s["since"] = ts
            elif not running and s["running"]:
                if s["since"] is not None:
                    s["runs"].append([s["since"], ts])
                s.update(since=None, last_stop=ts, cycled=True)
                events.append({"type": "stop"})
            if not running:
                s["after_s"], s["after_hours"] = 0.0, None     # switched off: nothing is wasting energy now
            s["running"] = running
        if s["running"] and not in_hours and s["after_s"] >= self.AFTER_HOURS_S and not s["after_hours"]:
            s["after_hours"] = {"since": ts - s["after_s"]}
            events.append({"type": "after_hours"})
        s["runs"] = [r for r in s["runs"] if r[1] >= ts - DAY - 3600][-500:]
        s["last_ts"] = ts
        return events

    def serviced(self) -> None:
        self.s["service_base_s"] = self.s["total_s"]

    def duty_24h(self, ts: float) -> float | None:
        s = self.s
        start = max(ts - DAY, s["first_ts"] or ts)
        if ts - start < 3600:
            return None                                        # less than an hour seen
        runs = list(s["runs"]) + ([[s["since"], ts]] if s["running"] and s["since"] else [])
        on = sum(max(0.0, min(b, ts) - max(a, start)) for a, b in runs)
        return round(min(100.0, on / (ts - start) * 100), 1)

    def values(self, ts: float, cfg: dict[str, Any], prefix: str = "load_") -> dict[str, Any]:
        s = self.s
        seen = ts - max(s["day_start"] or ts, s["first_ts"] or ts)
        run_today = s["run_today_s"] + (min(ts - s["last_ts"], 3600) if s["running"] and s["last_ts"] else 0)
        max_h, no_h, svc_h = (float(cfg.get(k) or 0) for k in ("max_run_h", "no_run_h", "service_h"))
        ran_long = bool(max_h and s["running"] and s["since"] and ts - s["since"] >= max_h * 3600)
        idle = bool(no_h and s["cycled"] and not s["running"] and s["last_stop"]
                    and ts - s["last_stop"] >= no_h * 3600)
        svc = (s["total_s"] - s["service_base_s"]) / 3600
        out = {
            f"{prefix}running": s["running"],
            f"{prefix}duty_today": round(min(100.0, run_today / seen * 100), 1) if seen >= 600 else None,
            f"{prefix}duty_24h": self.duty_24h(ts),
            f"{prefix}run_today_h": round(run_today / 3600, 2),
            f"{prefix}starts_today": s["starts_today"],
            f"{prefix}run_total_h": round(s["total_s"] / 3600, 1),
            f"{prefix}running_for_h": round((ts - s["since"]) / 3600, 2) if s["running"] and s["since"] else 0,
        }
        if max_h:
            out[f"{prefix}ran_too_long"] = ran_long
        if no_h:
            out[f"{prefix}not_running"] = idle
        if cfg.get("after_hours"):
            out[f"{prefix}after_hours"] = bool(s["after_hours"])
        if svc_h:
            out[f"{prefix}service_in_h"] = round(svc_h - svc, 1)
            out[f"{prefix}service_due"] = svc >= svc_h
        return out


class TempWatch:
    LOG_DAYS = 31

    def __init__(self, state: dict | None = None) -> None:
        s = state or {}
        self.s: dict[str, Any] = {
            "day": s.get("day"), "last_ts": s.get("last_ts"), "last_out": bool(s.get("last_out", False)),
            "out_since": s.get("out_since"), "alarm": s.get("alarm"), "out_today_s": float(s.get("out_today_s", 0)),
            "excursions": int(s.get("excursions", 0)), "min": s.get("min"), "max": s.get("max"),
            "samples": [list(x) for x in s.get("samples", [])], "log": list(s.get("log", [])), "last": s.get("last"),
        }

    def _close_day(self) -> None:
        s = self.s
        if s["day"] is not None and s["min"] is not None:
            s["log"].append({"day": s["day"], "min": s["min"], "max": s["max"],
                             "out_min": round(s["out_today_s"] / 60), "excursions": s["excursions"]})
            s["log"] = s["log"][-self.LOG_DAYS:]

    def update(self, ts: float, t: float | None, day: str, cfg: dict[str, Any], door_open: bool = False) -> list[dict]:
        """door_open: the unit's own door contact is open – the delay starts again once it closes."""
        s, events = self.s, []
        if not isinstance(t, (int, float)) or isinstance(t, bool):
            return events
        if s["day"] != day:
            self._close_day()
            s.update(day=day, out_today_s=0.0, excursions=0, min=None, max=None)
            if s["alarm"]:
                s["excursions"] = 1                            # still out of range at midnight
        if s["last_out"] and s["last_ts"] is not None and ts > s["last_ts"]:
            s["out_today_s"] += min(ts - s["last_ts"], 3600)
        low, high = cfg.get("temp_low"), cfg.get("temp_high")
        out = (isinstance(low, (int, float)) and t < low) or (isinstance(high, (int, float)) and t > high)
        delay = float(cfg.get("temp_delay_min") or 0) * 60
        if out and door_open and s["alarm"] is None:
            s["out_since"] = None                              # loading / door open: give it time after closing
        elif out:
            if s["out_since"] is None:
                s["out_since"] = ts
            if s["alarm"] is None and ts - s["out_since"] >= delay:
                s["alarm"] = {"since": s["out_since"], "peak": t}
                s["excursions"] += 1
                events.append({"type": "out_of_range", "temperature": t, "low": low, "high": high,
                               "minutes": round((ts - s["out_since"]) / 60)})
            elif s["alarm"] is not None:
                a = s["alarm"]
                a["peak"] = max(a["peak"], t) if isinstance(high, (int, float)) and t > high else min(a["peak"], t)
        else:
            if s["alarm"] is not None:
                events.append({"type": "back_in_range", "temperature": t,
                               "minutes": round((ts - s["alarm"]["since"]) / 60)})
            s["out_since"], s["alarm"] = None, None
        s["min"] = t if s["min"] is None else min(s["min"], t)
        s["max"] = t if s["max"] is None else max(s["max"], t)
        if not s["samples"] or ts - s["samples"][-1][0] >= 3300:
            s["samples"].append([ts, t])
        s["samples"] = [x for x in s["samples"] if x[0] >= ts - DAY - 7200]
        s.update(last_ts=ts, last_out=bool(out), last=t)
        return events

    def rise_24h(self, ts: float) -> float | None:
        s = self.s
        old = [x for x in s["samples"] if x[0] <= ts - DAY + 3600]
        if not old or s["last"] is None:
            return None
        return round(s["last"] - old[-1][1], 1)

    def values(self, ts: float, cfg: dict[str, Any]) -> dict[str, Any]:
        s = self.s
        band = any(isinstance(cfg.get(k), (int, float)) for k in ("temp_low", "temp_high"))
        out_s = s["out_today_s"] + (min(ts - s["last_ts"], 3600) if s["last_out"] and s["last_ts"] else 0)
        v: dict[str, Any] = {}
        if band:
            v.update(temp_alarm=s["alarm"] is not None, temp_out_today=round(out_s / 60),
                     temp_excursions_today=s["excursions"],
                     temp_in_range=(not s["last_out"]) if s["last"] is not None else None)
        if cfg.get("temp_rise_day"):
            rise = self.rise_24h(ts)
            v.update(temp_rise_24h=rise, temp_hot_spot=bool(rise is not None and rise >= float(cfg["temp_rise_day"])))
        return v


class Trend:
    """Thinned (ts, value) samples over ~26 h plus the latest one."""

    def __init__(self, state: dict | None = None, every_s: float = 300) -> None:
        st = state or {}
        self.samples: list[list[float]] = [list(x) for x in st.get("samples", [])]
        self.last: list[float] | None = list(st["last"]) if st.get("last") else None
        self.every_s = every_s

    def to_dict(self) -> dict[str, Any]:
        return {"samples": self.samples, "last": self.last}

    def add(self, ts: float, v: Any) -> None:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return
        self.last = [ts, float(v)]
        if not self.samples or ts - self.samples[-1][0] >= self.every_s:
            self.samples.append([ts, float(v)])
        self.samples = [x for x in self.samples if x[0] >= ts - DAY - 7200]

    def _ref(self, ts: float, hours: float) -> list[float] | None:
        if not self.samples or self.last is None:
            return None
        before = [x for x in self.samples if x[0] <= ts - hours * 3600]
        return before[-1] if before else self.samples[0]

    def change(self, ts: float, hours: float) -> float | None:
        """Change over the last `hours` (needs a sample at least 80 % of that far back)."""
        ref = self._ref(ts, hours)
        if ref is None or self.last[0] - ref[0] < hours * 3600 * 0.8:
            return None
        return round(self.last[1] - ref[1], 3)

    def rate_per_h(self, ts: float, hours: float) -> float | None:
        ref = self._ref(ts, hours)
        if ref is None:
            return None
        span = self.last[0] - ref[0]
        if span < min(hours * 3600 * 0.5, 1800):
            return None
        return (self.last[1] - ref[1]) / (span / 3600)


def bin_fill(distance_mm: Any, depth_mm: float) -> float | None:
    """Waste bin: sensor in the lid, distance to the rubbish → % full."""
    if not isinstance(distance_mm, (int, float)) or depth_mm <= 0:
        return None
    return round(max(0.0, min(100.0, (depth_mm - distance_mm) / depth_mm * 100)), 0)


def water_level_cm(distance_mm: Any, empty_distance_mm: float) -> float | None:
    """River / flood: sensor above the water, distance at the lowest level → level above that in cm."""
    if not isinstance(distance_mm, (int, float)) or empty_distance_mm <= 0:
        return None
    return round((empty_distance_mm - distance_mm) / 10, 1)
