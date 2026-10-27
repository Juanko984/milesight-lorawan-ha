"""Tank / silo contents from a level or distance sensor: litres, fill, usage per day, days until empty, refills
and sudden drops (theft or a leak). Pure Python (unit-tested).

Level: distance sensors (EM400-UDL / EM410-RDL / EM310-UDL / EM500-UDL) measure from the sensor down to the
surface, so level = empty distance − distance. Submersible probes (EM500-SWL) report the depth of water above
the probe, so level = depth + the probe's height above the tank floor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

SHAPES = ("none", "vertical_cylinder", "horizontal_cylinder", "rectangular", "cone_bottom", "linear")


@dataclass(frozen=True)
class TankConfig:
    shape: str = "none"
    height_mm: float = 0          # usable height (level when full); cone_bottom: total incl. the cone
    diameter_mm: float = 0        # cylinders / silo
    length_mm: float = 0          # horizontal cylinder / rectangular
    width_mm: float = 0           # rectangular
    cone_mm: float = 0            # cone_bottom: height of the cone (hopper)
    capacity_l: float = 0         # linear: litres when full (also overrides the computed capacity if set)
    empty_distance_mm: float = 0  # distance sensors: reading when the tank is empty (sensor to floor)
    probe_offset_mm: float = 0    # depth probes: probe height above the floor
    density: float = 0            # kg/m³ (feed ~ 650, diesel ~ 840); 0 = no weight
    low_pct: float = 20           # low-level alarm below this fill; 0 = off
    refill_pct: float = 5         # a rise of at least this share of capacity is a refill
    drop_pct: float = 0           # sudden-drop alarm: fall of at least this share …
    drop_minutes: float = 60      # … within this many minutes; 0 % = off
    contents: str = "water"       # water / fuel / feed (grain-feed silo) / other → water vs silo routing

    @property
    def enabled(self) -> bool:
        return self.shape in SHAPES[1:] and self.height_mm > 0

    @property
    def is_silo(self) -> bool:
        """A grain/feed silo (routed to the Farm dashboard, not Water)."""
        return self.contents == "feed"


CONTENTS = ("water", "fuel", "feed", "other")       # what the tank holds
DEFAULT_DENSITY = {"water": 1000, "fuel": 840, "feed": 650, "other": 0}   # kg/m³, used when density left at 0


def tank_config(opts: dict[str, Any]) -> TankConfig:
    """TankConfig from a device's options (keys tank_*; the distance sensors' install height is the empty distance)."""
    def f(key: str, default: float = 0) -> float:
        try:
            return float(opts.get(key, default) or 0)
        except (TypeError, ValueError):
            return float(default)
    shape = opts.get("tank_shape") or "none"
    height = f("tank_height_mm")
    diameter = f("tank_diameter_mm")
    if shape == "horizontal_cylinder" and diameter > 0:
        height = diameter                       # a lying cylinder is as high as it is wide
    empty = f("install_height_mm")
    if height <= 0 and empty > 0 and shape != "none":
        height = empty                          # sensor mounted at the top of the tank
    contents = opts.get("tank_contents") or "water"
    if contents not in CONTENTS:
        contents = "water"
    return TankConfig(shape=shape if shape in SHAPES else "none", height_mm=height, diameter_mm=diameter,
                      length_mm=f("tank_length_mm"), width_mm=f("tank_width_mm"), cone_mm=f("tank_cone_mm"),
                      capacity_l=f("tank_capacity_l"), empty_distance_mm=empty, probe_offset_mm=f("tank_probe_offset_mm"),
                      density=f("tank_density"), low_pct=f("tank_low_pct", 20), refill_pct=f("tank_refill_pct", 5) or 5,
                      drop_pct=f("tank_drop_pct"), drop_minutes=f("tank_drop_minutes", 60) or 60, contents=contents)


def volume_l(cfg: TankConfig, level_mm: float) -> float:
    """Litres at a liquid level (mm), clamped to the tank."""
    h = max(0.0, min(float(level_mm), cfg.height_mm))
    r = cfg.diameter_mm / 2
    if cfg.shape == "vertical_cylinder":
        v = math.pi * r * r * h
    elif cfg.shape == "horizontal_cylinder":
        # lying cylinder: the height is the diameter
        r = (cfg.diameter_mm or cfg.height_mm) / 2
        h = min(h, 2 * r)
        v = cfg.length_mm * (r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(max(0.0, 2 * r * h - h * h))) \
            if r > 0 else 0.0
    elif cfg.shape == "rectangular":
        v = cfg.length_mm * cfg.width_mm * h
    elif cfg.shape == "cone_bottom":
        hc = min(cfg.cone_mm, cfg.height_mm)
        if hc <= 0:
            v = math.pi * r * r * h
        elif h <= hc:
            rr = r * h / hc
            v = math.pi * rr * rr * h / 3
        else:
            v = math.pi * r * r * hc / 3 + math.pi * r * r * (h - hc)
    elif cfg.shape == "linear":
        return round(cfg.capacity_l * h / cfg.height_mm, 1) if cfg.height_mm else 0.0
    else:
        return 0.0
    return round(v / 1e6, 1)


def capacity_l(cfg: TankConfig) -> float:
    if cfg.capacity_l > 0:
        return cfg.capacity_l
    return volume_l(cfg, cfg.height_mm)


def level_mm(cfg: TankConfig, source: str, value: Any) -> float | None:
    """Liquid level from the sensor's reading: source 'distance' (mm) or 'depth' (cm)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if source == "distance":
        empty = cfg.empty_distance_mm or cfg.height_mm
        lvl = empty - value
    elif source == "depth":
        lvl = value * 10 + cfg.probe_offset_mm
    else:
        return None
    return round(max(0.0, min(lvl, cfg.height_mm)), 0)


