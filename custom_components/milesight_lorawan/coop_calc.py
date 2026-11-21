"""Chicken-coop automation logic — lights by daylight and heater by temperature.

Pure Python (no Home Assistant imports), so the control decisions are unit-tested on their own. The Home
Assistant glue (coop_ha.py) reads the light / temperature sensors, calls these functions each tick and switches
the configured relays only when the decision changes. Both use hysteresis so a relay never short-cycles, and the
heater has a safety cut-out: a missing / stale probe reading turns it off.
"""
from __future__ import annotations

from typing import Any


def in_window(hour: float, start: float, end: float) -> bool:
    """Is `hour` (0–24, local) inside the lighting window [start, end)? start == end means 'always on'.
    A window that wraps past midnight (start > end, e.g. 04:00–22:00 is normal, 20:00–06:00 wraps) is handled."""
    start, end = float(start) % 24, float(end) % 24
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def lights_decision(lux: float | None, on_lux: float, off_lux: float, within_window: bool,
                    currently_on: bool) -> bool:
    """Supplemental coop lighting to hold a steady day length for laying. Within the lighting window the lights
    come on when it is too dark (lux at/below on_lux) and go off once it is bright enough (lux at/above off_lux);
    the gap between the two levels is the hysteresis band. Outside the window the lights are always off, so the
    birds still get a real dark period. A missing lux reading holds the current state (no flapping on a dropout)."""
    if not within_window:
        return False
    if lux is None:
        return currently_on
    if not currently_on and lux <= on_lux:
        return True
    if currently_on and lux >= off_lux:
        return False
    return currently_on


def heater_decision(temp: float | None, on_temp: float, off_temp: float, currently_on: bool,
                    probe_ok: bool = True) -> bool:
    """Coop heater by temperature with hysteresis: on at/below on_temp, off at/above off_temp. Safety first —
    a dropped-out probe (probe_ok False) or a missing reading turns the heater off, so it can never be left
    running against an unknown temperature."""
    if not probe_ok or temp is None:
        return False
    if not currently_on and temp <= on_temp:
        return True
    if currently_on and temp >= off_temp:
        return False
    return currently_on


def normalise(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Fill a coop-controller config with safe defaults and coerce the numeric fields."""
    c = dict(cfg or {})
    lights = dict(c.get("lights") or {})
    heater = dict(c.get("heater") or {})

    def _num(v, d):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d
    return {
        "lights": {
            "enabled": bool(lights.get("enabled")),
            "relay": lights.get("relay") or None,
            "lux_entity": lights.get("lux_entity") or None,
            "on_lux": _num(lights.get("on_lux"), 15.0),
            "off_lux": _num(lights.get("off_lux"), 40.0),
            "start_hour": _num(lights.get("start_hour"), 5.0),
            "end_hour": _num(lights.get("end_hour"), 21.0),
        },
        "heater": {
            "enabled": bool(heater.get("enabled")),
            "relay": heater.get("relay") or None,
            "temp_entity": heater.get("temp_entity") or None,
            "on_temp": _num(heater.get("on_temp"), 8.0),
            "off_temp": _num(heater.get("off_temp"), 12.0),
        },
    }


def evaluate(cfg: dict[str, Any], *, hour: float, lux: float | None, temp: float | None,
             lights_on: bool, heater_on: bool, lux_ok: bool = True, probe_ok: bool = True) -> dict[str, Any]:
    """One control pass → the desired relay states plus a short reason for each, for the status card.

    `lux_ok` / `probe_ok` say whether the sensor reading is fresh; a stale lux holds the lights, a stale probe
    turns the heater off. A side without a relay or with `enabled` false is left untouched (want = None)."""
    c = normalise(cfg)
    L, H = c["lights"], c["heater"]
    out: dict[str, Any] = {"lights": {"want": None, "reason": "off"}, "heater": {"want": None, "reason": "off"}}

    if L["enabled"] and L["relay"]:
        within = in_window(hour, L["start_hour"], L["end_hour"])
        want = lights_decision(lux if lux_ok else None, L["on_lux"], L["off_lux"], within, lights_on)
        if not within:
            reason = "outside lighting window"
        elif not lux_ok or lux is None:
            reason = "no light reading — holding"
        elif want:
            reason = f"dark ({round(lux)} lx ≤ {round(L['on_lux'])})"
        else:
            reason = f"bright enough ({round(lux)} lx)"
        out["lights"] = {"want": want, "reason": reason, "within_window": within}

    if H["enabled"] and H["relay"]:
        want = heater_decision(temp if probe_ok else None, H["on_temp"], H["off_temp"], heater_on, probe_ok)
        if not probe_ok or temp is None:
            reason = "no probe reading — heater off (safety)"
        elif want:
            reason = f"cold ({round(temp, 1)} °C ≤ {round(H['on_temp'], 1)})"
        else:
            reason = f"warm enough ({round(temp, 1)} °C)"
        out["heater"] = {"want": want, "reason": reason}

    return out
