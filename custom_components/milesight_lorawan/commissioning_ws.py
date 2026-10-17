"""Commissioning panel for installers: sidebar page 'LoRaWAN commissioning' (admins only) with
* scan a device's QR code (Companion app scanner, the phone camera, a photo, or typing) → add it to Home Assistant
  and register it on the gateway in one go,
* a live walk test: every uplink of the device with RSSI / SNR / SF / gateways and a verdict, optional fast
  reporting (1 minute) for the walk, results saved on the device.
The page talks to the integration through the websocket commands below."""
from __future__ import annotations

import logging
import pathlib
import time
from typing import Any

try:  # Home Assistant 2026.x replaced voluptuous with probatio (same API)
    import probatio as vol
except ImportError:  # older Home Assistant
    import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .commissioning import parse_qr, sample, walk_summary
from .const import CONF_DEVEUI, CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_DEVICE, SIGNAL_HEARD
from .models import MODELS, downlinks, families, guess_from_name, guess_model
from .purposes import GROUPS, PURPOSES

_LOGGER = logging.getLogger(__name__)
STATIC_URL = f"/{DOMAIN}_static"
PANEL_URL = "milesight-commissioning"
FRONTEND = pathlib.Path(__file__).parent / "frontend"


def _hubs(hass: HomeAssistant) -> list:
    return list(hass.data.get(DOMAIN, {}).get("hubs", {}).values())


def _runtime(hass: HomeAssistant, deveui: str):
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_DEVEUI) == deveui and getattr(e, "runtime_data", None) is not None:
            return e.runtime_data
    return None


def _norm(deveui: str) -> str:
    return "".join(ch for ch in str(deveui).lower() if ch in "0123456789abcdef")


async def async_setup_panel(hass: HomeAssistant, version: str) -> None:
    """Static files, sidebar panel and websocket commands (once)."""
    data = hass.data.setdefault(DOMAIN, {"hubs": {}})
    if not data.get("commissioning_static"):         # static paths cannot be unregistered: once per run
        try:
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(FRONTEND), True)])
        except ImportError:          # Home Assistant before 2024.7
            hass.http.register_static_path(STATIC_URL, str(FRONTEND), True)
        data["commissioning_static"] = True
    if not data.get("commissioning_ws"):
        for handler in (ws_parse, ws_devices, ws_add, ws_watch, ws_fast, ws_end_fast, ws_save, ws_location):
            websocket_api.async_register_command(hass, handler)
        data["commissioning_ws"] = True
    if not data.get("commissioning_panel"):
        from homeassistant.components import panel_custom
        await panel_custom.async_register_panel(
            hass, frontend_url_path=PANEL_URL, webcomponent_name="milesight-commissioning",
            sidebar_title="LoRaWAN commissioning", sidebar_icon="mdi:qrcode-scan",
            module_url=f"{STATIC_URL}/commissioning.js?v={version}", require_admin=True, config={})
        data["commissioning_panel"] = True


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """The last gateway entry was removed: take the page out of the sidebar."""
    data = hass.data.get(DOMAIN, {})
    if data.get("commissioning_panel"):
        from homeassistant.components import frontend
        frontend.async_remove_panel(hass, PANEL_URL)
        data["commissioning_panel"] = False


