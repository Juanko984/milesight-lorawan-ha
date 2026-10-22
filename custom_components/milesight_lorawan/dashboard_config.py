"""Builds the 'Building' dashboard (a Home Assistant sections view) from built-in cards only.

Pure Python: input is a context of entity ids, output the Lovelace config dict (unit-tested).
"""
from __future__ import annotations

import json
from typing import Any


def _banner(site: str) -> str:
    s = json.dumps(site)
    return f"""{{% set s = {s} %}}
<table width="100%"><tr>
<td width="100">{{% if state_attr(s, 'logo') %}}<img src="{{{{ state_attr(s, 'logo') }}}}" width="84" alt="Logo">{{% endif %}}</td>
<td>
<h2>{{{{ states(s) }}}}</h2>
{{{{ state_attr(s, 'site') }}}}{{% if state_attr(s, 'address') %}} · {{{{ state_attr(s, 'address') }}}}{{% endif %}}<br>
{{% set c = [state_attr(s, 'contact'), state_attr(s, 'phone')] | select | list %}}
{{% if c or state_attr(s, 'email') %}}Facilities: {{{{ c | join(' · ') }}}}{{% if state_attr(s, 'email') %}}{{{{ ' · ' if c else '' }}}}<a href="mailto:{{{{ state_attr(s, 'email') }}}}">{{{{ state_attr(s, 'email') }}}}</a>{{% endif %}}{{% endif %}}
</td>
<td align="right">{{{{ now().strftime('%A %-d %B %Y · %H:%M') }}}}</td>
</tr></table>
{{% if (state_attr(s, 'alerts') or 0) > 0 %}}<ha-alert alert-type="warning">{{{{ state_attr(s, 'status') }}}}</ha-alert>{{% else %}}<ha-alert alert-type="success">All systems normal</ha-alert>{{% endif %}}"""


def _attention(alerts: str) -> str:
    return f"""{{% set al = state_attr({json.dumps(alerts)}, 'alerts') or [] %}}
{{% if not al %}}<ha-alert alert-type="success">Nothing needs attention</ha-alert>{{% else %}}
{{% for a in al %}}<ha-alert alert-type="{{{{ 'error' if a.severity == 'serious' else 'warning' }}}}" title="{{{{ a.where }}}} · {{{{ a.what }}}}">{{{{ a.detail }}}} · since {{{{ a.since }}}}</ha-alert>
{{% endfor %}}{{% endif %}}"""


def _heatmap(areas: list[str]) -> str:
    from .dashboard_live import heatmap_md
    return heatmap_md(areas)


def _open_alerts(entity: str) -> str:
    return f"""{{% set al = state_attr({json.dumps(entity)}, 'alerts') or [] %}}
{{% if not al %}}<ha-alert alert-type="success">No open alerts</ha-alert>{{% else %}}
{{% for a in al %}}<ha-alert alert-type="{{{{ 'error' if a.severity == 'critical' else 'warning' }}}}" title="{{{{ a.title }}}}">{{{{ a.message }}}}<br><small>since {{{{ a.since }}}} · {{{{ a.status }}}}{{% if a.acknowledged_by %}} by {{{{ a.acknowledged_by }}}}{{% endif %}}</small></ha-alert>
{{% endfor %}}{{% endif %}}"""


def _tile(entity: str | None, name: str, icon: str | None = None, columns: int = 6, **kw: Any) -> dict | None:
    if not entity:
        return None
    card = {"type": "tile", "entity": entity, "name": name, "grid_options": {"columns": columns}}
    if icon:
        card["icon"] = icon
    card.update(kw)
    return card


_CLASSIC = False


def set_classic(value: bool) -> None:
    """Emit built-in `gauge` cards instead of the custom milesight gauge (a fallback the user can turn on)."""
    global _CLASSIC
    _CLASSIC = bool(value)


