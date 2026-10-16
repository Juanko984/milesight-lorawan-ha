"""Pump analytics from current clamps (CT range): run hours, starts per hour (short-cycling), dry-run and
overload against the pump's normal current, energy and water per day, m³ per kWh. Pure Python (unit-tested)."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PumpConfig:
    enabled: bool = False
    run_a: float = 0.5               # running at or above this current
    normal_a: float = 0              # normal running current; 0 = learn it from the last week's running readings
    dry_pct: float = 60              # running below this share of normal = dry-run (lost prime, empty well)
    overload_pct: float = 125        # running above this share of normal = overload (blockage, bearing, low voltage)
    max_starts_hour: int = 6         # more starts than this in an hour = short-cycling
    confirm: int = 2                 # readings in a row before dry-run / overload is raised
    power_factor: float = 0.85       # for the energy estimate when the clamp has no energy counter
    volts: float = 0                 # mains voltage for that estimate


def pump_config(opts: dict[str, Any], run_a: float) -> PumpConfig:
    def f(key: str, default: float) -> float:
        try:
            v = opts.get(key, default)
            return float(default if v in (None, "") else v)
        except (TypeError, ValueError):
            return float(default)
    return PumpConfig(enabled=bool(opts.get("pump_enabled", False)), run_a=run_a,
                      normal_a=f("pump_normal_a", 0), dry_pct=f("pump_dry_pct", 60),
                      overload_pct=f("pump_overload_pct", 125), max_starts_hour=int(f("pump_max_starts", 6)),
                      power_factor=f("pump_power_factor", 0.85), volts=f("mains_voltage", 0))


class PumpTracker:
    LEARN_S = 7 * 86400

    def __init__(self, state: dict | None = None) -> None:
        s = state or {}
        self.s: dict[str, Any] = {
            "running": s.get("running"), "last_ts": s.get("last_ts"), "run_s": float(s.get("run_s", 0)),
            "starts": [float(x) for x in s.get("starts", [])],            # start times, last 24 h
            "learn": [list(x) for x in s.get("learn", [])],               # [ts, amps] while running (thinned)
            "dry_n": int(s.get("dry_n", 0)), "over_n": int(s.get("over_n", 0)),
            "dry": s.get("dry"), "over": s.get("over"),                    # {since, amps} while active
            "day": s.get("day"), "energy_start": s.get("energy_start"), "water_start": s.get("water_start"),
            "est_kwh": float(s.get("est_kwh", 0)),
        }

    def normal(self, cfg: PumpConfig) -> float | None:
        if cfg.normal_a > 0:
            return cfg.normal_a
        vals = [a for _, a in self.s["learn"]]
        return round(statistics.median(vals), 2) if len(vals) >= 6 else None

    def update(self, cfg: PumpConfig, ts: float, amps: float | None, day: str,
               energy_kwh: float | None = None, water_m3: float | None = None) -> list[dict[str, Any]]:
        """A clamp reading. Returns events (start, stop, dry_run, overload, short_cycling)."""
        s = self.s
        events: list[dict[str, Any]] = []
        if s["day"] != day:                                   # new day: counters for today start here
            s.update(day=day, energy_start=energy_kwh, water_start=water_m3, est_kwh=0.0)
        if s["energy_start"] is None and energy_kwh is not None:
            s["energy_start"] = energy_kwh
        if s["water_start"] is None and water_m3 is not None:
            s["water_start"] = water_m3
        if amps is None:
            return events
        running = amps >= cfg.run_a
        prev_ts, was = s["last_ts"], s["running"]
        if prev_ts is not None and was and ts > prev_ts:
            gap = min(ts - prev_ts, 3600)                     # never credit more than an hour across a gap
            s["run_s"] += gap
            if cfg.volts > 0 and energy_kwh is None:
                s["est_kwh"] += amps * cfg.volts * cfg.power_factor * gap / 3.6e6
        if running and was is False:
            s["starts"].append(ts)
            events.append({"type": "start", "amps": amps})
            if self.starts_last_hour(ts) == cfg.max_starts_hour + 1:
                events.append({"type": "short_cycling", "starts": self.starts_last_hour(ts)})
        elif was and not running:
            events.append({"type": "stop"})
        s["starts"] = [x for x in s["starts"] if ts - x <= 86400]
        s["running"], s["last_ts"] = running, ts

        normal = self.normal(cfg)
        if running:
            if not s["learn"] or ts - s["learn"][-1][0] >= 300:
                s["learn"].append([ts, amps])
            s["learn"] = [x for x in s["learn"] if ts - x[0] <= self.LEARN_S][-2000:]
        if running and normal:
            low, high = normal * cfg.dry_pct / 100, normal * cfg.overload_pct / 100
            s["dry_n"] = s["dry_n"] + 1 if amps < low else 0
            s["over_n"] = s["over_n"] + 1 if amps > high else 0
            if s["dry_n"] >= cfg.confirm and s["dry"] is None:
                s["dry"] = {"since": ts, "amps": amps}
                events.append({"type": "dry_run", "amps": amps, "normal": normal})
            if s["over_n"] >= cfg.confirm and s["over"] is None:
                s["over"] = {"since": ts, "amps": amps}
                events.append({"type": "overload", "amps": amps, "normal": normal})
            if s["dry_n"] == 0:
                s["dry"] = None
            if s["over_n"] == 0:
                s["over"] = None
        elif not running:
            s["dry_n"] = s["over_n"] = 0                      # stopped: alarms end (a stop is not a fault)
            s["dry"] = s["over"] = None
        return events

    def starts_last_hour(self, ts: float) -> int:
        return sum(1 for x in self.s["starts"] if ts - x <= 3600)

    def values(self, cfg: PumpConfig, ts: float, energy_kwh: float | None, water_m3: float | None) -> dict[str, Any]:
        s = self.s
        kwh = None
        if energy_kwh is not None and s["energy_start"] is not None:
            kwh = round(max(0.0, energy_kwh - s["energy_start"]), 3)
        elif cfg.volts > 0:
            kwh = round(s["est_kwh"], 3)
        water = round(max(0.0, water_m3 - s["water_start"]), 3) \
            if water_m3 is not None and s["water_start"] is not None else None
        starts_hour = self.starts_last_hour(ts)
        return {
            "pump_running": s["running"],
            "pump_run_hours": round(s["run_s"] / 3600, 2),
            "pump_starts_last_hour": starts_hour,
            "pump_starts_24h": sum(1 for x in s["starts"] if ts - x <= 86400),
            "pump_short_cycling": starts_hour > cfg.max_starts_hour,
            "pump_dry_run": s["dry"] is not None,
            "pump_overload": s["over"] is not None,
            "pump_normal_current": self.normal(cfg),
            "pump_energy_today": kwh,
            "pump_water_today": water,
            "pump_m3_per_kwh": round(water / kwh, 2) if water is not None and kwh and kwh >= 0.05 else None,
        }
