"""WebSocket commands the Recipes card uses to read and edit recipes. Engine lives in recipes.py."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB


def _manager(hass: HomeAssistant, hub_id: str | None):
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_HUB:
            continue
        if hub_id and e.entry_id != hub_id:
            continue
        mgr = getattr(getattr(e, "runtime_data", None), "recipes", None)
        if mgr is not None:
            return mgr
    return None


def _after(mgr) -> None:
    """Recompute the snapshot and persist immediately after a change."""
    mgr.update()
    if mgr.store is not None:
        mgr.store.async_delay_save(mgr._to_store, 1)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/recipes/list", vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_list(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with recipes")
        return
    connection.send_result(msg["id"], {"hub": mgr.entry.entry_id, **(mgr.data or {})})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/recipes/enable",
                                  vol.Required("catalog"): str, vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_enable(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with recipes")
        return
    try:
        inst = mgr.enable(msg["catalog"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _after(mgr)
    connection.send_result(msg["id"], {"recipe": inst})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/recipes/update",
                                  vol.Required("recipe"): dict, vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_update(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with recipes")
        return
    try:
        mgr.update_recipe(msg["recipe"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _after(mgr)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/recipes/toggle",
                                  vol.Required("id"): str, vol.Required("enabled"): bool, vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_toggle(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with recipes")
        return
    try:
        mgr.toggle(msg["id"], msg["enabled"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _after(mgr)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/recipes/delete",
                                  vol.Required("id"): str, vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_delete(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with recipes")
        return
    mgr.delete(msg["id"])
    _after(mgr)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/recipes/test",
                                  vol.Required("id"): str, vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_test(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with recipes")
        return
    fired = mgr.test(msg["id"])
    if fired is None:
        connection.send_error(msg["id"], "not_found", "Recipe not found")
        return
    connection.send_result(msg["id"], fired)


RECIPE_WS = (ws_list, ws_enable, ws_update, ws_toggle, ws_delete, ws_test)


def register(hass: HomeAssistant) -> None:
    for handler in RECIPE_WS:
        websocket_api.async_register_command(hass, handler)
