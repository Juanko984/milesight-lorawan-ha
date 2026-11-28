"""WebSocket commands the Property (short-stay) card uses to read and write per-property booking details,
without opening the integration's options. Backed by one shared BookingStore on the hub, so every viewer sees
the same bookings. Not admin-only: a host editing their own stay should not need admin rights (same as the team
chat / jobs commands)."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN


def _store(hass: HomeAssistant):
    for hub in (hass.data.get(DOMAIN, {}).get("hubs") or {}).values():
        store = getattr(hub, "bookings", None)
        if store is not None:
            return store
    return None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rental/list"})
@websocket_api.async_response
async def ws_list(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass)
    connection.send_result(msg["id"], {"bookings": store.all() if store else {}})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rental/set",
                                  vol.Required("area"): str, vol.Optional("booking"): dict})
@websocket_api.async_response
async def ws_set(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "No gateway is set up to store bookings")
        return
    booking = await store.async_set(msg["area"], msg.get("booking") or {})
    connection.send_result(msg["id"], {"ok": True, "area": msg["area"], "booking": booking})


RENTAL_WS = (ws_list, ws_set)


def register(hass: HomeAssistant) -> None:
    for handler in RENTAL_WS:
        websocket_api.async_register_command(hass, handler)