class TankTracker:
    """Keeps a week of contents samples to work out usage, refills and sudden drops.

    A big jump (refill or sudden drop) is only believed when the next reading confirms it; a single echo glitch
    that comes back is dropped. Refills are recognised from a run of rises, so slow pump refills count too."""

    KEEP_S = 8 * 86400
    WINDOW_S = 7 * 86400
    MIN_SPAN_S = 6 * 3600          # usage needs at least this much history
    THIN_S = 600                    # about one sample per 10 minutes

    def __init__(self, state: dict | None = None) -> None:
        s = state or {}
        self.s: dict[str, Any] = {
            "samples": [list(x) for x in s.get("samples", [])],  # [ts, litres]
            "last_refill": s.get("last_refill"),                  # {ts, added, litres}
            "refill_mark": s.get("refill_mark"),                  # 'Tank refilled' pressed (drop window restarts)
            "drop": s.get("drop"),                                # {ts, amount} while the alarm is on
            "drop_cleared": s.get("drop_cleared"),                # readings before this don't count for drops
            "suspect": s.get("suspect"),                          # unconfirmed big jump
            "run": s.get("run"),                                  # {from, done}: current run of rises
            "geom": s.get("geom"),
        }

    @staticmethod
    def _limits(cfg: TankConfig) -> tuple[float, float, float | None]:
        cap = capacity_l(cfg) or 1.0
        refill = cap * cfg.refill_pct / 100
        return min(cap * 0.01, refill), refill, (cap * cfg.drop_pct / 100 if cfg.drop_pct > 0 else None)

    def check_config(self, cfg: TankConfig) -> None:
        """Litres from another tank size can't be compared: start afresh when the size changes."""
        geom = [cfg.shape, cfg.height_mm, cfg.diameter_mm, cfg.length_mm, cfg.width_mm, cfg.cone_mm,
                cfg.capacity_l, cfg.empty_distance_mm, cfg.probe_offset_mm]
        if self.s["geom"] is not None and self.s["geom"] != geom:
            self.s.update(samples=[], drop=None, suspect=None, run=None, refill_mark=None, drop_cleared=None)
        self.s["geom"] = geom

    def update(self, cfg: TankConfig, ts: float, litres: float) -> list[dict[str, Any]]:
        """Add a reading; returns events ({type: refill | sudden_drop, …})."""
        jitter, refill_th, drop_th = self._limits(cfg)
        samples = self.s["samples"]
        if samples and ts < samples[-1][0]:
            return []                                        # out of order (stored history)
        sus = self.s["suspect"]
        if sus is not None:
            self.s["suspect"] = None
            if abs(litres - sus["base"]) < abs(sus["litres"] - sus["base"]) / 2:   # came back: a glitch
                if samples and samples[-1][0] == sus["ts"]:
                    samples.pop()
                self.s["run"] = sus.get("run")
        elif samples:
            jump = litres - samples[-1][1]
            big = refill_th if jump > 0 else drop_th
            if big and abs(jump) >= big:                     # wait for the next reading before believing it
                self.s["suspect"] = {"ts": ts, "litres": litres, "base": samples[-1][1], "run": self.s["run"]}
                self._track_run(samples[-1][1], litres, ts, refill_th, jitter, quiet=True)
                samples.append([ts, litres])
                return []
        events: list[dict[str, Any]] = []
        prev = samples[-1] if samples else None
        if prev is not None:
            ev = self._track_run(prev[1], litres, ts, refill_th, jitter)
            if ev:
                events.append(ev)
        if drop_th is not None and self.s["drop"] is None:
            since = self.s["drop_cleared"] or 0
            window = [x[1] for x in samples if ts - x[0] <= cfg.drop_minutes * 60 and x[0] >= since]
            if window and max(window) - litres >= drop_th:
                fall = max(window) - litres
                self.s["drop"] = {"ts": ts, "amount": round(fall, 1)}
                events.append({"type": "sudden_drop", "amount": round(fall, 1), "litres": round(litres, 1),
                               "minutes": cfg.drop_minutes})
        if len(samples) >= 2 and samples[-1][0] - samples[-2][0] < self.THIN_S and not events:
            samples[-1] = [ts, litres]                       # keep about one reading per 10 minutes
        else:
            samples.append([ts, litres])
        while samples and ts - samples[0][0] > self.KEEP_S:
            samples.pop(0)
        return events

    def _track_run(self, prev: float, litres: float, ts: float, refill_th: float, jitter: float,
                   quiet: bool = False) -> dict[str, Any] | None:
        d = litres - prev
        run = self.s["run"]
        if d < -jitter:
            self.s["run"] = None
            return None
        if run is None:
            if d <= jitter:
                return None
            run = self.s["run"] = {"from": prev, "done": False}
        added = round(litres - run["from"], 1)
        if run["done"]:
            if self.s["last_refill"]:
                self.s["last_refill"].update(added=added, litres=round(litres, 1))
            return None
        if added >= refill_th and not quiet:
            run["done"] = True
            self.s["last_refill"] = {"ts": ts, "added": added, "litres": round(litres, 1)}
            self.s["drop"] = None
            return {"type": "refill", "added": added, "litres": round(litres, 1)}
        return None

    def mark_refilled(self, ts: float, litres: float | None) -> None:
        self.s["refill_mark"] = ts
        self.s["last_refill"] = {"ts": ts, "added": None, "litres": litres}
        self.s["run"] = None
        self.clear_alarm(ts)

    def clear_alarm(self, ts: float) -> None:
        """Drops are measured from the current reading on (the fall that raised the alarm no longer counts)."""
        self.s["drop"] = None
        samples = [x for x in self.s["samples"] if x[0] <= ts]
        self.s["drop_cleared"] = samples[-1][0] if samples else ts

    def usage_per_day(self, cfg: TankConfig, ts: float) -> float | None:
        """Litres used per day over the last week: rises (refills) are not use, small rises (sensor jitter)
        cancel small falls."""
        jitter, _, _ = self._limits(cfg)
        pts = [x for x in self.s["samples"] if ts - x[0] <= self.WINDOW_S]
        if self.s["suspect"] is not None and pts and pts[-1][0] == self.s["suspect"]["ts"]:
            pts = pts[:-1]
        if len(pts) < 2 or pts[-1][0] - pts[0][0] < self.MIN_SPAN_S:
            return None
        used = 0.0
        for (_, a), (_, b) in zip(pts, pts[1:]):
            d = b - a
            if d < 0:
                used -= d
            elif d <= jitter:
                used -= d
        days = (pts[-1][0] - pts[0][0]) / 86400
        return round(max(0.0, used) / days, 1)

    def values(self, cfg: TankConfig, ts: float, litres: float | None) -> dict[str, Any]:
        cap = capacity_l(cfg)
        use = self.usage_per_day(cfg, ts)
        days = None
        if litres is not None and use:
            days = round(litres / use, 1) if use > cap * 0.0005 else None   # practically no use → no estimate
        fill = round(litres / cap * 100, 1) if litres is not None and cap else None
        lr = self.s["last_refill"]
        return {
            "tank_volume": litres,
            "tank_fill": fill,
            "tank_capacity": cap,
            "tank_free": round(cap - litres, 1) if litres is not None and cap else None,
            "tank_usage_per_day": use,
            "tank_days_left": days,
            "tank_empty_at": ts + days * 86400 if days is not None else None,
            "tank_mass": round(litres / 1000 * cfg.density, 1) if litres is not None and cfg.density > 0 else None,
            "tank_low": (fill < cfg.low_pct) if fill is not None and cfg.low_pct > 0 else None,
            "tank_sudden_drop": (self.s["drop"] is not None) if cfg.drop_pct > 0 else None,
            "tank_last_refill": lr["ts"] if lr else None,
            "tank_last_refill_added": lr.get("added") if lr else None,
            "tank_drop_amount": self.s["drop"]["amount"] if self.s["drop"] else None,
        }