# ------------------------------------------------------------------ commands
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/parse", vol.Required("text"): str})
@websocket_api.require_admin
@callback
def ws_parse(hass: HomeAssistant, connection, msg: dict) -> None:
    """QR text → DevEUI, AppKey, model guess; whether it is already set up and whether the gateway can add it."""
    p = parse_qr(msg["text"], guess_from_name)
    deveui = p.get("deveui")
    candidates: list[str] = []
    for hub in _hubs(hass):                     # heard already? use its payload to guess the model
        up = hub.last_uplink.get(deveui) if deveui else None
        if up is not None and up.raw:
            best, candidates = guess_model(up.raw)
            p["model"] = p["model"] or best or guess_from_name(up.device_name)
            p["heard"] = True
    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, deveui) if deveui else None
    connection.send_result(msg["id"], {
        **{k: v for k, v in p.items() if k != "app_key"}, "has_app_key": bool(p.get("app_key")),
        "app_key": p.get("app_key"), "candidates": candidates, "exists": entry is not None,
        "existing_name": entry.title if entry else None,
        "can_register": any(getattr(h, "can_provision", False) for h in _hubs(hass)),
        "models": sorted(({"value": k, "label": m.label} for k, m in MODELS.items()), key=lambda x: x["label"]),
        "families": {k: sorted(families(k)) for k in MODELS},
        "purposes": [{"value": pp.key, "families": sorted(pp.families),
                      "label": pp.label + (f" · {GROUPS[pp.group][0].split('· ')[1]}" if pp.group else "")}
                     for pp in PURPOSES.values()],
    })


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/devices"})
@websocket_api.require_admin
@callback
def ws_devices(hass: HomeAssistant, connection, msg: dict) -> None:
    """Devices to walk-test: the ones set up, plus ones the gateway hears that are not set up yet."""
    known = {}
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        rt = getattr(e, "runtime_data", None)
        known[e.data[CONF_DEVEUI]] = {
            "deveui": e.data[CONF_DEVEUI], "name": e.title, "model": e.options.get("model", e.data.get("model")),
            "area": e.data.get("area"), "last_seen": rt.meta.get("last_seen") if rt else None,
            "can_fast": bool(rt is not None and "prefix" in (downlinks(rt.model.key).get("report_interval") or {})),
            "walk_test": rt.meta.get("walk_test") if rt else None, "configured": True,
            "location": e.options.get("location")}
    heard = []
    for hub in _hubs(hass):
        for eui, up in hub.last_uplink.items():
            if eui not in known:
                heard.append({"deveui": eui, "name": up.device_name or eui.upper(), "configured": False,
                              "last_seen": up.extra.get("_rx")})
    connection.send_result(msg["id"], {"devices": sorted(known.values(), key=lambda d: d["name"].lower()),
                                       "unknown": heard, "now": time.time()})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/commission/add",
    vol.Required("deveui"): str, vol.Required("model"): str, vol.Optional("name"): str,
    vol.Optional("area"): str, vol.Optional("app_key"): str, vol.Optional("register", default=True): bool,
    vol.Optional("purpose"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_add(hass: HomeAssistant, connection, msg: dict) -> None:
    deveui = _norm(msg["deveui"])
    if len(deveui) != 16 or msg["model"] not in MODELS:
        connection.send_error(msg["id"], "invalid", "DevEUI must be 16 hex digits and the model must be known")
        return
    key = _norm(msg.get("app_key") or "") or None
    if key is not None and len(key) != 32:
        connection.send_error(msg["id"], "invalid", "The AppKey must be 32 hex digits")
        return
    name = (msg.get("name") or "").strip() or f"{msg['model']} {deveui[-4:].upper()}"
    gateway = None
    if msg.get("register"):
        hub = next((h for h in _hubs(hass) if getattr(h, "can_provision", False)), None)
        if hub is not None:
            try:
                gateway = await hub.async_provision(deveui, name, key)
            except Exception as err:  # noqa: BLE001
                connection.send_error(msg["id"], "gateway", f"The gateway did not accept the device: {err}")
                return
    exists = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, deveui) is not None
    if not exists:
        # a discovery card for this DevEUI would block the new entry: close it first
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN):
            if (flow.get("context") or {}).get("unique_id") == deveui:
                hass.config_entries.flow.async_abort(flow["flow_id"])
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data={
            CONF_DEVEUI: deveui, "model": msg["model"], "name": name, "area": (msg.get("area") or "").strip() or None,
            "purpose": msg.get("purpose") or None})
        rtype = result.get("type")
        if str(getattr(rtype, "value", rtype)) != "create_entry":
            connection.send_error(msg["id"], "not_added", f"Home Assistant did not add it: "
                                  f"{result.get('reason') or rtype}" + (" (it was registered on the gateway)"
                                                                        if gateway else ""))
            return
    connection.send_result(msg["id"], {"deveui": deveui, "name": name, "gateway": gateway, "existed": exists})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/watch", vol.Required("deveui"): str})
