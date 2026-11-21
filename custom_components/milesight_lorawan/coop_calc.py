"""Chicken-coop automation — a small rules engine that switches relays from the coop's sensor readings.

Pure Python (no Home Assistant imports), so the control decisions are unit-tested on their own. The Home
Assistant glue (coop_ha.py) reads the sensors, asks `evaluate` for the desired relay states each tick and
switches the relays only when a decision changes.

A rule is: a metric (temperature / humidity / CO₂ / ammonia / …) that is *above* or *below* a threshold, driving
one relay, with hysteresis (a separate on and off level so a relay never short-cycles) and an optional time
window. Several rules can drive the same relay — the relay is on when ANY of its rules is active (so one
extractor fan can run on heat OR CO₂ OR ammonia). A sensor that is missing or stale (no reading for a while)
makes its rule inactive, which is the safe default: a heater or fogger never runs against an unknown reading.
"""
from __future__ import annotations

from typing import Any

# metric key -> (label, unit, default direction, default on, default off). Direction 'above' = act when the
# reading rises (fans, flaps, foggers); 'below' = act when it falls (heater, lights, frost protection).
METRICS: dict[str, dict[str, Any]] = {
    "temperature": {"label": "Temperature", "unit": "°C"},
    "humidity":    {"label": "Humidity", "unit": "%"},
    "co2":         {"label": "CO₂", "unit": "ppm"},
    "nh3":         {"label": "Ammonia (NH₃)", "unit": "ppm"},
    "h2s":         {"label": "Hydrogen sulphide (H₂S)", "unit": "ppm"},
    "pm2_5":       {"label": "Dust (PM2.5)", "unit": "µg/m³"},
    "light":       {"label": "Light", "unit": "lx"},
}

# Ready-made rules, grounded in poultry-house guidance (ammonia < 25 ppm, CO₂ < ~3000 ppm, RH 50–70 %, layer
# comfort ~18–24 °C, frost protection a few °C). `relay_role` is a hint for the card's relay placeholder only.
PRESETS: tuple[dict[str, Any], ...] = (
    {"preset": "lights", "name": "Lights by daylight", "metric": "light", "mode": "below",
     "on_value": 15, "off_value": 40, "start_hour": 5, "end_hour": 21, "icon": "mdi:lightbulb-on-outline"},
    {"preset": "heater", "name": "Heater", "metric": "temperature", "mode": "below",
     "on_value": 8, "off_value": 12, "icon": "mdi:radiator"},
    {"preset": "frost", "name": "Water-line frost protection", "metric": "temperature", "mode": "below",
     "on_value": 2, "off_value": 4, "icon": "mdi:snowflake-alert"},
    {"preset": "fan_heat", "name": "Extractor fan — heat", "metric": "temperature", "mode": "above",
     "on_value": 28, "off_value": 26, "icon": "mdi:fan"},
    {"preset": "fan_co2", "name": "Extractor fan — CO₂", "metric": "co2", "mode": "above",
     "on_value": 3000, "off_value": 2500, "icon": "mdi:fan-alert"},
    {"preset": "fan_nh3", "name": "Extractor fan — ammonia", "metric": "nh3", "mode": "above",
     "on_value": 20, "off_value": 12, "icon": "mdi:fan-alert"},
    {"preset": "fan_humidity", "name": "Extractor fan — humidity", "metric": "humidity", "mode": "above",
     "on_value": 70, "off_value": 60, "icon": "mdi:fan"},
    {"preset": "flap", "name": "Fresh-air flap", "metric": "temperature", "mode": "above",
     "on_value": 26, "off_value": 23, "icon": "mdi:window-shutter"},
    {"preset": "foggers", "name": "Foggers / cooling", "metric": "temperature", "mode": "above",
     "on_value": 30, "off_value": 28, "icon": "mdi:sprinkler-variant"},
    {"preset": "circulation", "name": "Circulation fan", "metric": "temperature", "mode": "above",
     "on_value": 24, "off_value": 22, "icon": "mdi:fan"},
    {"preset": "dust", "name": "Extractor fan — dust", "metric": "pm2_5", "mode": "above",
     "on_value": 150, "off_value": 100, "icon": "mdi:blur"},
)
PRESET_BY_KEY = {p["preset"]: p for p in PRESETS}


