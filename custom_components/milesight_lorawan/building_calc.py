"""Building overview maths: averages, air quality, comfort, health score, alerts. Pure Python (unit-tested)."""
from __future__ import annotations

from typing import Any

DEFAULT_CO2_ALERT = 1200

# measure -> (name, unit, HA device class, precision)
AVERAGES = {
    "temperature": ("Average temperature", "°C", "temperature", 1),
    "humidity": ("Average humidity", "%", "humidity", 0),
    "co2": ("Average CO₂", "ppm", "carbon_dioxide", 0),
    "pm2_5": ("Average PM2.5", "μg/m³", "pm25", 0),
    "pm10": ("Average PM10", "μg/m³", "pm10", 0),
    "tvoc": ("Average TVOC", "μg/m³", "volatile_organic_compounds", 0),
    "hcho": ("Average formaldehyde", "mg/m³", None, 3),
    "pressure": ("Average pressure", "hPa", "atmospheric_pressure", 0),
}
AIR_LEVELS = ["Good", "Moderate", "Poor", "Unhealthy"]


def _band(v: float, good: float, zero: float) -> float:
    """100 up to `good`, falling linearly to 0 at `zero`."""
    if v <= good:
        return 100.0
    return max(0.0, 100 * (zero - v) / (zero - good))


def _level(v: float, limits: tuple[float, float, float]) -> int:
    return next((i for i, lim in enumerate(limits) if v <= lim), 3)


def air_quality(avg: dict[str, float], co2_alert: float = DEFAULT_CO2_ALERT) -> tuple[str | None, int | None]:
    """(Good / Moderate / Poor / Unhealthy, 0-100 score). Worst pollutant decides the level; the score blends
    the worst and the mean so one bad value pulls it down without zeroing it."""
    rules = {   # measure: (good / moderate / poor upper limits, score: fully good up to, zero at)
        "co2": ((800, co2_alert, 2000), (800, 2000)),
        "pm2_5": ((12, 35, 55), (12, 75)),
        "pm10": ((54, 154, 254), (54, 354)),
        "tvoc": ((300, 500, 1000), (300, 1500)),
        "hcho": ((0.08, 0.1, 0.3), (0.08, 0.5)),
    }
    levels, scores = [], []
    for k, (limits, (good, zero)) in rules.items():
        v = avg.get(k)
        if isinstance(v, (int, float)):
            levels.append(_level(v, limits))
            scores.append(_band(v, good, zero))
    if not levels:
        return None, None
    return AIR_LEVELS[max(levels)], round(0.5 * min(scores) + 0.5 * sum(scores) / len(scores))


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def compute_building(devices: list[dict[str, Any]], areas: dict[str, dict[str, Any]],
                     gateways: list[dict[str, Any]], co2_alert: float = DEFAULT_CO2_ALERT,
                     area_order: list[str] | None = None) -> dict[str, Any]:
    """devices: [{deveui, name, model, online, battery, battery_low, values{...}, units{key: unit},
    last_seen_text, command_failed}],
    areas: area_summary() output (+ occupancy share), gateways: [{name, online}]."""
    online = [d for d in devices if d.get("online")]
    avg: dict[str, float] = {}
    for k, (_, unit, _, prec) in AVERAGES.items():
        # only devices whose sensor for this key has the same unit (TVOC is an index on some models)
        xs = [d["values"][k] for d in online if isinstance(d["values"].get(k), (int, float))
              and not isinstance(d["values"].get(k), bool) and d.get("units", {}).get(k, unit) == unit]
        if xs:
            avg[k] = round(sum(xs) / len(xs), prec) if prec else round(sum(xs) / len(xs))
    air, air_score = air_quality(avg, co2_alert)

    names = [a for a in (area_order or []) if a in areas] or sorted(areas)
    comforts = [areas[a]["comfort"] for a in names if isinstance(areas[a].get("comfort"), (int, float))]
    comfort = round(_mean(comforts)) if comforts else None
    comfortable = sum(1 for c in comforts if c >= 80)

    total = len(devices) + len(gateways)
    healthy = sum(1 for d in devices if d.get("online") and not d.get("battery_low")) + \
        sum(1 for g in gateways if g.get("online"))
    systems = round(100 * healthy / total) if total else None

    parts = [(comfort, 0.4), (air_score, 0.4), (systems, 0.2)]
    have = [(v, w) for v, w in parts if v is not None]
    health = round(sum(v * w for v, w in have) / sum(w for _, w in have)) if have else None

    occ = [areas[a] for a in names if areas[a].get("occupied") is not None]
    people_known = [a["people"] for a in occ if isinstance(a.get("people"), (int, float))]
    people = sum(people_known) if people_known else None

    alerts: list[dict[str, Any]] = []
    for a in names:
        s = areas[a]
        if isinstance(s.get("co2"), (int, float)) and s["co2"] > co2_alert:
            alerts.append({"key": f"co2:{a}", "severity": "serious", "where": a,
                           "what": f"CO₂ {s['co2']:,.0f} ppm", "detail": f"Above {co2_alert:,.0f} ppm – ventilate"})
        if isinstance(s.get("humidity"), (int, float)) and not 25 <= s["humidity"] <= 60:
            alerts.append({"key": f"rh:{a}", "severity": "warning", "where": a,
                           "what": f"Humidity {s['humidity']:.0f} %",
                           "detail": "Above 60 %" if s["humidity"] > 60 else "Below 25 %"})
        if isinstance(s.get("temperature"), (int, float)) and not 18 <= s["temperature"] <= 27:
            alerts.append({"key": f"t:{a}", "severity": "warning", "where": a,
                           "what": f"Temperature {s['temperature']:.1f} °C", "detail": "Outside 18–27 °C"})
    for d in devices:
        if d.get("online") is False:
            alerts.append({"key": f"off:{d['deveui']}", "severity": "serious", "where": d["name"], "what": "Offline",
                           "detail": f"{d['model']} · last seen {d.get('last_seen_text') or 'never'}"})
        elif d.get("battery_low"):
            alerts.append({"key": f"bat:{d['deveui']}", "severity": "warning", "where": d["name"],
                           "what": f"Battery {d.get('battery')} %", "detail": f"{d['model']} · replace soon"})
        if d.get("command_failed"):
            alerts.append({"key": f"cmd:{d['deveui']}", "severity": "warning", "where": d["name"],
                           "what": "Command failed", "detail": d["command_failed"]})
    for g in gateways:
        if g.get("online") is False:
            alerts.append({"key": f"gw:{g['name']}", "severity": "serious", "where": g["name"],
                           "what": "Gateway offline", "detail": "No packets forwarded"})
    alerts.sort(key=lambda x: (x["severity"] != "serious", x["where"]))

    return {"health": health, "comfort": comfort, "comfortable_areas": comfortable, "areas_with_comfort": len(comforts),
            "air_quality": air, "air_score": air_score, "systems": systems, "people": people,
            "occupied_areas": sum(1 for a in occ if a.get("occupied")), "areas_with_occupancy": len(occ),
            "devices": len(devices), "devices_online": len(online), "averages": avg, "alerts": alerts,
            "areas": names}