@websocket_api.require_admin
@callback
def ws_watch(hass: HomeAssistant, connection, msg: dict) -> None:
    """Live: one event per uplink of this device (the last one heard is sent first)."""
    deveui = _norm(msg["deveui"])

    @callback
    def _forward(up, duplicate: bool) -> None:
        if up.deveui == deveui:
            connection.send_message(websocket_api.event_message(msg["id"], sample(up, duplicate, time.time())))
    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_HEARD, _forward)
    connection.send_result(msg["id"])
    for hub in _hubs(hass):
        up = hub.last_uplink.get(deveui)
        if up is not None:
            last = sample(up, False, up.extra.get("_rx"))
            last["previous"] = True
            connection.send_message(websocket_api.event_message(msg["id"], last))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/fast", vol.Required("deveui"): str,
                                  vol.Optional("minutes", default=30): vol.All(int, vol.Range(min=5, max=240))})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_fast(hass: HomeAssistant, connection, msg: dict) -> None:
    rt = _runtime(hass, _norm(msg["deveui"]))
    if rt is None:
        connection.send_error(msg["id"], "not_found", "Add the device to Home Assistant first")
        return
    try:
        connection.send_result(msg["id"], await rt.async_walk_test(msg["minutes"]))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "failed", str(err))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/end_fast", vol.Required("deveui"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_end_fast(hass: HomeAssistant, connection, msg: dict) -> None:
    rt = _runtime(hass, _norm(msg["deveui"]))
    if rt is None:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return
    try:
        connection.send_result(msg["id"], {"restored": await rt.async_end_walk_test()})
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "failed", str(err))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/save", vol.Required("deveui"): str,
                                  vol.Required("samples"): list, vol.Optional("spot"): str,
                                  vol.Optional("note"): str})
@websocket_api.require_admin
@callback
def ws_save(hass: HomeAssistant, connection, msg: dict) -> None:
    """Keep the walk-test result on the device (attribute of Signal quality, diagnostics)."""
    rt = _runtime(hass, _norm(msg["deveui"]))
    summary = walk_summary(msg["samples"][-200:])
    result = {"at": time.time(), "spot": (msg.get("spot") or "").strip() or None,
              "note": (msg.get("note") or "").strip() or None, **summary,
              "by": connection.user.name if connection.user else None}
    if rt is not None:
        rt.save_commissioning(result)
    connection.send_result(msg["id"], {"saved": rt is not None, "result": result})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/location", vol.Required("deveui"): str,
                                  vol.Optional("latitude"): vol.Any(None, float, int),
                                  vol.Optional("longitude"): vol.Any(None, float, int),
                                  vol.Optional("accuracy"): vol.Any(None, float, int)})
@websocket_api.require_admin
@callback
def ws_location(hass: HomeAssistant, connection, msg: dict) -> None:
    """Fixed location of a device (the phone's GPS where the installer stands), or clear it (no latitude)."""
    deveui = _norm(msg["deveui"])
    entry = next((e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_DEVEUI) == deveui), None)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Add the device to Home Assistant first")
        return
    lat, lon = msg.get("latitude"), msg.get("longitude")
    opts = {k: v for k, v in entry.options.items() if k != "location"}
    if lat is not None and lon is not None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            connection.send_error(msg["id"], "invalid", "Coordinates out of range")
            return
        opts["location"] = {"latitude": round(float(lat), 6), "longitude": round(float(lon), 6),
                            "accuracy": round(float(msg["accuracy"])) if msg.get("accuracy") is not None else None,
                            "at": time.time(), "by": connection.user.name if connection.user else None}
    hass.config_entries.async_update_entry(entry, options=opts)      # the device reloads with its Location entity
    connection.send_result(msg["id"], {"location": opts.get("location")})
