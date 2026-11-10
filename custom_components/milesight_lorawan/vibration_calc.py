"""ISO 10816 vibration assessment for a triaxial velocity sensor (e.g. WitMotion WTVB01-485 on a UC controller).

Pure Python (unit-tested, no Home Assistant imports). Given the X/Y/Z RMS velocities in mm/s it returns the health
verdict from the worst axis, using the ISO 10816 evaluation zones A–D. The zone edges depend on the machine class
(roughly its size and mounting), so a preset is chosen by the device's purpose; the defaults are the common small /
medium machine values."""
from __future__ import annotations

from typing import Any

# ISO 10816 evaluation zones, worst → best handled by index: A good, B satisfactory, C unsatisfactory, D unacceptable
ZONES = (("A", "Good", "ok"), ("B", "Satisfactory", "ok"), ("C", "Unsatisfactory", "warning"),
         ("D", "Unacceptable", "critical"))

# machine-class presets: the three velocity edges (mm/s) between zones A|B, B|C, C|D.
# small/medium ≈ ISO 10816-3 group 2/4 rigid; large ≈ group 1 rigid; the numbers are the widely used defaults.
MACHINE_CLASSES: dict[str, tuple[float, float, float]] = {
    "small": (2.8, 4.5, 7.1),
    "large": (4.5, 7.1, 11.0),
}
DEFAULT_CLASS = "small"
AXES = ("x", "y", "z")


def thresholds_for(machine_class: str | None) -> tuple[float, float, float]:
    return MACHINE_CLASSES.get(machine_class or DEFAULT_CLASS, MACHINE_CLASSES[DEFAULT_CLASS])


def zone_index(velocity: float, thresholds: tuple[float, float, float]) -> int:
    """0–3: which ISO zone a single-axis velocity (mm/s) falls in."""
    for i, edge in enumerate(thresholds):
        if velocity < edge:
            return i
    return len(thresholds)        # above the last edge → zone D (index 3)


def assess(velocities: dict[str, Any], machine_class: str | None = None) -> dict[str, Any]:
    """velocities: {"x": vx, "y": vy, "z": vz} in mm/s (any may be None). Returns the worst-axis ISO verdict."""
    th = thresholds_for(machine_class)
    vals = {a: float(velocities[a]) for a in AXES
            if isinstance(velocities.get(a), (int, float)) and not isinstance(velocities.get(a), bool)}
    if not vals:
        return {"verdict": None, "zone": None, "zone_index": None, "worst_axis": None, "worst_value": None,
                "severity": "unknown", "per_axis": {}, "thresholds": list(th), "machine_class": machine_class or DEFAULT_CLASS}
    worst_axis = max(vals, key=lambda a: vals[a])
    worst = round(vals[worst_axis], 2)
    zi = zone_index(worst, th)
    code, label, severity = ZONES[zi]
    return {
        "verdict": label, "zone": code, "zone_index": zi, "severity": severity,
        "worst_axis": worst_axis.upper(), "worst_value": worst,
        "per_axis": {a: ZONES[zone_index(v, th)][0] for a, v in vals.items()},
        "thresholds": list(th), "machine_class": machine_class or DEFAULT_CLASS,
    }


def zone_fraction(velocity: float, thresholds: tuple[float, float, float], top: float | None = None) -> float:
    """0..1 position of a velocity along the zone bar, for the card's marker (clamped)."""
    hi = top if top is not None else thresholds[-1] * 1.4
    if hi <= 0:
        return 0.0
    return max(0.0, min(1.0, velocity / hi))
