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
    names = json.dumps(areas, ensure_ascii=False)
    return f"""{{% set names = {names} %}}
{{% set rows = states.sensor | selectattr('attributes.hourly_today', 'defined') | selectattr('attributes.area', 'defined') | selectattr('attributes.area', 'in', names) | list %}}
{{% if not rows %}}No occupancy data yet – people counters, PIR and desk sensors in these areas fill this in.{{% else %}}
{{% set hours = range(7, 20) %}}
| Area | Now | Today |{{% for h in hours %}} {{{{ '%02d' % h }}}} |{{% endfor %}}
|---|---|---|{{% for h in hours %}}---|{{% endfor %}}
{{% for n in names %}}{{% for s in rows if s.attributes.area == n %}}| {{{{ n }}}} | {{{{ ('Occupied' ~ ((' ' ~ s.attributes.people_now) if s.attributes.people_now is not none else '')) if s.attributes.occupied_now else 'Empty' }}}} | {{{{ s.state if s.state not in ('unknown', 'unavailable') else '–' }}}} % |{{% for h in hours %}}{{% set p = s.attributes.hourly_today[h] %}} {{{{ '⬜' if p is none else ('🟥' if p >= 75 else ('🟧' if p >= 50 else ('🟨' if p >= 25 else ('🟩' if p > 0 else '⬛')))) }}}} |{{% endfor %}}
{{% endfor %}}{{% endfor %}}

⬛ empty · 🟩 under 25 % · 🟨 25–50 % · 🟧 50–75 % · 🟥 over 75 % · ⬜ no data{{% endif %}}"""


def _tile(entity: str | None, name: str, icon: str | None = None, columns: int = 6, **kw: Any) -> dict | None:
    if not entity:
        return None
    card = {"type": "tile", "entity": entity, "name": name, "grid_options": {"columns": columns}}
    if icon:
        card["icon"] = icon
    card.update(kw)
    return card


def _gauge(entity: str | None, name: str, lo: float, hi: float, segments: list[tuple[float, str]],
           columns: int = 6) -> dict | None:
    if not entity:
        return None
    return {"type": "gauge", "entity": entity, "name": name, "min": lo, "max": hi, "needle": True,
            "segments": [{"from": f, "color": c} for f, c in segments], "grid_options": {"columns": columns}}


def _section(cards: list[dict | None], span: int | None = None) -> dict:
    sec: dict[str, Any] = {"type": "grid", "cards": [c for c in cards if c]}
    if span:
        sec["column_span"] = span
    return sec


GREEN, YELLOW, RED = "var(--success-color)", "var(--warning-color)", "var(--error-color)"


