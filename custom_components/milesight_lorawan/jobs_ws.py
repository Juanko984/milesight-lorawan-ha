"""WebSocket commands the Jobs card uses to read and edit jobs. Manager lives in jobs.py.

Note: ids are passed as "job_id" — the websocket protocol reserves "id" for the request id (int).
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
        mgr = getattr(getattr(e, "runtime_data", None), "jobs", None)
        if mgr is not None:
            return mgr
    return None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/jobs/list", vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_list(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with jobs")
        return
    connection.send_result(msg["id"], {"hub": mgr.entry.entry_id, **(mgr.data or {})})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/jobs/create",
                                  vol.Required("title"): str, vol.Optional("detail"): str,
                                  vol.Optional("priority"): str, vol.Optional("area"): vol.Any(str, None),
                                  vol.Optional("assignee"): vol.Any(str, None), vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_create(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with jobs")
        return
    title = (msg.get("title") or "").strip()
    if not title:
        connection.send_error(msg["id"], "invalid", "A job needs a title")
        return
    job = mgr.create(title, detail=msg.get("detail", ""), priority=msg.get("priority", "info"),
                     area=msg.get("area"), assignee=msg.get("assignee"))
    connection.send_result(msg["id"], {"job": job})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/jobs/status",
                                  vol.Required("job_id"): str, vol.Required("status"): str,
                                  vol.Optional("resolution"): vol.Any(str, None),
                                  vol.Optional("resolved_by"): vol.Any(str, None),
                                  vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_status(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with jobs")
        return
    try:
        mgr.set_status(msg["job_id"], msg["status"], resolved_by=msg.get("resolved_by"),
                       resolution=msg.get("resolution"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/jobs/assign",
                                  vol.Required("job_id"): str, vol.Optional("assignee"): vol.Any(str, None),
                                  vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_assign(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with jobs")
        return
    try:
        mgr.assign(msg["job_id"], msg.get("assignee"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/jobs/check",
                                  vol.Required("job_id"): str, vol.Required("index"): int,
                                  vol.Required("done"): bool, vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_check(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with jobs")
        return
    try:
        mgr.toggle_check(msg["job_id"], msg["index"], msg["done"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/jobs/delete",
                                  vol.Required("job_id"): str, vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_delete(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with jobs")
        return
    mgr.delete(msg["job_id"])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/jobs/sweep", vol.Optional("hub"): str})
@websocket_api.require_admin
@callback
def ws_sweep(hass: HomeAssistant, connection, msg: dict) -> None:
    """Reconcile existing alert-jobs and raise a job for each open alert that doesn't have one yet."""
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with jobs")
        return
    connection.send_result(msg["id"], mgr.auto_check())


JOBS_WS = (ws_list, ws_create, ws_status, ws_assign, ws_check, ws_delete, ws_sweep)


def register(hass: HomeAssistant) -> None:
    for handler in JOBS_WS:
        websocket_api.async_register_command(hass, handler)
