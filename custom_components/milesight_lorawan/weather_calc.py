"""Weather-station helpers for an Ecowitt WS90 read over a UC controller (RS485/Modbus template).

Pure Python (unit-tested, no Home Assistant imports): turns the raw channel readings — temperature, humidity,
wind, rain, pressure, UV, light — into the things the card shows: a compass point, a plain-language condition,
a UV-risk label, and a pressure trend / simple forecast. The "feels like" (heat index) is computed by the
runtime, which already has it."""
from __future__ import annotations

from typing import Any

DIRS16 = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def compass(deg: Any) -> str | None:
    """A 0–359° bearing → 16-point compass (258° → WSW)."""
    d = _num(deg)
    return None if d is None else DIRS16[int((d % 360) / 22.5 + 0.5) % 16]


def condition(rain_rate: Any, uvi: Any, light_lux: Any) -> str:
    """Plain-language sky condition. Rain wins; otherwise brightness (lux) during the day, UV as a fallback."""
    if (_num(rain_rate) or 0) > 0:
        return "Rain"
    lx = _num(light_lux)
    if lx is not None:
        if lx < 1:
            return "Clear"                 # night / dark
        if lx < 15000:
            return "Cloudy"
        if lx < 50000:
            return "Partly cloudy"
        return "Sunny"
    uv = _num(uvi)
    if uv is not None:
        return "Sunny" if uv >= 5 else "Fair"
    return "Fair"


def uv_risk(uvi: Any) -> tuple[str | None, str]:
    """(label, severity) for the WHO UV-index bands."""
    uv = _num(uvi)
    if uv is None:
        return (None, "unknown")
    if uv < 3:
        return ("Low", "ok")
    if uv < 6:
        return ("Moderate", "ok")
    if uv < 8:
        return ("High", "warning")
    if uv < 11:
        return ("Very high", "warning")
    return ("Extreme", "critical")


def pressure_trend(delta_3h: Any) -> tuple[str, str, str]:
    """(trend, forecast, severity) from the 3-hour pressure change in hPa (Zambretti-style thresholds)."""
    d = _num(delta_3h)
    if d is None:
        return ("steady", "—", "ok")
    if d <= -3:
        return ("falling fast", "stormy", "warning")
    if d <= -1:
        return ("falling", "change", "ok")
    if d >= 3:
        return ("rising fast", "improving", "ok")
    if d >= 1:
        return ("rising", "fair", "ok")
    return ("steady", "fair", "ok")


def wind_severity(gust: Any) -> str:
    """Colour cue for the gust, from the Beaufort scale in km/h: ≥ 62 gale (critical), ≥ 39 strong (warning)."""
    g = _num(gust)
    if g is None:
        return "ok"
    if g >= 62:
        return "critical"
    if g >= 39:
        return "warning"
    return "ok"
