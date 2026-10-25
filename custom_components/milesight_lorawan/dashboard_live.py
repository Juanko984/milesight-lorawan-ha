"""'Live' views for the ready-made dashboards and the site landing page: gauges, slider tiles, history graphs and
maps for the site's actual devices, laid out as a Home Assistant *sections* view.

The bundled dashboards (resources/dashboards/*.yaml) find their devices with templates, which works anywhere but
only gives text and tables. Gauges, sliders, graphs and maps need real entity ids, so this module builds a view
from the devices that are set up – rebuilt when devices are added or change (unless the dashboard was edited by
hand). Pure Python: entity ids come from the `eid(platform, unique_id)` resolver; every builder returns a list
of grid sections."""
from __future__ import annotations

import json
from typing import Any, Callable

from . import setpoints as _sp

Resolver = Callable[[str, str], "str | None"]
RED, AMBER, GREEN, BLUE, GREY = "#db4437", "#ffa600", "#43a047", "#039be5", "#9e9e9e"
_CLASSIC = False


def set_classic(value: bool) -> None:
    """Use built-in `gauge` cards instead of the custom milesight gauge (user fallback)."""
    global _CLASSIC
    _CLASSIC = bool(value)
FULL, HALF, THIRD = 12, 6, 4


def _e(eid: Resolver, rt: Any, platform: str, key: str) -> str | None:
    return eid(platform, f"{rt.deveui}_{key}")


def _g(card: dict | None, cols: int | str = HALF, rows: int | None = None) -> dict | None:
    if card is None:
        return None
    opts: dict[str, Any] = {"columns": cols}
    if rows:
        opts["rows"] = rows
    return {**card, "grid_options": opts}


def _slider(entity: str, name: str | None = None, style: str = "slider") -> dict:
    card = {"type": "tile", "entity": entity, "features": [{"type": "numeric-input", "style": style}]}
    if name:
        card["name"] = name
    return _g(card, FULL)


def _tile(entity: str | None, name: str | None = None, icon: str | None = None, cols: int = HALF, **kw) -> dict | None:
    if not entity:
        return None
    card: dict[str, Any] = {"type": "tile", "entity": entity, **kw}
    if name:
        card["name"] = name
    if icon:
        card["icon"] = icon
    return _g(card, cols)


def _gauge(entity: str | None, name: str, lo: float, hi: float, segments: list[tuple[float, str]] | None = None,
           unit: str | None = None, cols: int = HALF) -> dict | None:
    if not entity:
        return None
    if _CLASSIC:
        card = {"type": "gauge", "entity": entity, "name": name, "min": lo, "max": hi, "needle": True}
    else:
        card = {"type": "custom:milesight-gauge-card", "entity": entity, "name": name,
                "min": lo, "max": hi, "shape": "arc", "switchable": False, "ticks": True, "needle": True}
    if segments:
        card["segments"] = [{"from": f, "color": c} for f, c in segments]
    if unit:
        card["unit"] = unit
    return _g(safe_gauge(card), cols)


def safe_gauge(card: dict) -> dict:
    """A gauge only while its sensor has a number; until then a tile ('Unknown') instead of the gauge card's
    'Entity is non-numeric' warning (no data yet, device offline, value not reported by this model)."""
    e = card["entity"]
    bad = ["unknown", "unavailable", ""]
    return {"type": "vertical-stack", "cards": [
        {"type": "conditional", "conditions": [{"condition": "state", "entity": e, "state_not": bad}], "card": card},
        {"type": "conditional", "conditions": [{"condition": "state", "entity": e, "state": bad}],
         "card": {"type": "tile", "entity": e, "name": card.get("name"), "vertical": True}}]}


def gauge_of(card: dict | None) -> dict | None:
    """The gauge inside a safe_gauge (or the card itself when it is a gauge)."""
    if not card:
        return None
    _GAUGES = ("gauge", "custom:milesight-gauge-card")
    if card.get("type") in _GAUGES:
        return card
    if card.get("type") == "vertical-stack":
        inner = (card.get("cards") or [{}])[0].get("card") or {}
        return inner if inner.get("type") in _GAUGES else None
    return None


def _history(entities: list, title: str | None = None, hours: int = 24) -> dict | None:
    ents = [e for e in entities if e]
    if not ents:
        return None
    card: dict[str, Any] = {"type": "history-graph", "hours_to_show": hours, "entities": ents}
    if title:
        card["title"] = title
    return _g(card, FULL)


def _entities(rows: list) -> dict | None:
    rows = [r for r in rows if r]
    return _g({"type": "entities", "entities": rows}, FULL) if rows else None


def _md(content: str, title: str | None = None) -> dict:
    card: dict[str, Any] = {"type": "markdown", "content": content}
    if title:
        card["title"] = title
    return _g(card, FULL)


def _setpoint_tiles(eid: Resolver, rt: Any, options: list[str]) -> list[dict]:
    out = []
    for o in options:
        if o in _sp.device_values(rt):
            e = _e(eid, rt, "number", _sp.key(o))
            if e:
                out.append(_slider(e, style="buttons" if _sp.DEVICE[o].box else "slider"))
    return out