def build_config(ctx: dict[str, Any]) -> dict[str, Any]:
    """ctx: title, site, health, comfort, air_quality, systems, people, alerts, avg{measure: id},
    devices_online, battery_low, gateways_online, uplinks, outside, co2_alert, areas[{name, icon, comfort,
    occupancy, co2, temperature}]."""
    avg = ctx.get("avg", {})
    co2_alert = ctx.get("co2_alert", 1200)
    badges = [b for b in (
        {"type": "entity", "entity": ctx.get("outside"), "name": "Outside", "show_name": True} if ctx.get("outside") else None,
        {"type": "entity", "entity": ctx.get("health"), "name": "Building health", "show_name": True},
        {"type": "entity", "entity": ctx.get("people"), "name": "People in building", "show_name": True},
        {"type": "entity", "entity": ctx.get("devices_online"), "name": "Devices online", "show_name": True},
        {"type": "entity", "entity": ctx.get("alerts"), "name": "Alerts", "show_name": True},
    ) if b and b.get("entity")]

    sections = [
        _section([{"type": "markdown", "content": _banner(ctx["site"]), "grid_options": {"columns": "full"}}],
                 span=4),
        _section([
            {"type": "heading", "heading": "Overall health", "icon": "mdi:heart-pulse"},
            {"type": "gauge", "entity": ctx.get("health"), "name": "Building health", "min": 0, "max": 100,
             "severity": {"green": 80, "yellow": 60, "red": 0}, "grid_options": {"columns": "full"}}
            if ctx.get("health") else None,
            _tile(ctx.get("comfort"), "Comfort", "mdi:emoticon-happy-outline"),
            _tile(ctx.get("air_quality"), "Air quality", "mdi:air-filter"),
            _tile(ctx.get("systems"), "Systems", "mdi:router-network"),
            _tile(ctx.get("people"), "Occupancy", "mdi:account-group"),
        ]),
        _section([
            {"type": "heading", "heading": "Air quality", "icon": "mdi:air-filter"},
            _gauge(avg.get("co2"), "CO₂", 400, 2000, [(400, GREEN), (800, YELLOW), (co2_alert, RED)]),
            _gauge(avg.get("pm2_5"), "PM2.5", 0, 75, [(0, GREEN), (12, YELLOW), (35, RED)]),
            _gauge(avg.get("tvoc"), "TVOC", 0, 1000, [(0, GREEN), (300, YELLOW), (500, RED)]),
            _gauge(avg.get("humidity"), "Humidity", 0, 100, [(0, YELLOW), (30, GREEN), (60, YELLOW)]),
            {"type": "history-graph", "title": "CO₂ today", "hours_to_show": 24,
             "entities": [{"entity": a["co2"], "name": a["name"]} for a in ctx.get("areas", []) if a.get("co2")]
             or [{"entity": avg["co2"], "name": "Building"}], "grid_options": {"columns": "full"}}
            if avg.get("co2") or any(a.get("co2") for a in ctx.get("areas", [])) else None,
            _tile(avg.get("temperature"), "Temperature", "mdi:thermometer"),
            _tile(avg.get("pm10"), "PM10", "mdi:blur"),
            _tile(avg.get("hcho"), "Formaldehyde", "mdi:molecule"),
            _tile(avg.get("pressure"), "Pressure", "mdi:gauge"),
        ], span=2),
        _section([
            {"type": "heading", "heading": "System health", "icon": "mdi:router-network"},
            _tile(ctx.get("devices_online"), "Devices online", "mdi:check-network-outline"),
            _tile(ctx.get("gateways_online"), "Gateways online", "mdi:router-wireless"),
            _tile(ctx.get("battery_low"), "Battery low", "mdi:battery-alert-variant-outline"),
            _tile(ctx.get("uplinks"), "Uplinks today", "mdi:upload-network"),
            {"type": "markdown", "title": "Needs attention", "content": _attention(ctx["alerts"]),
             "grid_options": {"columns": "full"}} if ctx.get("alerts") else None,
        ]),
    ]
    for a in ctx.get("areas", []):
        cards = [{"type": "heading", "heading": a["name"], "icon": a.get("icon") or "mdi:texture-box"},
                 _tile(a.get("comfort"), "Comfort", "mdi:emoticon-happy-outline", columns=12,
                       state_content=["state", "temperature", "humidity", "co2"]),
                 _tile(a.get("occupancy"), "Occupied today", "mdi:account-clock"),
                 _tile(a.get("co2"), "CO₂", "mdi:molecule-co2")]
        if len(cards) > 1 and any(cards[1:]):
            sections.append(_section(cards))
    if ctx.get("areas"):
        sections.append(_section([
            {"type": "heading", "heading": "Occupancy today", "icon": "mdi:account-clock"},
            {"type": "markdown", "content": _heatmap([a["name"] for a in ctx["areas"]]),
             "grid_options": {"columns": "full"}},
        ], span=4))
    return {"title": ctx.get("title", "Building"), "views": [{
        "type": "sections", "title": "Overview", "path": "overview", "icon": "mdi:office-building",
        "max_columns": 4, "badges": badges, "sections": sections}]}
