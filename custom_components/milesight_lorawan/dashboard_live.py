"""'Live' view for the ready-made dashboards: gauges, slider tiles and maps for the site's actual devices.

The bundled dashboards (resources/dashboards/*.yaml) find their devices with templates, which works anywhere
but only gives text and tables. Gauges, sliders and maps need real entity ids, so this module builds an extra
view from the devices that are set up – it is rebuilt when devices are added or change (unless the dashboard was
edited by hand). Pure Python: entity ids come from the `eid(platform, unique_id)` resolver."""
from __future__ import annotations

from typing import Any, Callable

from . import setpoints as _sp

Resolver = Callable[[str, str], "str | None"]


def _e(eid: Resolver, rt: Any, platform: str, key: str) -> str | None:
    return eid(platform, f"{rt.deveui}_{key}")


def _slider(entity: str, name: str | None = None) -> dict:
    card = {"type": "tile", "entity": entity, "features": [{"type": "numeric-input", "style": "slider"}]}
    if name:
        card["name"] = name
    return card


def _gauge(entity: str, name: str, lo: float, hi: float, segments: list[tuple[float, str]] | None = None,
           unit: str | None = None) -> dict:
    card: dict[str, Any] = {"type": "gauge", "entity": entity, "name": name, "min": lo, "max": hi, "needle": True}
    if segments:
        card["segments"] = [{"from": f, "color": c} for f, c in segments]
    if unit:
        card["unit"] = unit
    return card


RED, AMBER, GREEN, BLUE = "#db4437", "#ffa600", "#43a047", "#039be5"


def _setpoint_tiles(eid: Resolver, rt: Any, options: list[str]) -> list[dict]:
    out = []
    for o in options:
        if o in _sp.device_values(rt):
            e = _e(eid, rt, "number", _sp.key(o))
            if e:
                out.append(_slider(e))
    return out


def _stack(title: str, cards: list[dict]) -> dict | None:
    cards = [c for c in cards if c]
    if not cards:
        return None
    return {"type": "vertical-stack", "cards": [{"type": "heading", "heading": title}] + cards}


# ------------------------------------------------------------------ per dashboard
def farm_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    cards: list[dict] = []
    for rt in runtimes:
        if getattr(rt, "pivot", None) is None:
            continue
        tracker = _e(eid, rt, "device_tracker", "location")
        centre = _e(eid, rt, "sensor", "pivot_radius")
        ents = [e for e in ({"entity": tracker, "name": rt.entry.title} if tracker else None,
                            {"entity": centre, "name": "Centre"} if centre else None) if e]
        inner = []
        if ents:
            inner.append({"type": "map", "entities": ents, "hours_to_show": 12, "default_zoom": 16,
                          "aspect_ratio": "16:10"})
        prog = _e(eid, rt, "sensor", "pivot_progress")
        if prog:
            inner.append(_gauge(prog, "Round done", 0, 100, [(0, BLUE), (95, GREEN)]))
        rows = [e for e in (_e(eid, rt, "sensor", k) for k in ("pivot_status", "pivot_angle", "pivot_speed",
                                                               "pivot_finish_at")) if e]
        stalled = _e(eid, rt, "binary_sensor", "pivot_stalled")
        if stalled:
            rows.insert(0, stalled)
        if rows:
            inner.append({"type": "entities", "entities": rows})
        stop = _e(eid, rt, "button", "cmd_pivot_stop")
        if stop:
            inner.append({"type": "tile", "entity": stop, "name": "Pivot stopped (end round)",
                          "tap_action": {"action": "perform-action", "perform_action": "button.press",
                                         "target": {"entity_id": stop}}})
        inner += _setpoint_tiles(eid, rt, ["pivot_stall_min"])
        cards.append(_stack(f"Pivot – {rt.entry.title}", inner))
    for rt in runtimes:
        if getattr(rt, "pump", None) is None:
            continue
        cfg = rt.pump_cfg
        normal = rt.pump.normal(cfg) if hasattr(rt.pump, "normal") else None
        key = "current_total" if "ct3" in rt.model.features else "current"
        cur = _e(eid, rt, "sensor", key)
        inner = []
        if cur:
            if normal:
                dry, over = normal * cfg.dry_pct / 100, normal * cfg.overload_pct / 100
                inner.append(_gauge(cur, "Current", 0, round(normal * 1.6, 1),
                                    [(0, AMBER), (round(dry, 2), GREEN), (round(over, 2), RED)]))
            else:
                inner.append(_gauge(cur, "Current (learning normal)", 0, 50))
        starts = _e(eid, rt, "sensor", "pump_starts_last_hour")
        if starts:
            inner.append(_gauge(starts, "Starts last hour", 0, max(cfg.max_starts_hour * 2, 4),
                                [(0, GREEN), (cfg.max_starts_hour + 0.5, RED)]))
        rows = [e for e in (_e(eid, rt, "binary_sensor", k) for k in ("pump_dry_run", "pump_overload",
                                                                      "pump_short_cycling")) if e]
        rows += [e for e in (_e(eid, rt, "sensor", k) for k in ("pump_run_hours", "pump_energy_today",
                                                                "pump_m3_per_kwh")) if e]
        if rows:
            inner.append({"type": "entities", "entities": rows})
        inner += _setpoint_tiles(eid, rt, ["pump_normal_a", "pump_max_starts"])
        cards.append(_stack(f"Pump – {rt.entry.title}", inner))
    soil = []
    for rt in runtimes:
        if "soil" in getattr(rt, "families", ()):
            e = _e(eid, rt, "sensor", "moisture")
            if e:
                soil.append((rt, e))
    for hub in hubs:
        mgr = getattr(hub, "irrigation", None)
        if mgr is None or not mgr.enabled:
            continue
        hid = hub.entry.entry_id
        inner = []
        target = mgr.cfg.target
        for rt, e in soil:
            inner.append(_gauge(e, rt.entry.title, 0, 60, [(0, RED), (target * 0.8, AMBER), (target, GREEN)]))
        for k, plat in (("irr_advice", "sensor"), ("irr_rain", "binary_sensor"), ("irr_frost", "binary_sensor")):
            e = eid(plat, f"{hid}_{k}")
            if e:
                inner.append({"type": "tile", "entity": e})
        for o in _sp.HUB:
            e = eid("number", f"{hid}_{_sp.key(o)}")
            if e:
                inner.append(_slider(e))
        cards.append(_stack(f"Irrigation – {hub.entry.title}", inner))
    if soil and not any(getattr(getattr(h, "irrigation", None), "enabled", False) for h in hubs):
        cards.append(_stack("Soil moisture", [_gauge(e, rt.entry.title, 0, 60) for rt, e in soil]))
    return [c for c in cards if c]


