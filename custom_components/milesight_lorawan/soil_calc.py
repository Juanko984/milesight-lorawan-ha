"""Soil-probe helpers for a CWT 7-in-1 (THCPH-S) read over a UC controller (RS485/Modbus template).

Pure Python (unit-tested, no Home Assistant imports): classifies each reading against an agronomic band so the
card can colour the value — red when it's above the high threshold, amber when below the low threshold, normal
in between. The bands are sensible defaults for general cropping; they can be tuned later."""
from __future__ import annotations

from typing import Any

# (low, high) per reading. A 0 low means "only a high threshold matters" (no 'low' warning).
THRESHOLDS: dict[str, tuple[float, float]] = {
    "moisture": (20, 60),        # %
    "ec": (200, 2000),           # µS/cm (conductivity)
    "ph": (5.5, 7.5),
    "nitrogen": (30, 150),       # mg/kg
    "phosphorus": (15, 80),      # mg/kg
    "potassium": (80, 300),      # mg/kg
    "salinity": (0, 400),        # mg/L
    "tds": (0, 600),             # mg/L
}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def status(key: str, value: Any) -> str:
    """'high' (red), 'low' (amber), 'ok', or 'unknown' for one reading."""
    v = _num(value)
    if v is None:
        return "unknown"
    band = THRESHOLDS.get(key)
    if band is None:
        return "ok"
    low, high = band
    if high is not None and v > high:
        return "high"
    if low and v < low:
        return "low"
    return "ok"


def moisture_label(moisture: Any) -> str | None:
    m = _num(moisture)
    if m is None:
        return None
    return "dry" if m < THRESHOLDS["moisture"][0] else "wet" if m > THRESHOLDS["moisture"][1] else "moist"


def ph_label(ph: Any) -> str | None:
    p = _num(ph)
    if p is None:
        return None
    lo, hi = THRESHOLDS["ph"]
    return "acidic" if p < lo else "alkaline" if p > hi else "optimal"


def worst(statuses: list[str]) -> str:
    """Overall soil severity for the card's chip: a high reading outranks a low one."""
    if "high" in statuses:
        return "high"
    if "low" in statuses:
        return "low"
    return "ok"
