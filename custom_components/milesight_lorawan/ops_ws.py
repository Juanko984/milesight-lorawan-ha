"""WebSocket commands for the Ops Hub cards (expenses, utility bills, tasks, receipt parsing). Backed by one
OpsStore on the hub; not admin-only (same model as team chat / rental bookings)."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from . import ops_calc as _calc
from .const import DOMAIN


def _store(hass: HomeAssistant):
    for hub in (hass.data.get(DOMAIN, {}).get("hubs") or {}).values():
        s = getattr(hub, "ops", None)
        if s is not None:
            return s
    return None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ops/list"})
@websocket_api.async_response
async def ws_list(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass)
    connection.send_result(msg["id"], store.all() if store else {"expenses": [], "bills": [], "tasks": []})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ops/set",
                                  vol.Required("collection"): str, vol.Optional("id"): vol.Any(str, None),
                                  vol.Required("data"): dict})
@websocket_api.async_response
async def ws_set(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "No gateway is set up for Ops Hub")
        return
    item = await store.async_set(msg["collection"], msg.get("id"), msg["data"])
    if item is None:
        connection.send_error(msg["id"], "invalid", "Nothing to save")
        return
    connection.send_result(msg["id"], {"ok": True, "item": item, "all": store.all()})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ops/delete",
                                  vol.Required("collection"): str, vol.Required("id"): str})
@websocket_api.async_response
async def ws_delete(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass)
    ok = bool(store and await store.async_delete(msg["collection"], msg["id"]))
    connection.send_result(msg["id"], {"ok": ok, "all": store.all() if store else {}})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ops/setting",
                                  vol.Required("key"): str, vol.Required("value"): vol.Any(str, float, int)})
@websocket_api.async_response
async def ws_setting(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "No gateway is set up for Ops Hub")
        return
    connection.send_result(msg["id"], {"ok": True, "settings": await store.async_set_setting(msg["key"], msg["value"])})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ops/ocr", vol.Required("text"): str})
@websocket_api.async_response
async def ws_ocr(hass: HomeAssistant, connection, msg: dict) -> None:
    """Parse pasted / extracted receipt text into fields. The image→text step is a pluggable backend; this is the
    built-in parser that pre-fills the review screen."""
    store = _store(hass)
    vat = float(store.settings().get("vat_rate") if store else 0.15)
    connection.send_result(msg["id"], {"parsed": _calc.parse_receipt_text(msg["text"], vat)})


OPS_WS = (ws_list, ws_set, ws_delete, ws_setting, ws_ocr)


def register(hass: HomeAssistant) -> None:
    for handler in OPS_WS:
        websocket_api.async_register_command(hass, handler)