def _gauge(entity: str | None, name: str, lo: float, hi: float, segments: list[tuple[float, str]],
           columns: int = 6) -> dict | None:
    if not entity:
        return None
    from .dashboard_live import safe_gauge
    seg = [{"from": f, "color": c} for f, c in segments]
    if _CLASSIC:                                          # fall back to the built-in gauge card
        card = {"type": "gauge", "entity": entity, "name": name, "min": lo, "max": hi, "needle": True, "segments": seg}
    else:
        # the integration's own gauge card: draws the severity zones on the track (green/amber/red bands) behind the
        # needle, animates, and themes to light/dark. `needle` is kept for backwards tests; the card ignores it.
        card = {"type": "custom:milesight-gauge-card", "entity": entity, "name": name, "min": lo, "max": hi,
                "shape": "arc", "switchable": False, "ticks": False, "needle": True, "segments": seg}
    return {**safe_gauge(card), "grid_options": {"columns": columns}}


def _section(cards: list[dict | None], span: int | None = None) -> dict:
    sec: dict[str, Any] = {"type": "grid", "cards": [c for c in cards if c]}
    if span:
        sec["column_span"] = span
    return sec


GREEN, YELLOW, RED = "var(--success-color)", "var(--warning-color)", "var(--error-color)"


def _nav(title: str, url: str, icon: str) -> dict:
    return {"type": "button", "name": title, "icon": icon, "show_state": False,
            "tap_action": {"action": "navigate", "navigation_path": f"/{url}"},
            "grid_options": {"columns": 3, "rows": 2}}


