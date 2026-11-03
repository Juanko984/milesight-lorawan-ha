"""WebSocket commands the Team card uses to read and edit workers, and to clock from the card.

Note: ids are passed as "worker_id" — the websocket protocol reserves "id" for the request id (int).
"""
from __future__ import annotations

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
        mgr = getattr(getattr(e, "runtime_data", None), "team", None)
        if mgr is not None:
            return mgr
    return None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/team/list", vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_list(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with a team")
        return
    connection.send_result(msg["id"], {"hub": mgr.entry.entry_id, **(mgr.data or {})})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/team/add",
                                  vol.Required("name"): str, vol.Optional("role"): str,
                                  vol.Optional("tracker"): vol.Any(str, None), vol.Optional("method"): str,
                                  vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_add(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with a team")
        return
    name = (msg.get("name") or "").strip()
    if not name:
        connection.send_error(msg["id"], "invalid", "A worker needs a name")
        return
    w = mgr.add_worker(name, role=msg.get("role", ""), tracker=msg.get("tracker"),
                       method=msg.get("method", "app"))
    connection.send_result(msg["id"], {"worker": w})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/team/update",
                                  vol.Required("worker_id"): str, vol.Required("patch"): dict,
                                  vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_update(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with a team")
        return
    try:
        mgr.update_worker(msg["worker_id"], msg["patch"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/team/delete",
                                  vol.Required("worker_id"): str, vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_delete(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with a team")
        return
    mgr.delete_worker(msg["worker_id"])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/team/clock",
                                  vol.Required("worker_id"): str, vol.Required("kind"): vol.In(["in", "out"]),
                                  vol.Optional("latitude"): vol.Coerce(float),
                                  vol.Optional("longitude"): vol.Coerce(float), vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_clock(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with a team")
        return
    res = mgr.clock(msg["worker_id"], msg["kind"], lat=msg.get("latitude"), lon=msg.get("longitude"))
    connection.send_result(msg["id"], res)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/team/radius",
                                  vol.Required("radius_m"): vol.Coerce(float), vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_radius(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with a team")
        return
    mgr.set_radius(msg["radius_m"])
    connection.send_result(msg["id"], {"ok": True})


TEAM_WS = (ws_list, ws_add, ws_update, ws_delete, ws_clock, ws_radius)


def register(hass: HomeAssistant) -> None:
    for handler in TEAM_WS:
        websocket_api.async_register_command(hass, handler)
