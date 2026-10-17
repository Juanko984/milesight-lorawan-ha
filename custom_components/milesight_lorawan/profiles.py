"""Settings profiles: copy one device's set-up to other devices of the same model. Pure Python (unit-tested).

A profile holds the device's options (limits, purpose, opening hours, meters, channel map …) and the settings
it was sent over the air (reporting interval, alarms …). Options that only make sense for one device – its pivot
centre, applied Modbus templates (their commands were sent to that controller), meter offset – are left out."""
from __future__ import annotations

from typing import Any

DEVICE_ONLY = ("pivot_centre", "pivot_lat", "pivot_lon", "channel_templates", "meter_offset", "model",
               "tank_probe_offset_mm", "pump_water_entity")
CHANNEL_KEYS = ("channel_map",)


def capture(model: str, options: dict[str, Any], meta: dict[str, Any], name: str, source: str, ts: float
            ) -> dict[str, Any]:
    opts = {k: v for k, v in options.items() if k not in DEVICE_ONLY}
    return {"name": name, "model": model, "options": opts, "config": dict(meta.get("config") or {}),
            "settings": dict(meta.get("settings") or {}), "source": source, "created": ts}


def merged_options(target: dict[str, Any], profile: dict[str, Any], channels: bool = True) -> dict[str, Any]:
    """The target's new options: the profile's, keeping the target's device-only options."""
    new = {k: v for k, v in target.items() if k in DEVICE_ONLY}
    for k, v in profile["options"].items():
        if not channels and k in CHANNEL_KEYS:
            if k in target:
                new[k] = target[k]
            continue
        new[k] = v
    if not channels:
        for k in CHANNEL_KEYS:
            if k in target:
                new[k] = target[k]
    return new


def over_the_air(profile: dict[str, Any], target_meta: dict[str, Any]) -> list[tuple[str, Any]]:
    """('config' | 'setting', name, value) steps to send so the target matches the profile; only differences."""
    steps: list[tuple[str, Any]] = []
    have_cfg = target_meta.get("config") or {}
    for name, value in (profile.get("config") or {}).items():
        if have_cfg.get(name) != value:
            steps.append(("config", (name, value)))
    have_set = target_meta.get("settings") or {}
    for name, value in (profile.get("settings") or {}).items():
        if have_set.get(name) != value:
            steps.append(("setting", (name, value)))
    return steps


def describe(profile: dict[str, Any]) -> str:
    n_opt = len(profile.get("options") or {})
    n_air = len(profile.get("config") or {}) + len(profile.get("settings") or {})
    return f"{profile['name']} ({profile['model']}, {n_opt} options, {n_air} device settings, from {profile['source']})"