def _section(title: str, cards: list, icon: str | None = None, span: int | None = None) -> dict | None:
    cards = [c for c in cards if c]
    if not cards:
        return None
    head: dict[str, Any] = {"type": "heading", "heading": title}
    if icon:
        head["icon"] = icon
    sec: dict[str, Any] = {"type": "grid", "cards": [head] + cards}
    if span:
        sec["column_span"] = span
    return sec


def _nav(title: str, path: str, icon: str) -> dict:
    return _g({"type": "button", "name": title, "icon": icon, "show_state": False,
               "tap_action": {"action": "navigate", "navigation_path": path}}, THIRD, 2)


def _header(title: str, icon: str = "mdi:gauge", subtitle: str | None = None, span: int = 4) -> dict:
    """A full-width page-header section, so every generated Live view has the same masthead as the rest."""
    card: dict[str, Any] = {"type": "custom:milesight-page-header", "title": title, "icon": icon,
                            "grid_options": {"columns": "full"}}
    if subtitle:
        card["subtitle"] = subtitle
    return {"type": "grid", "column_span": span, "cards": [card]}


# ------------------------------------------------------------------ farm
def pivot_sections(eid: Resolver, runtimes: list) -> list[dict]:
    out = []
    for rt in runtimes:
        if getattr(rt, "pivot", None) is None:
            continue
        tracker = _e(eid, rt, "device_tracker", "location")
        centre = _e(eid, rt, "sensor", "pivot_radius")
        ents = [e for e in ({"entity": tracker, "name": rt.entry.title} if tracker else None,
                            {"entity": centre, "name": "Centre"} if centre else None) if e]
        stop = _e(eid, rt, "button", "cmd_pivot_stop")
        out.append(_section(f"Pivot – {rt.entry.title}", [
            _g({"type": "map", "entities": ents, "hours_to_show": 12, "default_zoom": 16, "aspect_ratio": "16:9",
                "theme_mode": "auto"}, FULL) if ents else None,
            _gauge(_e(eid, rt, "sensor", "pivot_progress"), "Round done", 0, 100, [(0, BLUE), (95, GREEN)]),
            _tile(_e(eid, rt, "binary_sensor", "pivot_stalled"), "Stalled", "mdi:alert-octagon"),
            _tile(_e(eid, rt, "sensor", "pivot_status"), "Status"),
            _tile(_e(eid, rt, "sensor", "pivot_angle"), "Angle", "mdi:rotate-right"),
            _tile(_e(eid, rt, "sensor", "pivot_speed"), "Speed"),
            _tile(_e(eid, rt, "sensor", "pivot_finish_at"), "Finishes at"),
            _tile(stop, "Pivot stopped (end round)", "mdi:stop-circle-outline", FULL,
                  tap_action={"action": "perform-action", "perform_action": "button.press",
                              "target": {"entity_id": stop}}) if stop else None,
            *_setpoint_tiles(eid, rt, ["pivot_stall_min"]),
        ], "mdi:sprinkler-variant"))
    return [s for s in out if s]


def pump_sections(eid: Resolver, runtimes: list) -> list[dict]:
    out = []
    for rt in runtimes:
        if getattr(rt, "pump", None) is None:
            continue
        cfg = rt.pump_cfg
        normal = rt.pump.normal(cfg) if hasattr(rt.pump, "normal") else None
        cur = _e(eid, rt, "sensor", "current_total" if "ct3" in rt.model.features else "current")
        if normal:
            dry, over = normal * cfg.dry_pct / 100, normal * cfg.overload_pct / 100
            g = _gauge(cur, "Current", 0, round(normal * 1.6, 1), [(0, AMBER), (round(dry, 2), GREEN),
                                                                  (round(over, 2), RED)])
        else:
            g = _gauge(cur, "Current (learning normal)", 0, 50)
        out.append(_section(f"Pump – {rt.entry.title}", [
            g,
            _gauge(_e(eid, rt, "sensor", "pump_starts_last_hour"), "Starts last hour", 0,
                   max(cfg.max_starts_hour * 2, 4), [(0, GREEN), (cfg.max_starts_hour + 0.5, RED)]),
            _tile(_e(eid, rt, "binary_sensor", "pump_dry_run"), "Dry-run", "mdi:water-off", THIRD),
            _tile(_e(eid, rt, "binary_sensor", "pump_overload"), "Overload", "mdi:flash-alert", THIRD),
            _tile(_e(eid, rt, "binary_sensor", "pump_short_cycling"), "Short-cycling", "mdi:sync-alert", THIRD),
            _tile(_e(eid, rt, "sensor", "pump_run_hours"), "Run hours"),
            _tile(_e(eid, rt, "sensor", "pump_energy_today"), "Energy today"),
            _tile(_e(eid, rt, "sensor", "pump_m3_per_kwh"), "Water per kWh"),
            _history([cur], "Current, last 24 h"),
            *_setpoint_tiles(eid, rt, ["pump_normal_a", "pump_max_starts"]),
        ], "mdi:pump"))
    return [s for s in out if s]


