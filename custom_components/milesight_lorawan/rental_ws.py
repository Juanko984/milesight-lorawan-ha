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


def _displays_by_area(hass: HomeAssistant) -> dict:
    """Which property areas have a DS3604 e-ink display (so the card can show the 'Push to display' button)."""
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
    out: dict[str, bool] = {}
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        rt = getattr(e, "runtime_data", None)
        if rt is not None and "ds3604" in getattr(getattr(rt, "model", None), "features", frozenset()):
            try:
                out[rt._area()] = True
            except Exception:  # noqa: BLE001
                pass
    return out


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rental/list"})
@websocket_api.async_response
async def ws_list(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass)
    connection.send_result(msg["id"], {"bookings": store.all() if store else {},
                                       "config": store.config_all() if store else {},
                                       "displays": _displays_by_area(hass)})


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


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rental/config_set",
                                  vol.Required("area"): str, vol.Optional("config"): dict})
@websocket_api.async_response
async def ws_config_set(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "No gateway is set up")
        return
    cfg = await store.async_set_config(msg["area"], msg.get("config") or {})
    connection.send_result(msg["id"], {"ok": True, "area": msg["area"], "config": cfg})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rental/push_display",
                                  vol.Required("area"): str, vol.Optional("config"): dict})
@websocket_api.async_response
async def ws_push_display(hass: HomeAssistant, connection, msg: dict) -> None:
    """Compose a guest-welcome card from the property's booking + display settings and push it to the DS3604(s)
    in that area. Saves the settings too, so the same button re-pushes an updated card next booking."""
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
    from .rental_display import build_welcome_template
    store = _store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "No gateway is set up")
        return
    area = msg["area"]
    config = await store.async_set_config(area, msg.get("config") or {}) if msg.get("config") else store.get_config(area)
    booking = store.get(area)
    blocks = build_welcome_template(booking, config)
    pushed, errors = 0, []
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        rt = getattr(e, "runtime_data", None)
        if rt is None or "ds3604" not in getattr(getattr(rt, "model", None), "features", frozenset()):
            continue
        try:
            if rt._area() != area:
                continue
            await rt.async_display(1, blocks, show=True, refresh=True, only_changed=True)
            pushed += 1
        except Exception as err:  # noqa: BLE001
            errors.append(str(err))
    if not pushed and not errors:
        connection.send_error(msg["id"], "no_display", "No DS3604 e-ink display in this property's area")
        return
    connection.send_result(msg["id"], {"ok": pushed > 0, "pushed": pushed, "errors": errors, "config": config})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rental/ack_display",
                                  vol.Required("area"): str})
@websocket_api.async_response
async def ws_ack_display(hass: HomeAssistant, connection, msg: dict) -> None:
    """Reset the 'guest pressed the button' flag on the DS3604(s) in this property's area."""
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
    area = msg["area"]
    acked = 0
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        rt = getattr(e, "runtime_data", None)
        if rt is None or "ds3604" not in getattr(getattr(rt, "model", None), "features", frozenset()):
            continue
        try:
            if rt._area() == area:
                rt.ack_guest_call()
                acked += 1
        except Exception:  # noqa: BLE001
            pass
    connection.send_result(msg["id"], {"ok": True, "area": area, "acked": acked})


RENTAL_WS = (ws_list, ws_set, ws_config_set, ws_push_display, ws_ack_display)


def register(hass: HomeAssistant) -> None:
    for handler in RENTAL_WS:
        websocket_api.async_register_command(hass, handler)
