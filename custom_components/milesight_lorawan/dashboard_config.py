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
                "shape": "arc", "switchable": False, "ticks": True, "needle": True, "segments": seg}
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


# operational domain -> the site tags that mean "this site has it" (purpose-fit landing page)
_DOMAIN_TAGS = {"tanks": {"tank"}, "cold_chain": {"cold_chain"}, "energy": {"energy", "hvac"},
                "climate": {"comfort"}, "farm": {"pump", "irrigation", "silo"}, "coop": {"coop"}}
_DOMAIN_ORDER = ("energy", "tanks", "cold_chain", "farm", "climate", "coop")
# these exist on every gateway, so the Overview always shows them (the card self-discovers its sensor)
_DOMAIN_ALWAYS = ("fleet", "recipes", "gateways")


def build_config(ctx: dict[str, Any]) -> dict[str, Any]:
    """A production command-center landing page: a status band, the open alerts, and a purpose-fit grid of the
    operational domains this site actually has — each linking to its dashboard. ctx: title, site, open_alerts,
    tags[list], outside, nav[(title, url, icon)]. (The detailed building/air-quality views live on the Building
    analytics dashboard.)"""
    set_classic(ctx.get("classic_gauges", False))
    tags = set(ctx.get("tags") or [])
    # single pane of glass: every system the site has (tag-gated) plus the always-on ones (fleet / recipes / gateways)
    domains = [d for d in _DOMAIN_ORDER if _DOMAIN_TAGS[d] & tags] + list(_DOMAIN_ALWAYS)
    badges = ([{"type": "entity", "entity": ctx["outside"], "name": "Outside", "show_name": True}]
              if ctx.get("outside") else [])

    sections = [
        # masthead with the shortcut nav (every other page has it) + first-run checklist
        _section([
            {"type": "custom:milesight-page-header", "title": "Overview",
             "subtitle": "Everything at a glance across the site", "icon": "mdi:home-outline",
             "stats": False, "grid_options": {"columns": "full"}},
            {"type": "custom:milesight-onboarding", "grid_options": {"columns": "full"}},
        ], span=4),
        # status hero: overall state + self-discovering tiles (alerts, devices, gateways, low battery, spend)
        _section([
            {"type": "custom:milesight-status-band", "lead": True, "grid_options": {"columns": "full"}},
        ], span=4),
        # needs attention: open alerts, most severe first — collapses to nothing when all-clear
        _section([
            {"type": "custom:milesight-attention-card", "grid_options": {"columns": "full"}},
        ], span=4),
    ]
    # perimeter security: electric fences at a glance (energized / fault)
    if "fence" in tags:
        sections.append(_section([
            {"type": "heading", "heading": "Perimeter and security", "icon": "mdi:shield-home"},
            {"type": "custom:milesight-fence-card", "grid_options": {"columns": "full"}},
        ], span=4))
    # operations grid: one summary card per system — each self-discovers and taps through to its dashboard.
    # (The shortcut nav in the header links to every dashboard, so there is no separate button grid here.)
    sections.append(_section(
        [{"type": "heading", "heading": "Systems", "icon": "mdi:view-dashboard-variant"}]
        + [{"type": "custom:milesight-domain-card", "domain": d, "grid_options": {"columns": 4}} for d in domains],
        span=4))
    # site identity, kept for reference at the foot of the page
    sections.append(_section([
        {"type": "heading", "heading": "Site", "icon": "mdi:information-outline"},
        {"type": "markdown", "content": _banner(ctx["site"]), "grid_options": {"columns": "full"}},
    ], span=4))

    sections = [s_ for s_ in sections if s_ and s_["cards"]
                and not (len(s_["cards"]) == 1 and s_["cards"][0]["type"] == "heading")]
    return {"title": ctx.get("title", "Overview"), "views": [{
        "type": "sections", "title": "Overview", "path": "overview", "icon": "mdi:view-dashboard",
        "max_columns": 4, "badges": badges, "sections": sections}]}
