"""Centre-pivot analytics from a GPS tracker (AT101) on the end tower: arm angle, % of the circle done, speed,
time to finish and a stall alarm. Pure Python (unit-tested)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

EARTH_M = 6371000.0


@dataclass(frozen=True)
class PivotConfig:
    lat: float | None = None
    lon: float | None = None
    sector: float = 360            # degrees in a full round (less for part-circle pivots)
    stall_min: float = 30          # no movement for this long while running = stalled
    move_deg: float = 1.0          # smaller changes are GPS noise
    max_radius_m: float = 1500     # fixes further from the centre than this are ignored (bad fix)

    @property
    def enabled(self) -> bool:
        return self.lat is not None and self.lon is not None


def pivot_config(opts: dict[str, Any]) -> PivotConfig:
    centre = opts.get("pivot_centre") or {}
    lat = centre.get("latitude") if isinstance(centre, dict) else None
    lon = centre.get("longitude") if isinstance(centre, dict) else None

    def f(key: str, default: float) -> float:
        try:
            return float(opts.get(key, default) or default)
        except (TypeError, ValueError):
            return default
    return PivotConfig(lat=lat, lon=lon, sector=f("pivot_sector", 360), stall_min=f("pivot_stall_min", 30))


def bearing(lat0: float, lon0: float, lat: float, lon: float) -> float:
    """Compass bearing from the centre to the point, 0 = north, clockwise."""
    p0, p1, dl = math.radians(lat0), math.radians(lat), math.radians(lon - lon0)
    y = math.sin(dl) * math.cos(p1)
    x = math.cos(p0) * math.sin(p1) - math.sin(p0) * math.cos(p1) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def distance_m(lat0: float, lon0: float, lat: float, lon: float) -> float:
    p0, p1 = math.radians(lat0), math.radians(lat)
    a = math.sin((p1 - p0) / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(math.radians(lon - lon0) / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def _delta(a: float, b: float) -> float:
    """Signed smallest angle from a to b (−180 … 180)."""
    return (b - a + 540) % 360 - 180


class PivotTracker:
    def __init__(self, state: dict | None = None) -> None:
        s = state or {}
        self.s: dict[str, Any] = {
            "angle": s.get("angle"), "ts": s.get("ts"), "radius": s.get("radius"),
            "moved_ts": s.get("moved_ts"), "move_angle": s.get("move_angle"),
            "start_ts": s.get("start_ts"), "start_angle": s.get("start_angle"), "travelled": float(s.get("travelled", 0)),
            "direction": s.get("direction"), "speed": s.get("speed"), "running": bool(s.get("running", False)),
            "stalled": s.get("stalled"), "finished_ts": s.get("finished_ts"),
        }

    def update(self, cfg: PivotConfig, ts: float, lat: Any, lon: Any) -> list[dict[str, Any]]:
        """A GPS fix. Returns events (started, stalled, finished)."""
        if not cfg.enabled or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return []
        s = self.s
        r = distance_m(cfg.lat, cfg.lon, lat, lon)
        if r > cfg.max_radius_m or r < 5:
            return []                                    # bad fix, or the tracker is at the centre
        ang = bearing(cfg.lat, cfg.lon, lat, lon)
        s["radius"] = round(r, 1)
        events: list[dict[str, Any]] = []
        if s["move_angle"] is None:
            s.update(angle=ang, ts=ts, move_angle=ang, moved_ts=ts)
            return events
        d = _delta(s["move_angle"], ang)
        if abs(d) >= cfg.move_deg:                       # it moved
            dt_h = max(1e-6, (ts - s["moved_ts"]) / 3600)
            speed = abs(d) / dt_h
            s["speed"] = round(speed if s["speed"] is None else 0.6 * speed + 0.4 * s["speed"], 2)
            direction = "clockwise" if d > 0 else "anticlockwise"
            if not s["running"]:
                s.update(running=True, start_ts=s["moved_ts"], start_angle=s["move_angle"], travelled=0.0,
                         direction=direction, finished_ts=None)
                events.append({"type": "started", "angle": round(s["move_angle"], 1), "direction": direction})
            if s["stalled"]:
                s["stalled"] = None
            if direction == s["direction"]:
                s["travelled"] += abs(d)
            else:                                        # reversed (part-circle pivots): a new pass
                s.update(direction=direction, start_angle=s["move_angle"], start_ts=s["moved_ts"], travelled=abs(d))
            s["move_angle"], s["moved_ts"] = ang, ts
            if s["travelled"] >= cfg.sector - cfg.move_deg:
                s.update(running=False, finished_ts=ts, speed=None)
                events.append({"type": "finished", "angle": round(ang, 1)})
        s["angle"], s["ts"] = ang, ts
        events += self.check(cfg, ts)
        return events

    def check(self, cfg: PivotConfig, ts: float) -> list[dict[str, Any]]:
        """Run every minute too: a pivot that stops sends no new fixes."""
        s = self.s
        if s["running"] and not s["stalled"] and s["moved_ts"] is not None and \
                ts - s["moved_ts"] >= cfg.stall_min * 60:
            s["stalled"] = {"since": s["moved_ts"], "angle": s["move_angle"]}
            return [{"type": "stalled", "angle": round(s["move_angle"], 1),
                     "minutes": round((ts - s["moved_ts"]) / 60)}]
        return []

    def stop(self) -> None:
        """'Pivot stopped' button: the round is over (stopped on purpose), clears the stall alarm."""
        self.s.update(running=False, stalled=None, speed=None)

    def values(self, cfg: PivotConfig, ts: float) -> dict[str, Any]:
        s = self.s
        progress = min(100.0, s["travelled"] / cfg.sector * 100) if s["start_ts"] is not None else None
        if not s["running"] and s["finished_ts"]:
            progress = 100.0
        remaining = max(0.0, cfg.sector - s["travelled"])
        hours = remaining / s["speed"] if s["running"] and s["speed"] and not s["stalled"] else None
        status = ("stalled" if s["stalled"] else "running" if s["running"] else
                  "finished" if s["finished_ts"] else "stopped" if s["angle"] is not None else None)
        return {
            "pivot_angle": round(s["angle"], 1) if s["angle"] is not None else None,
            "pivot_progress": round(progress, 1) if progress is not None else None,
            "pivot_speed": s["speed"] if s["running"] else 0 if s["angle"] is not None else None,
            "pivot_finish_in": round(hours, 2) if hours is not None else None,
            "pivot_finish_at": ts + hours * 3600 if hours is not None else None,
            "pivot_status": status,
            "pivot_stalled": bool(s["stalled"]) if cfg.enabled else None,
            "pivot_direction": s["direction"],
            "pivot_radius": s["radius"],
            "pivot_started_at": s["start_ts"] if s["running"] else None,
        }
