"""Mould (mold) growth risk from indoor temperature + relative humidity (pure, unit-tested).

Two published values per temp+humidity device:
  • Mould risk  — a 0–3 level with the same wording hosts know from the "Mould Indicator" integration:
        0  No mold growth risk
        1  Mold growth risk after 8+ weeks
        2  Mold growth risk in 4–8 weeks
        3  Mold growth risk in <4 weeks
  • Mould index — 0–100 %, how far the air sits above the temperature's critical humidity (0 = at/below it).

The level comes from Viitanen's critical-time-for-mould model (weeks to first growth on a sensitive surface) and
the critical humidity from Hukka & Viitanen's RH_crit(T) curve — both published, so the numbers are defensible.
Only indoor air T/RH is used (no wall/outdoor probe), so this is an air-based estimate, not a surface measurement.
"""
from __future__ import annotations

import math

LEVEL_TEXT = {
    0: "No mold growth risk",
    1: "Mold growth risk after 8+ weeks",
    2: "Mold growth risk in 4–8 weeks",
    3: "Mold growth risk in <4 weeks",
}


def rh_critical(temp_c: float) -> float | None:
    """Lowest relative humidity (%) at which mould can grow at this temperature (Hukka & Viitanen).
    None when it is too cold or too hot for growth (≤0 °C or ≥50 °C)."""
    t = temp_c
    if t <= 0 or t >= 50:
        return None
    rhc = (-0.00267 * t ** 3 + 0.160 * t ** 2 - 3.13 * t + 100.0) if t < 20 else 80.0
    return max(80.0, min(100.0, rhc))


def weeks_to_mold(temp_c: float, rh_pct: float) -> float | None:
    """Viitanen critical time (weeks) for first mould on a sensitive surface; None outside the growth window."""
    if temp_c <= 0.1 or temp_c > 50 or rh_pct < 80 or rh_pct > 100:
        return None
    return math.exp(66.02 - 0.68 * math.log(temp_c) - 13.9 * math.log(rh_pct))


def mold_risk(temp_c: float | None, rh_pct: float | None) -> dict | None:
    """Mould risk for an air reading. None when temperature or humidity is missing."""
    if temp_c is None or rh_pct is None:
        return None
    rhc = rh_critical(temp_c)
    if rhc is None or rh_pct < rhc:
        return {"index": 0, "text": LEVEL_TEXT[0], "weeks": None,
                "rh_critical": None if rhc is None else round(rhc, 1), "severity": 0}
    severity = max(0.0, min(100.0, (rh_pct - rhc) / (100.0 - rhc) * 100.0)) if rhc < 100 else 100.0
    weeks = weeks_to_mold(temp_c, rh_pct)
    if weeks is None:
        level = 0
    elif weeks >= 8:
        level = 1
    elif weeks >= 4:
        level = 2
    else:
        level = 3
    return {"index": level, "text": LEVEL_TEXT[level], "weeks": None if weeks is None else round(weeks, 1),
            "rh_critical": round(rhc, 1), "severity": round(severity)}