def irrigation_sections(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    soil = [(rt, e) for rt in runtimes if "soil" in getattr(rt, "families", ())
            if (e := _e(eid, rt, "sensor", "moisture"))]
    out = []
    for hub in hubs:
        mgr = getattr(hub, "irrigation", None)
        if mgr is None or not mgr.enabled:
            continue
        hid, target = hub.entry.entry_id, mgr.cfg.target
        weather = mgr.cfg.weather
        out.append(_section(f"Irrigation and frost – {hub.entry.title}", [
            _g({"type": "weather-forecast", "entity": weather, "forecast_type": "daily",
                "show_forecast": True}, FULL) if weather else None,
            _tile(eid("sensor", f"{hid}_irr_advice"), "Irrigation advice", cols=FULL,
                  state_content=["state", "reason"]),
            _tile(eid("binary_sensor", f"{hid}_irr_rain"), "Rain expected"),
            _tile(eid("binary_sensor", f"{hid}_irr_frost"), "Frost tonight"),
            *[_gauge(e, rt.entry.title, 0, 60, [(0, RED), (target * 0.8, AMBER), (target, GREEN)], cols=THIRD)
              for rt, e in soil],
            _history([e for _, e in soil], "Soil moisture, last 7 days", 168),
            *[_slider(e) for o in _sp.HUB if (e := eid("number", f"{hid}_{_sp.key(o)}"))],
        ], "mdi:weather-partly-rainy"))
    if soil and not out:
        out.append(_section("Soil moisture", [*[_gauge(e, rt.entry.title, 0, 60, cols=THIRD) for rt, e in soil],
                                              _history([e for _, e in soil], "Last 7 days", 168)],
                            "mdi:water-percent"))
    return [s for s in out if s]


def farm_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    return irrigation_sections(eid, runtimes, hubs) + pivot_sections(eid, runtimes) + pump_sections(eid, runtimes)


# ------------------------------------------------------------------ tanks
def tank_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    out = []
    for rt in runtimes:
        if getattr(rt, "tank", None) is None:
            continue
        low = rt.tank_cfg.low_pct or 0
        vol = _e(eid, rt, "sensor", "tank_volume")
        out.append(_section(rt.entry.title, [
            _gauge(_e(eid, rt, "sensor", "tank_fill"), "Fill", 0, 100,
                   [(0, RED), (low, AMBER), (min(100, low * 2 or 40), GREEN)]),
            _tile(vol, "Contents", "mdi:storage-tank"),
            _tile(_e(eid, rt, "sensor", "tank_days_left"), "Days left", "mdi:calendar-clock"),
            _tile(_e(eid, rt, "sensor", "tank_usage_per_day"), "Use per day"),
            _tile(_e(eid, rt, "sensor", "tank_last_refill"), "Last refill"),
            _tile(_e(eid, rt, "binary_sensor", "tank_sudden_drop"), "Sudden drop", "mdi:water-alert"),
            _history([vol], "Contents, last 7 days", 168),
            *_setpoint_tiles(eid, rt, ["tank_low_pct"]),
        ], "mdi:storage-tank"))
    return [s for s in out if s]


# ------------------------------------------------------------------ cold chain / energy
def cold_chain_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    out = []
    for rt in runtimes:
        p = getattr(rt, "purpose", None)
        if p is None or p.group != "cold_chain":
            continue
        cards: list = []
        temp = None
        if getattr(rt, "tempw", None) is not None:
            key = "temperature" if "temperature" in rt.raw or "temperature_1" not in rt.raw else "temperature_1"
            temp = _e(eid, rt, "sensor", key)
            lo, hi = rt.pcfg.get("temp_low"), rt.pcfg.get("temp_high")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                cards.append(_gauge(temp, "Temperature", lo - 10, hi + 10, [(lo - 10, BLUE), (lo, GREEN), (hi, RED)],
                                    unit="°C"))
            cards += [_tile(_e(eid, rt, "binary_sensor", "temp_alarm"), "Out of range", "mdi:thermometer-alert"),
                      _tile(_e(eid, rt, "sensor", "temp_out_today"), "Out of range today"),
                      _tile(_e(eid, rt, "sensor", "temp_excursions_today"), "Excursions today")]
        if "load_" in getattr(rt, "loads", {}):
            cards.append(_gauge(_e(eid, rt, "sensor", "load_duty_24h"), "Compressor duty 24 h", 0, 100,
                                [(0, GREEN), (75, AMBER), (90, RED)]))
        if "contact" in getattr(rt, "_pfam", ()):
            cards.append(_tile(_e(eid, rt, "binary_sensor", "door_active"), "Door"))
        cards.append(_history([temp], "Temperature, last 24 h"))
        cards += _setpoint_tiles(eid, rt, ["p_temp_low", "p_temp_high", "p_left_open_min"])
        out.append(_section(rt.entry.title, cards, p.icon or "mdi:fridge-outline"))
    return [s for s in out if s]


# ------------------------------------------------------------------ cold storage (multi-view)
_COLD_ROLE = ("states.sensor | selectattr('attributes.milesight_role', 'defined') | "
              "selectattr('attributes.milesight_role', 'eq', 'cold_chain') | list")

STATUS_MD = """{% set t = """ + _COLD_ROLE + """ %}{% if not t %}No fridge, freezer or cold-room probes yet – open a temperature sensor → Configure → Purpose → *Fridge / cold room* or *Freezer*.{% else %}{% set alarm = t | selectattr('attributes.alarm') | list %}{% set doors = t | selectattr('attributes.door_open', 'eq', true) | list %}{% set drift = t | rejectattr('attributes.alarm') | selectattr('attributes.temperature', 'number') | list %}{% set ns = namespace(out=[], tir=[]) %}{% for s in drift %}{% set a = s.attributes %}{% if (a.high is number and a.temperature > a.high) or (a.low is number and a.temperature < a.low) %}{% set ns.out = ns.out + [s] %}{% endif %}{% endfor %}{% for s in t %}{% if s.attributes.in_range_7d is number %}{% set ns.tir = ns.tir + [s.attributes.in_range_7d] %}{% endif %}{% endfor %}
| Units | In range | Alarm | Drifting (within delay) | Doors open | Time in range, 7 days |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **{{ t | count }}** | **{{ t | count - alarm | count - ns.out | count }}** | **{{ alarm | count }}** | **{{ ns.out | count }}** | **{{ doors | count }}** | **{{ (ns.tir | min) if ns.tir else '–' }} %** (worst unit) |

{% for s in alarm %}{% set a = s.attributes %}<ha-alert alert-type="error" title="{{ a.device }}{{ ' · ' ~ a.area if a.area }}">{{ a.temperature }} °C – allowed {{ a.low if a.low is not none else '' }} … {{ a.high if a.high is not none else '' }} °C. Out of range {{ s.state }} min today. Record what was done under Compliance → Corrective actions.</ha-alert>
{% endfor %}{% for s in ns.out %}{% set a = s.attributes %}<ha-alert alert-type="warning" title="{{ a.device }}">{{ a.temperature }} °C is outside {{ a.low if a.low is not none else '' }} … {{ a.high if a.high is not none else '' }} °C – alarm after {{ a.delay_min or 0 }} min unless it recovers{{ ' (door open)' if a.door_open }}.</ha-alert>
{% endfor %}{% for s in doors %}<ha-alert alert-type="info">{{ s.attributes.device }}: door open.</ha-alert>
{% endfor %}{% if not alarm and not ns.out %}<ha-alert alert-type="success">All units within their limits.</ha-alert>{% endif %}{% endif %}"""

REPORTS_MD = """{% set r = state_attr('{e}', 'reports') or [] %}{% if not r %}No reports yet. They are made automatically ({{ state_attr('{e}', 'schedule') }}) – or press a button above.{% else %}| | Unit | Period | Min / max | Out of range | Excursions | Coverage | PDF |
|---|---|---|---|---|---|---|---|
{% for x in r[:25] %}| {{ {'compliant': '🟢', 'deviations': '🟠'}.get(x.status, '🔴') }} | {{ x.unit }} | {{ x.period }} | {{ x.min if x.min is not none else '–' }} / {{ x.max if x.max is not none else '–' }} °C | {{ x.out_min }} min | {{ x.excursions }} | {{ x.coverage }} % | [open]({{ x.url }}) |
{% endfor %}
🟢 compliant · 🟠 excursions with a corrective action recorded · 🔴 needs attention (excursion without an action, or data missing){% endif %}
{% if state_attr('{e}', 'email') %}E-mailed with {{ state_attr('{e}', 'email') | join(', ') }}.{% else %}Not e-mailed yet: gateway → Configure → *Cold-chain compliance reports*.{% endif %}"""

LOG_MD = """{% set a = states['{e}'].attributes if states['{e}'] is defined else {} %}| Day | Min | Max | Out of range | Excursions |
|---|---|---|---|---|
{% for d in (a.log or [])[-14:] | reverse %}| {{ d.day }} | {{ d.min }} °C | {{ d.max }} °C | {{ d.out_min }} min | {{ d.excursions }} |
{% endfor %}"""


def _cold_units(runtimes: list) -> list:
    return sorted([rt for rt in runtimes if getattr(getattr(rt, "purpose", None), "group", None) == "cold_chain"
                   and getattr(rt, "tempw", None) is not None],
                  key=lambda rt: ((rt.entry.data.get("area") or "~").lower(), rt.entry.title.lower()))


def _cold_temp(eid: Resolver, rt: Any) -> str | None:
    key = "temperature" if "temperature" in rt.raw or "temperature_1" not in rt.raw else "temperature_1"
    return _e(eid, rt, "sensor", key)


def _cold_gauge(eid: Resolver, rt: Any, cols: int = HALF, name: str | None = None) -> dict | None:
    lo, hi = rt.pcfg.get("temp_low"), rt.pcfg.get("temp_high")
    if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
        return _tile(_cold_temp(eid, rt), name or rt.entry.title, None, cols)
    span = max(4, hi - lo)
    return _gauge(_cold_temp(eid, rt), name or rt.entry.title, lo - span, hi + span,
                  [(lo - span, BLUE), (lo, GREEN), (hi, RED)], unit="°C", cols=cols)


def _stats(entities: list, title: str, days: int, period: str) -> dict | None:
    ents = [e for e in entities if e]
    if not ents:
        return None
    return _g({"type": "statistics-graph", "title": title, "entities": ents, "days_to_show": days,
               "period": period, "stat_types": ["min", "mean", "max"], "chart_type": "line"}, FULL)


def _press(entity: str | None, name: str, icon: str) -> dict | None:
    if not entity:
        return None
    return _g({"type": "tile", "entity": entity, "name": name, "icon": icon, "hide_state": True,
               "tap_action": {"action": "perform-action", "perform_action": "button.press",
                              "target": {"entity_id": entity}, "confirmation": {"text": f"{name}?"}}}, HALF)


def cold_chain_views(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    """Cold storage: Overview (status, alarms, every unit at a glance by area), Units (detail), Trends (7 / 30
    days min-mean-max) and Compliance (reports, corrective actions, daily log)."""
    units = _cold_units(runtimes)
    if not units:
        return []
    areas: dict[str, list] = {}
    for rt in units:
        areas.setdefault(rt.entry.data.get("area") or "Other", []).append(rt)

    # modern Overview: self-discovering status band + the units table + the day-log (no entity ids needed)
    overview = [
        _section("Cold chain status", [{"type": "custom:milesight-coldchain-band", "grid_options": {"columns": "full"}}],
                 "mdi:snowflake-thermometer", span=4),
        _section("Units", [{"type": "custom:milesight-table-card", "preset": "cold_chain", "title": False, "grid_options": {"columns": "full"}},
                           {"type": "custom:milesight-coldlog-card", "title": False, "grid_options": {"columns": "full"}}],
                 "mdi:fridge-outline", span=4),
    ]
    for area, rts in areas.items():
        cards = []
        for rt in rts:
            cards += [_cold_gauge(eid, rt, HALF),
                      _g({"type": "vertical-stack", "cards": [c for c in (
                          {"type": "tile", "entity": _e(eid, rt, "binary_sensor", "temp_alarm"), "name": "Alarm",
                           "icon": "mdi:thermometer-alert"} if _e(eid, rt, "binary_sensor", "temp_alarm") else None,
                          {"type": "tile", "entity": _e(eid, rt, "sensor", "temp_in_range_7d"), "name": "In range 7 d"}
                          if _e(eid, rt, "sensor", "temp_in_range_7d") else None,
                          {"type": "tile", "entity": _e(eid, rt, "binary_sensor", "door_active"), "name": "Door"}
                          if _e(eid, rt, "binary_sensor", "door_active") else None,
                          {"type": "tile", "entity": _e(eid, rt, "sensor", "load_duty_24h"), "name": "Compressor 24 h"}
                          if _e(eid, rt, "sensor", "load_duty_24h") else None) if c]}, HALF)]
        overview.append(_section(area, cards, "mdi:texture-box"))

    detail = []
    for rt in units:
        temp = _cold_temp(eid, rt)
        lo, hi = rt.pcfg.get("temp_low"), rt.pcfg.get("temp_high")
        detail.append(_section(rt.entry.title, [
            _cold_gauge(eid, rt, FULL, "Temperature"),
            _md(f"**Allowed** {'' if lo is None else lo} … {'' if hi is None else hi} °C · alarm after "
                f"{rt.pcfg.get('temp_delay_min') or 0} min out of range"
                + (f" · {rt.entry.data['area']}" if rt.entry.data.get("area") else "")),
            _tile(_e(eid, rt, "sensor", "temp_out_today"), "Out of range today", cols=HALF),
            _tile(_e(eid, rt, "sensor", "temp_excursions_today"), "Excursions today", cols=HALF),
            _tile(_e(eid, rt, "binary_sensor", "door_active"), "Door", cols=HALF),
            _tile(_e(eid, rt, "sensor", "door_today_s"), "Door open today", cols=HALF),
            _tile(_e(eid, rt, "binary_sensor", "load_active"), "Compressor", cols=HALF),
            _tile(_e(eid, rt, "sensor", "load_duty_24h"), "Compressor duty 24 h", cols=HALF),
            _history([temp, _e(eid, rt, "binary_sensor", "door_active")], "Last 24 h"),
            *_setpoint_tiles(eid, rt, ["p_temp_low", "p_temp_high", "p_left_open_min"]),
            _tile(_e(eid, rt, "sensor", "battery"), "Battery", cols=HALF),
            _tile(_e(eid, rt, "binary_sensor", "online") or _e(eid, rt, "sensor", "last_seen"), "Online", cols=HALF),
        ], getattr(rt.purpose, "icon", None) or "mdi:fridge-outline"))

    trends = []
    for rt in units:
        temp = _cold_temp(eid, rt)
        trends.append(_section(rt.entry.title, [
            _stats([temp], "Hourly min / mean / max – 7 days", 7, "hour"),
            _stats([temp], "Daily min / mean / max – 30 days", 30, "day"),
            _history([_e(eid, rt, "sensor", "temp_in_range_7d")], "Time in range, 7 days (%)", 24 * 7),
        ], "mdi:chart-bell-curve-cumulative"))

    # Compliance: the self-discovering card (time in range, one-tap PDF reports, corrective actions, recent reports)
    comp = []
    if any(eid("sensor", f"{hub.entry.entry_id}_compliance_reports") for hub in hubs):
        comp.append(_section("Compliance", [{"type": "custom:milesight-compliance-card", "title": False,
                                             "grid_options": {"columns": "full"}}], "mdi:file-certificate-outline", span=4))
        for rt in units:                               # the per-unit daily log stays as a drill-down
            e = _e(eid, rt, "sensor", "temp_out_today")
            if e:
                comp.append(_section(f"{rt.entry.title} – daily log", [_md(LOG_MD.replace("{e}", e))],
                                     "mdi:notebook-outline"))

    compressors = [_section("Compressors", [{"type": "custom:milesight-table-card", "preset": "compressors",
                                             "title": False, "grid_options": {"columns": "full"}}],
                            "mdi:heat-pump-outline", span=4)]

    _SUB = {"Overview": "Every fridge and freezer at a glance", "Units": "Temperature, door and compressor per unit",
            "Trends": "7- and 30-day min / mean / max", "Compliance": "Time in range, PDF reports and corrective actions",
            "Compressors": "Compressor duty and short-cycling"}

    def view(title: str, path: str, icon: str, sections: list) -> dict | None:
        sections = [x for x in sections if x]
        return {"type": "sections", "title": title, "path": path, "icon": icon, "max_columns": 4,
                "sections": [_header(title, icon, _SUB.get(title))] + sections} if sections else None
    return [v for v in (view("Overview", "overview", "mdi:view-dashboard-outline", overview),
                        view("Units", "units", "mdi:fridge-outline", detail),
                        view("Trends", "trends", "mdi:chart-line", trends),
                        view("Compliance", "compliance", "mdi:file-certificate-outline", comp),
                        view("Compressors", "compressors", "mdi:heat-pump-outline", compressors)) if v]


VIEWS = {"cold_chain.yaml": cold_chain_views}     # builders that make several tabs in front of the bundled ones


def energy_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    out = []
    for rt in runtimes:
        for prefix, (_tr, _cfg, key, ch) in (getattr(rt, "loads", None) or {}).items():
            if key in ("fridge", "freezer"):
                continue
            title = rt.entry.title + (f" – channel {ch}" if ch else "")
            out.append(_section(title, [
                _gauge(_e(eid, rt, "sensor", f"{prefix}duty_24h"), "Duty cycle 24 h", 0, 100,
                       [(0, GREEN), (75, AMBER), (90, RED)]),
                _tile(_e(eid, rt, "sensor", f"{prefix}run_today_h"), "Run time today"),
                _tile(_e(eid, rt, "binary_sensor", f"{prefix}after_hours"), "On after hours", "mdi:weather-night"),
                _tile(_e(eid, rt, "binary_sensor", f"{prefix}service_due"), "Service due", "mdi:wrench-clock"),
            ], "mdi:lightning-bolt"))
        if getattr(rt, "_pkey", None) == "mains":
            out.append(_section(f"Mains – {rt.entry.title}", [
                _gauge(_e(eid, rt, "sensor", "phase_imbalance"), "Phase imbalance", 0, 60,
                       [(0, GREEN), (15, AMBER), (25, RED)]),
                _tile(_e(eid, rt, "binary_sensor", "mains_outage"), "Power outage", "mdi:power-plug-off"),
            ], "mdi:transmission-tower"))
    return [s for s in out if s]


# ------------------------------------------------------------------ building analytics
def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name.lower())


def heatmap_md(areas: list[str] | None, key: str = "hourly_today", first: int = 6, last: int = 21,
               now: bool = True) -> str:
    """Compact occupancy heat map: per area a name line (people now, share of the day) and one row of coloured
    squares, one per hour – fits a phone, no sideways scroll. areas None = every area with occupancy data."""
    names = json.dumps(areas or [], ensure_ascii=False)
    sq = ("{{ '⬜' if p is none else ('🟥' if p >= 75 else ('🟧' if p >= 50 else ('🟨' if p >= 25 else "
          "('🟩' if p > 0 else '⬛')))) }}")
    head = ("**{{ s.attributes.area }}**"
            + ("{% if s.attributes.occupied_now %} · 🧑 {{ s.attributes.people_now if s.attributes.people_now "
               "is not none else 'occupied' }}{% elif s.attributes.occupied_now is not none %} · empty{% endif %}"
               "{% if s.state not in ('unknown', 'unavailable') %} · {{ s.state }} % today{% endif %}" if now else ""))
    return (f"{{% set names = {names} %}}\n"
            f"{{% set rows = states.sensor | selectattr('attributes.{key}', 'defined') | selectattr('attributes.area', "
            f"'defined') | list %}}\n"
            "{% set names = names or (rows | map(attribute='attributes.area') | unique | sort | list) %}\n"
            "{% if not rows %}No occupancy data yet – people counters, PIR and desk sensors in an area fill this in."
            "{% else %}\n"
            "{% for n in names %}{% for s in rows if s.attributes.area == n %}"
            f"{head}  \n"
            f"{{% for h in range({first}, {last + 1}) %}}{{% set p = s.attributes.{key}[h] %}}{sq}{{% endfor %}}\n\n"
            "{% endfor %}{% endfor %}"
            f"<small>{first:02d}:00 → {last:02d}:00, one square per hour · ⬛ empty · 🟩 <25 % · 🟨 25–50 % · "
            "🟧 50–75 % · 🟥 >75 % · ⬜ no data</small>{% endif %}")


def area_names(hubs: list) -> list[str]:
    names: list[str] = []
    for hub in hubs:
        tracker = getattr(hub, "areas", None)
        for n in sorted(getattr(tracker, "summary", {}) or {}):
            if n not in names:
                names.append(n)
    return names


def analytics_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    out = []
    names = area_names(hubs)
    for hub in hubs:
        hid = hub.entry.entry_id
        summary = getattr(getattr(hub, "areas", None), "summary", {}) or {}
        for name in sorted(summary):
            comfort = eid("sensor", f"{hid}_area_{_slug(name)}_comfort")
            occ = eid("sensor", f"{hid}_area_{_slug(name)}_occupancy")
            co2 = next((e for rt in runtimes if getattr(rt, "entry", None) is not None
                        and (rt.entry.data.get("area") or "").lower() == name.lower()
                        and "co2" in rt.raw and (e := _e(eid, rt, "sensor", "co2"))), None)
            temp = next((e for rt in runtimes if getattr(rt, "entry", None) is not None
                         and (rt.entry.data.get("area") or "").lower() == name.lower()
                         and "temperature" in rt.raw and (e := _e(eid, rt, "sensor", "temperature"))), None)
            out.append(_section(name, [
                _gauge(comfort, "Comfort", 0, 100, [(0, RED), (50, AMBER), (80, GREEN)]),
                _gauge(occ, "Occupied today", 0, 100, [(0, GREY), (25, GREEN), (75, AMBER)]),
                _tile(temp, "Temperature", "mdi:thermometer", THIRD),
                _tile(co2, "CO₂", "mdi:molecule-co2", THIRD),
                _tile(comfort, "Humidity", "mdi:water-percent", THIRD, state_content=["humidity"]) if comfort else None,
                _history([temp, co2], "Last 24 h"),
            ], "mdi:texture-box"))
    if names:
        out.insert(0, _section("Occupancy today", [_md(heatmap_md(names))], "mdi:account-clock", span=2))
        out.insert(1, _section("Occupancy yesterday", [_md(heatmap_md(names, "hourly_yesterday", now=False))],
                               "mdi:account-clock-outline", span=2))
    return [s for s in out if s]


def retail_cards(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    """Per-counter detail: one section per people-counter / AI occupancy device, laid out by the device panel."""
    from .retail import _classify
    out = []
    for rt in runtimes:
        if getattr(rt, "entry", None) is None or not hasattr(rt, "model"):
            continue
        kind = _classify(rt.model.key, rt.entry.options.get("purpose"))
        if kind not in ("counter", "zone"):
            continue
        anchor = next((_e(eid, rt, "sensor", k) for k in
                       ("people_net_today", "people_in_today", "occupancy", "people_count")
                       if _e(eid, rt, "sensor", k)), None)
        if not anchor:
            continue
        icon = "mdi:door-sliding" if kind == "counter" else "mdi:select-group"
        out.append(_section(rt.entry.title, [
            _g({"type": "custom:milesight-device-panel", "entity": anchor}, FULL)], icon))
    return out


BUILDERS = {"farm.yaml": farm_cards, "tanks_and_alerts.yaml": tank_cards, "cold_chain.yaml": cold_chain_cards,
            "energy.yaml": energy_cards, "building_analytics.yaml": analytics_cards, "retail.yaml": retail_cards}

# Dashboards whose bundled view is itself the command-center Overview: the generated "Live" tab goes AFTER it
# (per-area detail), not in front.
LIVE_AFTER = {"building_analytics.yaml", "retail.yaml"}


def location_entities(eid: Resolver, runtimes: list) -> list[dict]:
    """Every device with a fixed location (and GNSS trackers) for a map card."""
    out = []
    for rt in runtimes:
        e = None
        if hasattr(rt, "fixed_location") and rt.fixed_location() is not None:
            e = _e(eid, rt, "device_tracker", "fixed_location")
        elif "at101" in getattr(rt.model, "features", ()) or getattr(rt, "distance", None) is not None:
            e = _e(eid, rt, "device_tracker", "location")
        if e:
            out.append({"entity": e, "name": rt.entry.title})
    return out


def map_view(eid: Resolver, runtimes: list) -> dict | None:
    ents = location_entities(eid, runtimes)
    if not ents:
        return None
    return {"title": "Map", "path": "map", "icon": "mdi:map-marker-radius", "type": "panel",
            "cards": [{"type": "map", "entities": ents, "theme_mode": "auto", "default_zoom": 16,
                       "hours_to_show": 0}]}


AFTER = {"maintenance.yaml": map_view}     # extra tabs at the end (not a 'Live' tab in front)


def live_view(sections: list[dict], title: str = "Live", path: str = "live", icon: str = "mdi:gauge") -> dict:
    header = _header(title, icon, "Live gauges, controls and history for this site's devices")
    return {"type": "sections", "title": title, "path": path, "icon": icon, "max_columns": 4,
            "sections": [header] + sections}


def with_live_view(file: str, config: dict, eid: Resolver, runtimes: list, hubs: list) -> dict:
    """The bundled dashboard plus a first 'Live' view (only when there is something to show)."""
    views = VIEWS.get(file)
    if views is not None:
        made = views(eid, runtimes, hubs)      # a full tab set that replaces the bundled views (no duplicates)
        return {**config, "views": made} if made else config
    after = AFTER.get(file)
    if after is not None:
        extra = after(eid, runtimes)
        return {**config, "views": list(config.get("views") or []) + [extra]} if extra else config
    builder = BUILDERS.get(file)
    if builder is None:
        return config
    sections = builder(eid, runtimes, hubs)
    if not sections:
        return config
    lv = live_view(sections)
    views = list(config.get("views") or [])
    return {**config, "views": (views + [lv]) if file in LIVE_AFTER else ([lv] + views)}


# ------------------------------------------------------------------ site landing page
def site_sections(eid: Resolver, runtimes: list, hubs: list) -> list[dict]:
    """What the landing page shows below the building overview: tanks, farm, cold chain, energy at a glance."""
    out: list[dict] = []
    tanks = [rt for rt in runtimes if getattr(rt, "tank", None) is not None]
    if tanks:
        out.append(_section("Tanks and silos", [
            _gauge(_e(eid, rt, "sensor", "tank_fill"), rt.entry.title, 0, 100,
                   [(0, RED), (rt.tank_cfg.low_pct or 0, AMBER), (min(100, (rt.tank_cfg.low_pct or 20) * 2), GREEN)],
                   cols=THIRD) for rt in tanks], "mdi:storage-tank"))
    out += irrigation_sections(eid, runtimes, hubs)
    pivots = [rt for rt in runtimes if getattr(rt, "pivot", None) is not None]
    if pivots:
        ents = []
        for rt in pivots:
            t, c = _e(eid, rt, "device_tracker", "location"), _e(eid, rt, "sensor", "pivot_radius")
            ents += [x for x in ({"entity": t, "name": rt.entry.title} if t else None,
                                 {"entity": c, "name": f"{rt.entry.title} centre"} if c else None) if x]
        out.append(_section("Pivots", [
            _g({"type": "map", "entities": ents, "hours_to_show": 12, "default_zoom": 15, "aspect_ratio": "16:9",
                "theme_mode": "auto"}, FULL) if ents else None,
            *[_gauge(_e(eid, rt, "sensor", "pivot_progress"), rt.entry.title, 0, 100, [(0, BLUE), (95, GREEN)],
                     cols=THIRD) for rt in pivots]], "mdi:sprinkler-variant"))
    pumps = [rt for rt in runtimes if getattr(rt, "pump", None) is not None]
    if pumps:
        out.append(_section("Pumps", [
            _tile(_e(eid, rt, "binary_sensor", "load_active") or _e(eid, rt, "sensor", "pump_run_hours"),
                  rt.entry.title, "mdi:pump", THIRD) for rt in pumps], "mdi:pump"))
    cold = cold_chain_cards(eid, runtimes, hubs)
    if cold:
        out.append(_section("Cold chain", [c for s in cold for c in s["cards"][1:] if gauge_of(c)],
                            "mdi:snowflake-thermometer"))
    loads = [rt for rt in runtimes if getattr(rt, "loads", None)]
    if loads:
        out.append(_section("Energy", [
            _gauge(_e(eid, rt, "sensor", f"{p}duty_24h"), rt.entry.title + (f" {ch}" if ch else ""), 0, 100,
                   [(0, GREEN), (75, AMBER), (90, RED)], cols=THIRD)
            for rt in loads for p, (_t, _c, key, ch) in rt.loads.items() if key not in ("fridge", "freezer")],
            "mdi:lightning-bolt"))
    return [s for s in out if s and len(s["cards"]) > 1]


def nav_section(dashboards: list[tuple[str, str, str]]) -> dict | None:
    """Buttons to the site's other dashboards: (title, url, icon)."""
    return _section("Dashboards", [_nav(t, f"/{u}", i) for t, u, i in dashboards], "mdi:view-dashboard", span=4)
