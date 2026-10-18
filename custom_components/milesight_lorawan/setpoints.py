"""Setpoints: alarm limits and targets that live in a device's (or the gateway's) options, offered as number
entities (a slider, or a typed-in box for precise values) so dashboards can change them directly. Changing one updates the options (the device
reloads with the new limit). Pure Python (unit-tested)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Setpoint:
    option: str            # options key
    name: str
    unit: str | None
    min: float
    max: float
    step: float
    icon: str
    box: bool = False      # typed in (precise values) instead of a slider
    config: bool = False   # shown under Configuration on the device page


DEVICE = {s.option: s for s in (
    Setpoint("tank_low_pct", "Tank low alarm", "%", 0, 90, 1, "mdi:storage-tank-outline"),
    Setpoint("pump_normal_a", "Pump normal current", "A", 0, 500, 0.01, "mdi:current-ac", box=True, config=True),
    Setpoint("pump_max_starts", "Pump max starts per hour", "starts", 1, 60, 1, "mdi:restart-alert", box=True,
             config=True),
    Setpoint("mains_voltage", "Voltage", "V", 0, 1000, 1, "mdi:flash-triangle-outline", box=True, config=True),
    Setpoint("power_factor", "Power factor", None, 0.1, 1, 0.01, "mdi:angle-acute", box=True, config=True),
    Setpoint("run_threshold_a", "Running above", "A", 0, 5000, 0.01, "mdi:current-ac", box=True, config=True),
    Setpoint("pivot_stall_min", "Pivot stall alarm after", "min", 5, 240, 5, "mdi:timer-alert-outline"),
    Setpoint("p_temp_low", "Temperature alarm below", "°C", -40, 90, 0.5, "mdi:thermometer-chevron-down"),
    Setpoint("p_temp_high", "Temperature alarm above", "°C", -40, 90, 0.5, "mdi:thermometer-chevron-up"),
    Setpoint("p_left_open_min", "Left-open alarm after", "min", 1, 240, 1, "mdi:door-open"),
)}
HUB = {s.option: s for s in (
    Setpoint("irr_target", "Irrigation target soil moisture", "%", 5, 80, 1, "mdi:water-percent"),
    Setpoint("irr_base_minutes", "Irrigation time for dry soil", "min", 5, 240, 5, "mdi:timer-sand"),
    Setpoint("irr_frost_c", "Frost warning at", "°C", -10, 10, 0.5, "mdi:snowflake-thermometer"),
)}


def key(option: str) -> str:
    """Entity key of a setpoint."""
    return f"sp_{option}"


def clamp(sp: Setpoint, value: float) -> float:
    v = min(sp.max, max(sp.min, float(value)))
    v = round(round((v - sp.min) / sp.step) * sp.step + sp.min, 3)
    return int(v) if float(sp.step).is_integer() and float(v).is_integer() else v


def extra_options(option: str) -> dict[str, Any]:
    """Options written together with a setpoint."""
    return {"run_threshold_set": True} if option == "run_threshold_a" else {}


def device_values(rt: Any) -> dict[str, float]:
    """The setpoints a device runtime offers, with their current (effective) values."""
    out: dict[str, float] = {}
    if getattr(rt, "tank", None) is not None and rt.tank_cfg is not None:
        out["tank_low_pct"] = rt.tank_cfg.low_pct
    model = getattr(rt, "model", None)
    if "load" in getattr(model, "features", ()):
        from .pump import power_factor, run_threshold_setting
        opts = dict(rt.entry.options)
        try:
            out["mains_voltage"] = float(opts.get("mains_voltage") or 0)
        except (TypeError, ValueError):
            out["mains_voltage"] = 0.0
        out["power_factor"] = power_factor(opts)
        out["run_threshold_a"] = run_threshold_setting(opts)
    if getattr(rt, "pump", None) is not None and rt.pump_cfg is not None:
        out["pump_normal_a"] = rt.pump_cfg.normal_a
        out["pump_max_starts"] = rt.pump_cfg.max_starts_hour
    if getattr(rt, "pivot", None) is not None and rt.pivot_cfg is not None:
        out["pivot_stall_min"] = rt.pivot_cfg.stall_min
    pcfg = getattr(rt, "pcfg", None) or {}
    if getattr(rt, "tempw", None) is not None:
        for name in ("temp_low", "temp_high"):
            if isinstance(pcfg.get(name), (int, float)):
                out[f"p_{name}"] = pcfg[name]
    if "contact" in getattr(rt, "_pfam", ()) and isinstance(pcfg.get("left_open_min"), (int, float)):
        out["p_left_open_min"] = pcfg["left_open_min"]
    return out


def hub_values(cfg: Any) -> dict[str, float]:
    """Irrigation setpoints of a gateway (IrrigationConfig)."""
    return {"irr_target": cfg.target, "irr_base_minutes": cfg.base_minutes, "irr_frost_c": cfg.frost_c}
