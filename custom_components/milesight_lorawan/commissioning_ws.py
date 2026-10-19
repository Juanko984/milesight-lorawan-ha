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
        for handler in (ws_parse, ws_add_gateway, ws_gateways, ws_configure_gateway, ws_forget_gateway,
                        ws_discovered, ws_ignore,
                        ws_devices, ws_add, ws_watch, ws_fast, ws_end_fast, ws_save, ws_location, ws_phone_location):
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
    """QR text → DevEUI, AppKey, model guess; whether it is already set up and whether the gateway can add it.
    A gateway's code (gateway EUI / MAC) answers {'gateway': {...}} instead."""
    from .gateway_discovery import default_name, parse_gateway_code
    gw = parse_gateway_code(msg["text"])
    if gw is not None:
        known = next((h for h in _hubs(hass) if hasattr(h, "gateway_known") and h.gateway_known(gw["eui"])), None)
        g = (known.stats.gateways.get(gw["eui"]) or known.stats.expected.get(gw["eui"]) or {}) if known else {}
        connection.send_result(msg["id"], {"gateway": {**gw, "known": known is not None, "name": g.get("name"),
                                                       "suggested_name": default_name(gw["eui"], gw.get("model")),
                                                       "heard": any(gw["eui"] in h.stats.gateways for h in _hubs(hass))}})
        return
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


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/commission/add_gateway", vol.Required("eui"): str, vol.Optional("name"): str,
    vol.Optional("area"): str, vol.Optional("model"): str, vol.Optional("mac"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_add_gateway(hass: HomeAssistant, connection, msg: dict) -> None:
    """A gateway scanned in the panel: adopt it now if it already sends, else as soon as it does."""
    from .config_flow import _local_ip
    from .const import CONF_LNS_ENABLED, CONF_LNS_PORT, DEFAULT_LNS_PORT
    from .gateway_discovery import default_name, is_gateway_eui, norm_hex
    eui = norm_hex(msg["eui"])
    if not is_gateway_eui(eui):
        connection.send_error(msg["id"], "invalid", "A gateway EUI is 16 hex digits with FFFE in the middle")
        return
    hubs = [h for h in _hubs(hass) if hasattr(h, "expect_gateway")]
    if not hubs:
        connection.send_error(msg["id"], "no_hub", "Set up Milesight LoRaWAN first")
        return
    hub = next((h for h in hubs if h.entry.options.get(CONF_LNS_ENABLED)), hubs[0])
    name = (msg.get("name") or "").strip() or default_name(eui, msg.get("model"))
    status = hub.expect_gateway(eui, {"name": name, "area": (msg.get("area") or "").strip() or None,
                                      "model": msg.get("model"), "mac": msg.get("mac")})
    lns = bool(hub.entry.options.get(CONF_LNS_ENABLED))
    connection.send_result(msg["id"], {
        "status": status, "name": name, "lns": lns, "ha_ip": await _local_ip(hass),
        "port": int(hub.entry.options.get(CONF_LNS_PORT) or DEFAULT_LNS_PORT)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/gateways"})
@websocket_api.require_admin
@callback
def ws_gateways(hass: HomeAssistant, connection, msg: dict) -> None:
    """Every gateway Home Assistant knows — heard or just announced — with live status, for the Gateways tab."""
    from .const import CONF_GATEWAY_OFFLINE_MIN, DEFAULT_GATEWAY_OFFLINE_MIN
    now = time.time()
    out: dict[str, dict] = {}
    ha_ip = None
    for hub in _hubs(hass):
        offline_s = float(hub.entry.options.get(CONF_GATEWAY_OFFLINE_MIN, DEFAULT_GATEWAY_OFFLINE_MIN)) * 60
        st = getattr(hub, "stats", None)
        if st is None:
            continue
        for gid, g in st.gateways.items():
            info = g.get("info") or {}
            out[gid] = {
                "eui": gid, "name": g.get("name") or gid, "area": g.get("area"), "ip": g.get("ip") or info.get("ip"),
                "model": g.get("model") or info.get("model"), "firmware": info.get("firmware"),
                "online": st.online(gid, now, offline_s), "last_heard": g.get("last_heard"),
                "packets_today": g.get("packets_today", 0), "connection": g.get("found") or (g.get("conn") or [None])[0],
                "approved": bool(g.get("approved")), "heard": True}
        for gid, g in st.expected.items():
            if gid not in out:
                out[gid] = {"eui": gid, "name": g.get("name") or gid, "area": g.get("area"), "ip": g.get("ip"),
                            "model": g.get("model"), "firmware": None, "online": None, "last_heard": None,
                            "packets_today": 0, "connection": None, "approved": False, "heard": False}
    has_mqtt = any(e.state == e.state.LOADED if hasattr(e.state, "LOADED") else True
                   for e in hass.config_entries.async_entries("mqtt"))
    connection.send_result(msg["id"], {
        "gateways": sorted(out.values(), key=lambda x: str(x["name"]).lower()), "now": now,
        "ha_mqtt": bool(hass.config_entries.async_entries("mqtt")), "has_mqtt": has_mqtt})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/commission/configure_gateway", vol.Required("host"): str,
    vol.Optional("username", default="admin"): str, vol.Required("password"): str,
    vol.Optional("mode", default="both"): str, vol.Optional("band", default="EU868"): str,
    vol.Optional("mqtt_user"): str, vol.Optional("mqtt_password"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_configure_gateway(hass: HomeAssistant, connection, msg: dict) -> None:
    """Configure a gateway over the LAN from the panel: log in, point Semtech at HA and/or set up its MQTT
    application. The admin password is sent only to the gateway and never stored or logged."""
    from .gateway_api import GatewayError, run_gateway_config
    if msg["mode"] not in ("lns", "mqtt", "both"):
        connection.send_error(msg["id"], "invalid", "mode must be lns, mqtt or both")
        return
    if not _hubs(hass):
        connection.send_error(msg["id"], "no_hub", "Set up Milesight LoRaWAN first")
        return
    try:
        out = await run_gateway_config(hass, msg["host"].strip(), msg["username"], msg["password"],
                                       mode=msg["mode"], band=msg["band"],
                                       mqtt_user=msg.get("mqtt_user"), mqtt_password=msg.get("mqtt_password"))
    except GatewayError as err:
        connection.send_error(msg["id"], "gateway", str(err))
        return
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "error", str(err))
        return
    connection.send_result(msg["id"], out)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/forget_gateway", vol.Required("eui"): str})
@websocket_api.require_admin
@callback
def ws_forget_gateway(hass: HomeAssistant, connection, msg: dict) -> None:
    from .gateway_discovery import norm_hex
    eui = norm_hex(msg["eui"])
    removed = [h.entry.title for h in _hubs(hass) if hasattr(h, "forget_gateway") and h.forget_gateway(eui)]
    if not removed:
        connection.send_error(msg["id"], "unknown", f"No gateway {eui.upper()} is known")
        return
    connection.send_result(msg["id"], {"forgotten": eui.upper(), "from": removed})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/discovered"})
@websocket_api.require_admin
@callback
def ws_discovered(hass: HomeAssistant, connection, msg: dict) -> None:
    """Everything Home Assistant has auto-discovered but not yet set up — the same items shown under
    Settings → Devices & services → Discovered — so the installer can add them from this panel."""
    from .gateway_discovery import default_name, norm_hex
    from .models import guess_from_name
    mgr = hass.config_entries.flow
    devices: list[dict] = []
    gateways: list[dict] = []
    for flow in list(getattr(mgr, "_progress", {}).values()):
        if getattr(flow, "handler", None) != DOMAIN:
            continue
        ctx = getattr(flow, "context", {}) or {}
        if ctx.get("source") not in ("integration_discovery", "dhcp"):
            continue
        raw = getattr(flow, "init_data", None)
        d = raw if isinstance(raw, dict) else {}
        if not d and raw is not None:                        # a dhcp DhcpServiceInfo object
            d = {"lan": True, "ip": getattr(raw, "ip", None), "mac": getattr(raw, "macaddress", None)}
        uid = ctx.get("unique_id") or ""
        title = (ctx.get("title_placeholders") or {}).get("name")
        fid = flow.flow_id
        if uid.startswith("gateway:") or d.get("gateway_id") or d.get("lan"):
            eui = norm_hex(uid.split(":", 1)[1]) if uid.startswith("gateway:") else norm_hex(str(d.get("gateway_id") or ""))
            gateways.append({"flow_id": fid, "uid": uid or None, "eui": eui or None, "ip": d.get("ip"),
                             "model": d.get("model"), "lan": bool(d.get("lan")),
                             "name": title or (default_name(eui, d.get("model")) if eui else "Gateway")})
        else:
            deveui = norm_hex(str(d.get(CONF_DEVEUI) or uid))
            if len(deveui) != 16:
                continue
            devices.append({"flow_id": fid, "uid": uid or None, "deveui": deveui,
                            "name": d.get("device_name") or title or deveui.upper(),
                            "model": d.get("guess") or guess_from_name(d.get("device_name") or "") or None})
    devices.sort(key=lambda x: str(x["name"]).lower())
    gateways.sort(key=lambda x: str(x["name"]).lower())
    connection.send_result(msg["id"], {"devices": devices, "gateways": gateways})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/ignore",
                                  vol.Required("flow_id"): str, vol.Optional("unique_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_ignore(hass: HomeAssistant, connection, msg: dict) -> None:
    """Dismiss a discovered item from the panel (Home Assistant's 'Ignore')."""
    uid = msg.get("unique_id")
    if uid:
        from homeassistant.config_entries import SOURCE_IGNORE
        try:
            await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IGNORE, "unique_id": uid},
                                                      data={"unique_id": uid, "title": uid})
        except Exception:  # noqa: BLE001 - fall back to just closing the card
            pass
    try:
        hass.config_entries.flow.async_abort(msg["flow_id"])
    except Exception:  # noqa: BLE001 - already gone
        pass
    connection.send_result(msg["id"], {"ok": True})


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
    if lat is not None and lon is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        connection.send_error(msg["id"], "invalid", "Coordinates out of range")
        return
    loc = _save_location(hass, entry, lat, lon, msg.get("accuracy"),
                         connection.user.name if connection.user else None, "browser")
    connection.send_result(msg["id"], {"location": loc})


def _save_location(hass: HomeAssistant, entry, lat, lon, accuracy, by, source: str) -> dict | None:
    opts = {k: v for k, v in entry.options.items() if k != "location"}
    if lat is not None and lon is not None:
        opts["location"] = {"latitude": round(float(lat), 6), "longitude": round(float(lon), 6),
                            "accuracy": round(float(accuracy)) if accuracy is not None else None,
                            "at": time.time(), "by": by, "source": source}
    hass.config_entries.async_update_entry(entry, options=opts)      # the device reloads with its Location entity
    return opts.get("location")


def phone_trackers(hass: HomeAssistant, user_id: str | None) -> list[str]:
    """The Companion-app GPS trackers of this user: the person's device trackers from the mobile_app integration,
    else (no person linked) every mobile_app tracker."""
    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(hass)
    mobile = {e.entity_id for e in reg.entities.values()
              if e.domain == "device_tracker" and e.platform == "mobile_app"}
    mine: list[str] = []
    if user_id:
        for st in hass.states.async_all("person"):
            if st.attributes.get("user_id") == user_id:
                mine = [t for t in st.attributes.get("device_trackers") or [] if t in mobile]
    return mine or sorted(mobile)


def _notify_service(hass: HomeAssistant, tracker: str) -> str | None:
    """notify.mobile_app_<device> of the phone behind a tracker (to ask it for a fresh position)."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from homeassistant.util import slugify
    ent = er.async_get(hass).async_get(tracker)
    dev = dr.async_get(hass).async_get(ent.device_id) if ent and ent.device_id else None
    if dev is None:
        return None
    name = f"mobile_app_{slugify(dev.name_by_user or dev.name or '')}"
    return name if hass.services.has_service("notify", name) else None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/commission/phone_location",
                                  vol.Required("deveui"): str, vol.Optional("save", default=True): bool})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_phone_location(hass: HomeAssistant, connection, msg: dict) -> None:
    """The phone's position from the Home Assistant app's own location tracking (works where the page itself may
    not read GPS, e.g. Home Assistant reached over http://). Asks the phone for a fresh fix first."""
    import asyncio
    deveui = _norm(msg["deveui"])
    entry = next((e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_DEVEUI) == deveui), None)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Add the device to Home Assistant first")
        return
    user_id = connection.user.id if connection.user else None
    trackers = phone_trackers(hass, user_id)
    if not trackers:
        connection.send_error(msg["id"], "no_phone", "No Home Assistant app with location found for your user – "
                              "turn on location in the app (App settings → Location) or link your phone to your person.")
        return
    before = {t: (hass.states.get(t).last_updated if hass.states.get(t) else None) for t in trackers}
    asked = []
    for t in trackers:
        svc = _notify_service(hass, t)
        if svc:
            try:
                await hass.services.async_call("notify", svc, {"message": "request_location_update"}, blocking=True)
                asked.append(t)
            except Exception:  # noqa: BLE001 - use the last known position then
                _LOGGER.debug("Could not ask %s for a location update", svc, exc_info=True)
    if asked:                                         # wait up to 20 s for a fresh fix
        for _ in range(40):
            if any(hass.states.get(t) and hass.states.get(t).last_updated != before[t] for t in asked):
                break
            await asyncio.sleep(0.5)

    def fix(t: str):
        st = hass.states.get(t)
        lat, lon = (st.attributes.get("latitude"), st.attributes.get("longitude")) if st else (None, None)
        return (st, lat, lon) if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else None
    fixes = [f for f in (fix(t) for t in trackers) if f]
    if not fixes:
        connection.send_error(msg["id"], "no_fix", "The Home Assistant app has not reported a position yet.")
        return
    st, lat, lon = max(fixes, key=lambda f: f[0].last_updated)
    acc = st.attributes.get("gps_accuracy")
    age = round(time.time() - st.last_updated.timestamp())
    loc = _save_location(hass, entry, lat, lon, acc, connection.user.name if connection.user else None,
                         st.entity_id) if msg.get("save", True) else None
    connection.send_result(msg["id"], {"latitude": lat, "longitude": lon, "accuracy": acc, "age_s": age,
                                       "tracker": st.entity_id, "fresh": st.entity_id in asked and age < 60,
                                       "location": loc})