def _num(v: Any, d: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def in_window(hour: float, start: float, end: float) -> bool:
    """Is `hour` (0–24, local) inside the window [start, end)? start == end means 'always'. A window that wraps
    past midnight (start > end, e.g. 20:00–06:00) is handled."""
    start, end = float(start) % 24, float(end) % 24
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def normalise_rule(r: dict[str, Any], i: int = 0) -> dict[str, Any]:
    metric = r.get("metric") if r.get("metric") in METRICS else "temperature"
    mode = "below" if r.get("mode") == "below" else "above"
    out = {
        "id": str(r.get("id") or f"r{i}"),
        "name": (str(r.get("name") or "").strip() or METRICS[metric]["label"])[:48],
        "metric": metric,
        "mode": mode,
        "sensor": r.get("sensor") or None,
        "relay": r.get("relay") or None,
        "on_value": _num(r.get("on_value"), 0.0),
        "off_value": _num(r.get("off_value"), 0.0),
        "enabled": bool(r.get("enabled", True)),
        "icon": r.get("icon") or None,
    }
    if r.get("start_hour") is not None or r.get("end_hour") is not None:
        out["start_hour"] = _num(r.get("start_hour"), 0.0)
        out["end_hour"] = _num(r.get("end_hour"), 24.0)
    return out


def normalise(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Coop config → a clean rule list. Migrates the old {lights, heater} shape (v0.158) into two rules."""
    c = dict(cfg or {})
    rules = c.get("rules")
    if rules is None and ("lights" in c or "heater" in c):      # migrate the first lights/heater shape
        rules = []
        lg, ht = c.get("lights") or {}, c.get("heater") or {}
        if lg.get("relay") or lg.get("lux_entity"):
            rules.append({"id": "lights", "name": "Lights by daylight", "metric": "light", "mode": "below",
                          "sensor": lg.get("lux_entity"), "relay": lg.get("relay"),
                          "on_value": lg.get("on_lux", 15), "off_value": lg.get("off_lux", 40),
                          "start_hour": lg.get("start_hour", 5), "end_hour": lg.get("end_hour", 21),
                          "enabled": lg.get("enabled", False)})
        if ht.get("relay") or ht.get("temp_entity"):
            rules.append({"id": "heater", "name": "Heater", "metric": "temperature", "mode": "below",
                          "sensor": ht.get("temp_entity"), "relay": ht.get("relay"),
                          "on_value": ht.get("on_temp", 8), "off_value": ht.get("off_temp", 12),
                          "enabled": ht.get("enabled", False)})
    return {"rules": [normalise_rule(r, i) for i, r in enumerate(rules or [])]}


def rule_active(value: float | None, mode: str, on_value: float, off_value: float, prev_active: bool,
                fresh: bool, within_window: bool = True) -> bool:
    """One rule's on/off state with hysteresis. Outside its window, or with no fresh reading, it is inactive —
    the safe default (nothing runs against an unknown or out-of-window reading)."""
    if not within_window or not fresh or value is None:
        return False
    if mode == "below":
        if not prev_active and value <= on_value:
            return True
        if prev_active and value >= off_value:
            return False
    else:                                            # above
        if not prev_active and value >= on_value:
            return True
        if prev_active and value <= off_value:
            return False
    return prev_active


def _reason(rule: dict[str, Any], value: float | None, fresh: bool, within: bool, active: bool) -> str:
    m = METRICS[rule["metric"]]
    unit = m["unit"]
    if not within:
        return "outside window"
    if not fresh or value is None:
        return "no reading — off (safety)"
    val = f"{round(value, 1) if rule['metric'] in ('temperature',) else round(value)} {unit}".strip()
    if active:
        cmp = "≥" if rule["mode"] == "above" else "≤"
        return f"{val} {cmp} {round(rule['on_value'], 1)}"
    return val


def evaluate(cfg: dict[str, Any], *, hour: float, readings: dict[str, tuple[float | None, bool]],
             prev_active: dict[str, bool], relay_on: dict[str, bool]) -> dict[str, Any]:
    """One control pass.

    readings: {metric: (value, fresh)} for every metric a rule needs. A rule with no sensor configured reads its
    metric from this map; a rule may also name its own sensor, which the HA layer resolves into `per_sensor`.
    prev_active: {rule_id: bool} last tick (for hysteresis). relay_on: {relay: bool} current relay states.

    Returns {rules: [...with active/value/reason...], relays: {relay: want_on}, active: {rule_id: bool}}.
    """
    rules = normalise(cfg)["rules"]
    per_sensor: dict[str, tuple[float | None, bool]] = cfg.get("_per_sensor") or {}
    out_rules: list[dict[str, Any]] = []
    want: dict[str, bool] = {}
    active_now: dict[str, bool] = {}

    for r in rules:
        src = per_sensor.get(r["sensor"]) if r.get("sensor") in per_sensor else readings.get(r["metric"], (None, False))
        value, fresh = src if src is not None else (None, False)
        within = True
        if "start_hour" in r:
            within = in_window(hour, r["start_hour"], r["end_hour"])
        prev = bool(prev_active.get(r["id"], relay_on.get(r["relay"] or "", False)))
        act = r["enabled"] and bool(r["relay"]) and rule_active(value, r["mode"], r["on_value"], r["off_value"],
                                                                prev, fresh, within)
        active_now[r["id"]] = act
        if r["enabled"] and r["relay"]:
            want[r["relay"]] = want.get(r["relay"], False) or act
        out_rules.append({**r, "active": act, "value": None if value is None else round(value, 2),
                          "fresh": fresh, "within_window": within,
                          "reason": _reason(r, value, fresh, within, act)})

    return {"rules": out_rules, "relays": want, "active": active_now}
