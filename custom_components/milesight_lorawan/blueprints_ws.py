"""WebSocket command the Rules page uses to list the ready-made automation blueprints the integration ships
(leak, door-left-open, temperature-out-of-range, battery low, device/gateway offline …), so the page can show
what's available with a link to set each one up. Blueprints are instantiated in Home Assistant's own automation
editor, so this is read-only — it just surfaces the catalogue and whether each file is installed.
"""
from __future__ import annotations

import pathlib

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_BUNDLED = pathlib.Path(__file__).parent / "resources" / "blueprints"


def _read_blueprints(installed_dir: pathlib.Path) -> list[dict]:
    """Parse each shipped blueprint's name / description, and note whether it is installed on disk."""
    import yaml

    class _BPLoader(yaml.SafeLoader):
        """Home Assistant blueprints use custom tags (!input, !include, !secret); we only read the
        top-level name/description, so treat any such tag as a plain value instead of failing."""

    _BPLoader.add_multi_constructor("!", lambda loader, suffix, node: None)

    out: list[dict] = []
    for p in sorted(_BUNDLED.glob("*.yaml")):
        try:
            bp = (yaml.load(p.read_text(encoding="utf-8"), _BPLoader) or {}).get("blueprint") or {}
        except Exception:  # noqa: BLE001 - one unreadable blueprint shouldn't hide the rest
            continue
        out.append({
            "slug": p.stem,
            "name": bp.get("name") or p.stem,
            "description": " ".join((bp.get("description") or "").split()),   # collapse YAML-folded whitespace
            "installed": (installed_dir / p.name).exists(),
        })
    out.sort(key=lambda b: b["name"].lower())
    return out


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/blueprints"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_blueprints(hass: HomeAssistant, connection, msg: dict) -> None:
    installed_dir = pathlib.Path(hass.config.path("blueprints", "automation", DOMAIN))
    blueprints = await hass.async_add_executor_job(_read_blueprints, installed_dir)
    connection.send_result(msg["id"], {"blueprints": blueprints,
                                       "url": "/config/blueprints/dashboard"})


BLUEPRINTS_WS = (ws_blueprints,)


def register(hass: HomeAssistant) -> None:
    for handler in BLUEPRINTS_WS:
        websocket_api.async_register_command(hass, handler)