def build_config(ctx: dict[str, Any]) -> dict[str, Any]:
    """ctx: title, site, health, comfort, air_quality, systems, people, alerts, open_alerts, avg{measure: id},
    devices_online, battery_low, gateways_online, uplinks, outside, co2_alert, areas[{name, icon, comfort,
    occupancy, co2, temperature}], nav[(title, url, icon)], live[sections from dashboard_live.site_sections]."""
    set_classic(ctx.get("classic_gauges", False))
    avg = ctx.get("avg", {})
    co2_alert = ctx.get("co2_alert", 1200)
    areas = ctx.get("areas", [])
    badges = [b for b in (
        {"type": "entity", "entity": ctx.get("outside"), "name": "Outside", "show_name": True} if ctx.get("outside") else None,
        {"type": "entity", "entity": ctx.get("health"), "name": "Building health", "show_name": True},
        {"type": "entity", "entity": ctx.get("people"), "name": "People in building", "show_name": True},
        {"type": "entity", "entity": ctx.get("devices_online"), "name": "Devices online", "show_name": True},
        {"type": "entity", "entity": ctx.get("alerts"), "name": "Alerts", "show_name": True},
    ) if b and b.get("entity")]

    sections = [
        _section([
            {"type": "custom:milesight-onboarding", "grid_options": {"columns": "full"}},
            {"type": "markdown", "content": _banner(ctx["site"]), "grid_options": {"columns": "full"}},
        ], span=4),
    ]
    if ctx.get("nav"):
        sections.append(_section([{"type": "heading", "heading": "Dashboards", "icon": "mdi:view-dashboard"}]
                                 + [_nav(*n) for n in ctx["nav"]], span=4))
    sections += [
        _section([
            {"type": "heading", "heading": "Overall health", "icon": "mdi:heart-pulse"},
            {**_gauge(ctx.get("health"), "Building health", 0, 100, [(0, RED), (60, YELLOW), (80, GREEN)]),
             "grid_options": {"columns": "full"}} if ctx.get("health") else None,
            _tile(ctx.get("comfort"), "Comfort", "mdi:emoticon-happy-outline"),
            _tile(ctx.get("air_quality"), "Air quality", "mdi:air-filter"),
            _tile(ctx.get("systems"), "Systems", "mdi:router-network"),
            _tile(ctx.get("people"), "People now", "mdi:account-group"),
        ]),
        _section([
            {"type": "heading", "heading": "Needs attention", "icon": "mdi:bell-alert"},
            {"type": "markdown", "content": _open_alerts(ctx["open_alerts"]), "grid_options": {"columns": "full"}}
            if ctx.get("open_alerts") else None,
            {"type": "markdown", "content": _attention(ctx["alerts"]), "grid_options": {"columns": "full"}}
            if ctx.get("alerts") else None,
        ]),
        _section([
            {"type": "heading", "heading": "Air quality", "icon": "mdi:air-filter"},
            _gauge(avg.get("co2"), "CO₂", 400, 2000, [(400, GREEN), (800, YELLOW), (co2_alert, RED)]),
            _gauge(avg.get("pm2_5"), "PM2.5", 0, 75, [(0, GREEN), (12, YELLOW), (35, RED)]),
            _gauge(avg.get("tvoc"), "TVOC", 0, 1000, [(0, GREEN), (300, YELLOW), (500, RED)]),
            _gauge(avg.get("humidity"), "Humidity", 0, 100, [(0, YELLOW), (30, GREEN), (60, YELLOW)]),
            {"type": "history-graph", "title": "CO₂ today", "hours_to_show": 24,
             "entities": [{"entity": a["co2"], "name": a["name"]} for a in areas if a.get("co2")]
             or [{"entity": avg["co2"], "name": "Building"}], "grid_options": {"columns": "full"}}
            if avg.get("co2") or any(a.get("co2") for a in areas) else None,
            _tile(avg.get("temperature"), "Temperature", "mdi:thermometer"),
            _tile(avg.get("pm10"), "PM10", "mdi:blur"),
            _tile(avg.get("hcho"), "Formaldehyde", "mdi:molecule"),
            _tile(avg.get("pressure"), "Pressure", "mdi:gauge"),
        ]),
        _section([
            {"type": "heading", "heading": "System health", "icon": "mdi:router-network"},
            _tile(ctx.get("devices_online"), "Devices online", "mdi:check-network-outline"),
            _tile(ctx.get("gateways_online"), "Gateways online", "mdi:router-wireless"),
            _tile(ctx.get("battery_low"), "Battery low", "mdi:battery-alert-variant-outline"),
            _tile(ctx.get("uplinks"), "Uplinks today", "mdi:upload-network"),
        ]),
    ]
    people = [a for a in areas if a.get("occupancy")]
    if areas:
        sections.append(_section(
            [{"type": "heading", "heading": "People", "icon": "mdi:account-group"},
             _tile(ctx.get("people"), "In the building now", "mdi:account-group", columns=12)]
            + [_tile(a["occupancy"], a["name"], a.get("icon") or "mdi:account-clock", columns=6,
                     state_content=["people_now", "state"]) for a in people]
            + [{"type": "markdown", "content": _heatmap([a["name"] for a in areas]),
                "grid_options": {"columns": "full"}}], span=2))
    for a in areas:
        cards = [{"type": "heading", "heading": a["name"], "icon": a.get("icon") or "mdi:texture-box"},
                 _tile(a.get("comfort"), "Comfort", "mdi:emoticon-happy-outline", columns=12,
                       state_content=["state", "temperature", "humidity", "co2"]),
                 _tile(a.get("occupancy"), "Occupied today", "mdi:account-clock"),
                 _tile(a.get("co2"), "CO₂", "mdi:molecule-co2")]
        if len(cards) > 1 and any(cards[1:]):
            sections.append(_section(cards))
    sections += [s_ for s_ in ctx.get("live") or [] if s_]
    sections = [s_ for s_ in sections if s_["cards"] and not (len(s_["cards"]) == 1 and s_["cards"][0]["type"] == "heading")]
    return {"title": ctx.get("title", "Building"), "views": [{
        "type": "sections", "title": "Overview", "path": "overview", "icon": "mdi:office-building",
        "max_columns": 4, "badges": badges, "sections": sections}]}
