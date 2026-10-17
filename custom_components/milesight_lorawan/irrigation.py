"""Forecast-aware irrigation advice and frost warnings. Pure Python (unit-tested); hub-side wiring in
irrigation_ha.py. Forecast items are Home Assistant weather forecasts: {datetime, temperature, templow,
precipitation, precipitation_probability, …}."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class IrrigationConfig:
    weather: str | None = None          # weather.* entity
    soil: tuple[str, ...] = ()          # soil moisture sensors (%)
    target: float = 30                  # irrigate below this soil moisture (%)
    rain_mm: float = 5                  # skip when at least this much rain is forecast …
    rain_hours: int = 24                # … within this many hours
    rain_prob: float = 60               # … with at least this probability (when the forecast gives one)
    base_minutes: float = 60            # irrigation time for a fully dry soil
    frost_c: float = 2                  # frost warning at or below this forecast temperature
    warn_from: int = 15                 # warn from this hour the evening before


def irrigation_config(opts: dict[str, Any]) -> IrrigationConfig:
    def f(key: str, default: float) -> float:
        try:
            v = opts.get(key, default)
            return float(default if v in (None, "") else v)
        except (TypeError, ValueError):
            return float(default)
    return IrrigationConfig(weather=opts.get("irr_weather") or None, soil=tuple(opts.get("irr_soil") or ()),
                            target=f("irr_target", 30), rain_mm=f("irr_rain_mm", 5),
                            rain_hours=int(f("irr_rain_hours", 24)), rain_prob=f("irr_rain_prob", 60),
                            base_minutes=f("irr_base_minutes", 60), frost_c=f("irr_frost_c", 2))


def _dt(v: Any, now: datetime | None = None) -> datetime | None:
    """Forecast time in the same time zone as `now` (forecasts are often in UTC; naive = local)."""
    if not isinstance(v, datetime):
        try:
            v = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
    if now is not None and now.tzinfo is not None:
        v = v.replace(tzinfo=now.tzinfo) if v.tzinfo is None else v.astimezone(now.tzinfo)
    return v


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def rain_ahead(forecast: list[dict[str, Any]], now: datetime, hours: int, daily: bool = False) -> dict[str, Any]:
    """Expected rain (mm) and the highest probability in the next `hours`. Daily forecasts: the days that start
    within the window count in full (today's remaining share for today)."""
    end = now + timedelta(hours=hours)
    mm, prob, n = 0.0, None, 0
    for f in forecast or []:
        t = _dt(f.get("datetime"), now)
        if t is None:
            continue
        span = timedelta(days=1) if daily else timedelta(hours=1)
        if t + span <= now or t >= end:
            continue
        p = _num(f.get("precipitation"))
        if p is not None:
            share = 1.0
            if daily and t < now:                        # today: only the part that is still to come
                share = max(0.0, (t + span - now) / span)
            mm += p * share
        q = _num(f.get("precipitation_probability"))
        if q is not None:
            prob = q if prob is None else max(prob, q)
        n += 1
    return {"mm": round(mm, 1), "probability": prob, "periods": n}


def frost_tonight(forecast: list[dict[str, Any]], now: datetime, threshold: float, warn_from: int = 15,
                  daily: bool = False) -> dict[str, Any]:
    """Lowest forecast temperature from now until 10:00 the next morning (hourly), or that morning's templow
    (daily).
    'active' only from warn_from (afternoon) until 10:00, i.e. the evening before and during the night."""
    morning = (now + timedelta(days=1 if now.hour >= 10 else 0)).replace(hour=10, minute=0, second=0, microsecond=0)
    low, at = None, None
    for f in forecast or []:
        t = _dt(f.get("datetime"), now)
        if t is None:
            continue
        if daily:                                         # a day's low is the early morning of that day
            if t.date() != morning.date():
                continue
            v = _num(f.get("templow"))
        else:
            if t < now - timedelta(hours=1) or t > morning:
                continue
            v = _num(f.get("temperature"))
        if v is not None and (low is None or v < low):
            low, at = v, t
    in_window = now.hour >= warn_from or now.hour < 10
    frost = low is not None and low <= threshold
    return {"active": bool(frost and in_window), "expected": frost, "low": low,
            "at": at.isoformat() if at else None}


def advice(moisture: list[float], rain: dict[str, Any], cfg: IrrigationConfig,
           fallen: float | None = None) -> dict[str, Any]:
    """'irrigate' / 'skip' with the reason and suggested minutes. fallen: rain measured in the last 24 h (rain
    gauge), mm."""
    soil = round(sum(moisture) / len(moisture), 1) if moisture else None
    if fallen is not None and cfg.rain_mm and fallen >= cfg.rain_mm:
        return {"advice": "skip", "reason": f"{fallen:g} mm rain fell in the last 24 h", "minutes": 0,
                "soil_moisture": soil, "rain_expected": False, "rain_fallen": fallen}
    if fallen:                                            # some measured rain counts like forecast rain
        rain = {**rain, "mm": round(rain["mm"] + fallen, 1)}
    rain_expected = rain["mm"] >= cfg.rain_mm and (rain["probability"] is None or rain["probability"] >= cfg.rain_prob)
    if rain_expected:
        return {"advice": "skip", "reason": f"{rain['mm']:g} mm rain forecast in {cfg.rain_hours} h",
                "minutes": 0, "soil_moisture": soil, "rain_expected": True}
    if soil is not None and soil >= cfg.target:
        return {"advice": "skip", "reason": f"soil moist enough ({soil:g} % ≥ {cfg.target:g} %)", "minutes": 0,
                "soil_moisture": soil, "rain_expected": False}
    if soil is None:
        return {"advice": "irrigate", "reason": "no rain forecast (no soil moisture sensor)",
                "minutes": round(cfg.base_minutes), "soil_moisture": None, "rain_expected": False}
    deficit = max(0.0, (cfg.target - soil) / cfg.target)
    # some rain on the way, below the skip threshold, counts for part of the need
    credit = min(1.0, rain["mm"] / cfg.rain_mm) * 0.5 if cfg.rain_mm else 0.0
    minutes = round(cfg.base_minutes * deficit * (1 - credit))
    if minutes < 5:
        return {"advice": "skip", "reason": f"soil nearly at target ({soil:g} %)", "minutes": 0,
                "soil_moisture": soil, "rain_expected": False}
    return {"advice": "irrigate", "reason": f"soil {soil:g} % (target {cfg.target:g} %)"
                                            + (f", {rain['mm']:g} mm rain expected" if rain["mm"] else ""),
            "minutes": minutes, "soil_moisture": soil, "rain_expected": False}
