"""WebSocket commands the Team chat card uses: list channels + messages, send, mark read, and a live subscription.

Any authenticated Home Assistant user can chat (not admin-only). The sender defaults to the logged-in HA user;
a shared tablet can 'post as' a Team worker by name (validated against the team list)."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB
from .messaging import SIGNAL_CHAT


def _manager(hass: HomeAssistant, hub_id: str | None):
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_HUB:
            continue
        if hub_id and e.entry_id != hub_id:
            continue
        mgr = getattr(getattr(e, "runtime_data", None), "chat", None)
        if mgr is not None:
            return mgr
    return None


def _user(connection) -> tuple[str, str | None]:
    u = getattr(connection, "user", None)
    return ((getattr(u, "name", None) or "User"), getattr(u, "id", None)) if u else ("User", None)


def _is_admin(connection) -> bool:
    return bool(getattr(getattr(connection, "user", None), "is_admin", False))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/list",
                                  vol.Optional("hub"): str, vol.Optional("channel"): str})
@callback
def ws_list(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return
    _, user_id = _user(connection)
    connection.send_result(msg["id"], mgr.snapshot(user_id, msg.get("channel"), is_admin=_is_admin(connection)))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/send", vol.Required("channel"): str,
                                  vol.Optional("text"): str, vol.Optional("as_worker"): vol.Any(str, None),
                                  vol.Optional("push"): bool, vol.Optional("image"): vol.Any(str, None),
                                  vol.Optional("loc"): vol.Any(dict, None), vol.Optional("hub"): str})
@websocket_api.async_response
async def ws_send(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return
    author, user_id = _user(connection)
    role = ""
    aw = (msg.get("as_worker") or "").strip()
    if aw:
        team = getattr(getattr(mgr.entry, "runtime_data", None), "team", None)
        worker = next((w for w in (getattr(team, "data", {}).get("workers") or []) if w.get("name") == aw), None)
        if worker is None:
            connection.send_error(msg["id"], "invalid", "Unknown worker")
            return
        author, role = aw, worker.get("role", "")
    image_url = await mgr.save_image(msg["image"]) if msg.get("image") else None
    out = mgr.post(msg["channel"], msg.get("text", ""), author=author, user_id=user_id, role=role,
                   push=bool(msg.get("push")), image=image_url, loc=msg.get("loc"))
    if out is None:
        connection.send_error(msg["id"], "invalid", "Empty message or unknown channel")
        return
    connection.send_result(msg["id"], {"message": out})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/read",
                                  vol.Required("channel"): str, vol.Optional("hub"): str})
@callback
def ws_read(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return
    name, user_id = _user(connection)
    if user_id:
        mgr.mark_read(user_id, msg["channel"], name)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/subscribe",
                                  vol.Optional("hub"): str, vol.Optional("presence"): bool})
@callback
def ws_subscribe(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return

    @callback
    def _forward(data) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], data))

    disconnect = async_dispatcher_connect(hass, SIGNAL_CHAT.format(mgr.entry.entry_id), _forward)
    # Only a real chat view (not the global sidebar-badge subscription) counts as "in chat now".
    presence = bool(msg.get("presence"))
    name, user_id = _user(connection)
    if presence:
        mgr.presence_add(user_id, name)

    @callback
    def _cleanup() -> None:
        disconnect()
        if presence:
            mgr.presence_drop(user_id)

    connection.subscriptions[msg["id"]] = _cleanup
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/typing",
                                  vol.Required("channel"): str, vol.Optional("hub"): str})
@callback
def ws_typing(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return
    name, user_id = _user(connection)
    mgr.typing(user_id, name, msg["channel"])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/channel/create",
                                  vol.Required("title"): str, vol.Optional("icon"): str, vol.Optional("hub"): str})
@callback
def ws_channel_create(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return
    c = mgr.create_channel(msg["title"], icon=msg.get("icon") or "mdi:pound")
    if c is None:
        connection.send_error(msg["id"], "invalid", "A channel name is required")
        return
    connection.send_result(msg["id"], {"channel": c})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/channel/rename",
                                  vol.Required("channel"): str, vol.Required("title"): str, vol.Optional("hub"): str})
@callback
def ws_channel_rename(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return
    c = mgr.rename_channel(msg["channel"], msg["title"])
    if c is None:
        connection.send_error(msg["id"], "invalid", "Unknown channel or empty name")
        return
    connection.send_result(msg["id"], {"channel": c})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/channel/archive",
                                  vol.Required("channel"): str, vol.Optional("archived"): bool, vol.Optional("hub"): str})
@callback
def ws_channel_archive(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return
    c = mgr.archive_channel(msg["channel"], bool(msg.get("archived", True)))
    if c is None:
        connection.send_error(msg["id"], "invalid", "That channel can't be archived")
        return
    connection.send_result(msg["id"], {"channel": c})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/chat/channel/device",
                                  vol.Required("device_id"): str, vol.Optional("name"): vol.Any(str, None),
                                  vol.Optional("hub"): str})
@callback
def ws_channel_device(hass: HomeAssistant, connection, msg: dict) -> None:
    mgr = _manager(hass, msg.get("hub"))
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No gateway with messaging")
        return
    c = mgr.ensure_device_channel(msg["device_id"], msg.get("name"))
    if c is None:
        connection.send_error(msg["id"], "invalid", "A device is required")
        return
    connection.send_result(msg["id"], {"channel": c})


def register(hass: HomeAssistant) -> None:
    for handler in (ws_list, ws_send, ws_read, ws_subscribe, ws_typing,
                    ws_channel_create, ws_channel_rename, ws_channel_archive, ws_channel_device):
        websocket_api.async_register_command(hass, handler)