def tank_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    cards = []
    for rt in runtimes:
        if getattr(rt, "tank", None) is None:
            continue
        low = rt.tank_cfg.low_pct or 0
        inner = []
        fill = _e(eid, rt, "sensor", "tank_fill")
        if fill:
            inner.append(_gauge(fill, "Fill", 0, 100, [(0, RED), (low, AMBER), (min(100, low * 2 or 40), GREEN)]))
        rows = [e for e in (_e(eid, rt, "sensor", k) for k in ("tank_volume", "tank_usage_per_day", "tank_days_left",
                                                               "tank_empty_at")) if e]
        if rows:
            inner.append({"type": "entities", "entities": rows})
        inner += _setpoint_tiles(eid, rt, ["tank_low_pct"])
        cards.append(_stack(rt.entry.title, inner))
    return [c for c in cards if c]


def cold_chain_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    cards = []
    for rt in runtimes:
        p = getattr(rt, "purpose", None)
        if p is None or p.group != "cold_chain":
            continue
        inner = []
        if getattr(rt, "tempw", None) is not None:
            temp_key = "temperature" if "temperature" in rt.raw or "temperature_1" not in rt.raw else "temperature_1"
            t = _e(eid, rt, "sensor", temp_key)
            lo, hi = rt.pcfg.get("temp_low"), rt.pcfg.get("temp_high")
            if t and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                inner.append(_gauge(t, "Temperature", lo - 10, hi + 10, [(lo - 10, BLUE), (lo, GREEN), (hi, RED)],
                                    unit="°C"))
            rows = [e for e in (_e(eid, rt, "binary_sensor", "temp_alarm"), _e(eid, rt, "sensor", "temp_out_today"),
                                _e(eid, rt, "sensor", "temp_excursions_today")) if e]
            if rows:
                inner.append({"type": "entities", "entities": rows})
        if "load_" in getattr(rt, "loads", {}):
            d = _e(eid, rt, "sensor", "load_duty_24h")
            if d:
                inner.append(_gauge(d, "Compressor duty 24 h", 0, 100, [(0, GREEN), (75, AMBER), (90, RED)]))
        door = _e(eid, rt, "binary_sensor", "door_active")
        if door and "contact" in getattr(rt, "_pfam", ()):
            inner.append({"type": "tile", "entity": door})
        inner += _setpoint_tiles(eid, rt, ["p_temp_low", "p_temp_high", "p_left_open_min"])
        cards.append(_stack(rt.entry.title, inner))
    return [c for c in cards if c]


def energy_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    cards = []
    for rt in runtimes:
        for prefix, (_tr, _cfg, key, ch) in (getattr(rt, "loads", None) or {}).items():
            if key in ("fridge", "freezer"):
                continue
            inner = []
            d = _e(eid, rt, "sensor", f"{prefix}duty_24h")
            if d:
                inner.append(_gauge(d, "Duty cycle 24 h", 0, 100, [(0, GREEN), (75, AMBER), (90, RED)]))
            rows = [e for e in (_e(eid, rt, "sensor", f"{prefix}run_today_h"),
                                _e(eid, rt, "binary_sensor", f"{prefix}after_hours"),
                                _e(eid, rt, "binary_sensor", f"{prefix}service_due")) if e]
            if rows:
                inner.append({"type": "entities", "entities": rows})
            title = rt.entry.title + (f" – channel {ch}" if ch else "")
            cards.append(_stack(title, inner))
        if getattr(rt, "_pkey", None) == "mains":
            inner = []
            imb = _e(eid, rt, "sensor", "phase_imbalance")
            if imb:
                inner.append(_gauge(imb, "Phase imbalance", 0, 60, [(0, GREEN), (15, AMBER), (25, RED)]))
            out = _e(eid, rt, "binary_sensor", "mains_outage")
            if out:
                inner.append({"type": "tile", "entity": out})
            cards.append(_stack(f"Mains – {rt.entry.title}", inner))
    return [c for c in cards if c]


BUILDERS = {"farm.yaml": farm_cards, "tanks_and_alerts.yaml": tank_cards, "cold_chain.yaml": cold_chain_cards,
            "energy.yaml": energy_cards}


def with_live_view(file: str, config: dict, eid: Resolver, runtimes: list, hubs: list) -> dict:
    """The bundled dashboard plus a first 'Live' view (only when there is something to show)."""
    builder = BUILDERS.get(file)
    if builder is None:
        return config
    cards = builder(eid, runtimes, hubs)
    if not cards:
        return config
    live = {"title": "Live", "path": "live", "icon": "mdi:gauge", "cards": cards}
    return {**config, "views": [live] + list(config.get("views") or [])}
