"""WebSocket command the Alerts card uses to set who is on call (the primary notify target) from the page,
without opening the integration's options. Writes the hub entry's alert_primary option; the entry reloads and
the alert manager picks up the new on-call person.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import CONF_ALERT_PRIMARY, CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB


def _hub_entry(hass: HomeAssistant, hub_id: str | None):
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_HUB:
            continue
        if hub_id and e.entry_id != hub_id:
            continue
        return e
    return None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/alerts/set_oncall",
                                  vol.Optional("targets"): [str], vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_set_oncall(hass: HomeAssistant, connection, msg: dict) -> None:
    """Set the primary on-call notify target(s). An empty list clears it (no one is paged by default)."""
    entry = _hub_entry(hass, msg.get("hub"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "No gateway to set on-call for")
        return
    targets = [t for t in (msg.get("targets") or []) if isinstance(t, str) and t.strip()]
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_ALERT_PRIMARY: targets})
    connection.send_result(msg["id"], {"ok": True, "primary": targets})


ALERTS_WS = (ws_set_oncall,)


def register(hass: HomeAssistant) -> None:
    for handler in ALERTS_WS:
        websocket_api.async_register_command(hass, handler)
