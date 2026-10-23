"""Services: raw downlinks and timed output / valve commands."""
from __future__ import annotations

import re

try:  # Home Assistant 2026.x replaced voluptuous with probatio (same API)
    import probatio as vol
except ImportError:  # older Home Assistant
    import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import CONF_DEVEUI, DOMAIN

SERVICE_SEND_DOWNLINK = "send_downlink"
SERVICE_OUTPUT_COMMAND = "output_command"
SERVICE_DISPLAY = "display_content"
SERVICE_ACK = "acknowledge_alert"
SERVICE_SNOOZE = "snooze_alert"
SERVICE_PROVISION = "add_to_gateway"
SERVICE_DEPROVISION = "remove_from_gateway"
SERVICE_SYNC = "sync_gateway_devices"
SERVICE_TANK_REFILLED = "tank_refilled"
SERVICE_LOG = "log_service"
SERVICE_BATTERY = "battery_replaced"
SERVICE_PROFILE = "apply_settings_profile"
SERVICE_HANDOVER = "handover_report"
SERVICE_COMPLIANCE = "compliance_report"
SERVICE_CONFIGURE_GW = "configure_gateway"
SERVICE_FORGET_GW = "forget_gateway"
DISPLAY_BLOCKS = [f"text_{n}" for n in range(1, 11)] + ["qrcode"]
ACTIONS = ["on", "off", "on_for", "off_for", "open_for", "open_until_pulses", "set"]

SEND_SCHEMA = vol.Schema({
    vol.Required("device_id"): cv.string,
    vol.Required("payload"): cv.string,
    vol.Optional("fport"): vol.All(vol.Coerce(int), vol.Range(min=1, max=223)),
})
OUTPUT_SCHEMA = vol.Schema({
    vol.Required("device_id"): cv.string,
    vol.Required("output"): cv.string,
    vol.Required("action"): vol.In(ACTIONS),
    vol.Optional("value"): vol.Coerce(float),
})

DISPLAY_SCHEMA = vol.Schema({
    vol.Required("device_id"): vol.Any(cv.string, [cv.string]),
    vol.Optional("template", default=1): vol.All(vol.Coerce(int), vol.In([1, 2])),
    **{vol.Optional(b): cv.string for b in DISPLAY_BLOCKS},
    vol.Optional("content"): vol.Any(None, {vol.In(DISPLAY_BLOCKS): vol.Any(None, cv.string)}),
    vol.Optional("force", default=False): cv.boolean,
    vol.Optional("show", default=True): cv.boolean,
    vol.Optional("refresh", default=False): cv.boolean,
    vol.Optional("beep", default=False): cv.boolean,
})


ACK_SCHEMA = vol.Schema({vol.Optional("alert_id"): cv.string})
SNOOZE_SCHEMA = vol.Schema({vol.Required("alert_id"): cv.string,
                            vol.Optional("minutes"): vol.All(vol.Coerce(float), vol.Range(min=1, max=1440))})
PROVISION_SCHEMA = vol.Schema({
    vol.Required("deveui"): cv.string,
    vol.Optional("name"): cv.string,
    vol.Optional("app_key"): cv.string,
    vol.Optional("profile_id"): cv.string,
})
DEPROVISION_SCHEMA = vol.Schema({vol.Required("deveui"): cv.string})
TANK_SCHEMA = vol.Schema({vol.Required("device_id"): vol.Any(cv.string, [cv.string])})
LOG_SCHEMA = vol.Schema({vol.Required("device_id"): vol.Any(cv.string, [cv.string]),
                         vol.Required("note"): cv.string,
                         vol.Optional("kind", default="maintenance"): vol.In(["maintenance", "battery_replaced",
                                                                             "firmware", "note",
                                                                             "corrective_action"])})
COMPLIANCE_SCHEMA = vol.Schema({vol.Optional("period", default="week"): vol.In(["week", "month", "custom"]),
                                vol.Optional("start"): cv.datetime, vol.Optional("end"): cv.datetime,
                                vol.Optional("device_id"): vol.Any(cv.string, [cv.string]),
                                vol.Optional("send", default=True): cv.boolean})
PROFILE_SCHEMA = vol.Schema({vol.Required("profile"): cv.string,
                             vol.Required("device_id"): vol.Any(cv.string, [cv.string]),
                             vol.Optional("include_channels", default=True): cv.boolean,
                             vol.Optional("send_to_devices", default=True): cv.boolean})


def _hubs(hass: HomeAssistant, provisioning: bool = False) -> list:
    hubs = list(hass.data.get(DOMAIN, {}).get("hubs", {}).values())
    if provisioning:
        hubs = [h for h in hubs if h.ns is not None]
        if not hubs:
            raise ServiceValidationError("Set up 'Add devices to the gateway' in the gateway's options first")
    return hubs


def _eui(text: str) -> str:
    eui = re.sub(r"[^0-9a-fA-F]", "", text).lower()
    if len(eui) != 16:
        raise ServiceValidationError(f"'{text}' is not a 16-digit DevEUI")
    return eui


def _runtime(hass: HomeAssistant, device_id: str):
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"Unknown device {device_id}")
    deveuis = {ident for domain, ident in device.identifiers if domain == DOMAIN}
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_DEVEUI) in deveuis and getattr(entry, "runtime_data", None) is not None:
            return entry.runtime_data
    raise ServiceValidationError("This device is not a Milesight LoRaWAN device (or it is not loaded)")


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEND_DOWNLINK):
        return

    async def _send(call: ServiceCall) -> None:
        rt = _runtime(hass, call.data["device_id"])
        hexstr = re.sub(r"[^0-9a-fA-F]", "", call.data["payload"])
        if not hexstr or len(hexstr) % 2:
            raise ServiceValidationError("payload must be hex bytes, e.g. ff10ff")
        try:
            await rt.async_send_raw(bytes.fromhex(hexstr), call.data.get("fport"))
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err

    async def _output(call: ServiceCall) -> None:
        rt = _runtime(hass, call.data["device_id"])
        try:
            await rt.async_output(call.data["output"], call.data["action"], call.data.get("value"))
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err

    async def _display(call: ServiceCall) -> None:
        ids = call.data["device_id"]
        for device_id in ids if isinstance(ids, list) else [ids]:
            rt = _runtime(hass, device_id)
            blocks = {k: v for k, v in (call.data.get("content") or {}).items() if v is not None}
            blocks.update({b: call.data[b] for b in DISPLAY_BLOCKS if b in call.data})
            try:
                await rt.async_display(call.data["template"], blocks, show=call.data["show"],
                                       refresh=call.data["refresh"], beep=call.data["beep"],
                                       only_changed=not call.data["force"])
            except ValueError as err:
                raise ServiceValidationError(str(err)) from err
            except Exception as err:  # noqa: BLE001
                raise HomeAssistantError(str(err)) from err

    async def _ack(call: ServiceCall) -> None:
        user = None
        if call.context.user_id:
            u = await hass.auth.async_get_user(call.context.user_id)
            user = u.name if u else None
        for hub in _hubs(hass):
            await hub.alerts.async_acknowledge(call.data.get("alert_id"), user)

    async def _snooze(call: ServiceCall) -> None:
        user = None
        if call.context.user_id:
            u = await hass.auth.async_get_user(call.context.user_id)
            user = u.name if u else None
        for hub in _hubs(hass):
            await hub.alerts.async_snooze(call.data["alert_id"], user, call.data.get("minutes"))

    async def _provision(call: ServiceCall) -> dict:
        from .ns_api import valid_key
        key = call.data.get("app_key")
        if key and not valid_key(key):
            raise ServiceValidationError("app_key must be 32 hex digits")
        hubs = [h for h in _hubs(hass, True) if h.can_provision]
        if not hubs:
            raise ServiceValidationError("Pick the gateway application and profile under 'Add devices to the gateway'")
        eui = _eui(call.data["deveui"])
        try:
            result = await hubs[0].async_provision(eui, call.data.get("name"), key, call.data.get("profile_id"))
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        return {"result": result}

    async def _deprovision(call: ServiceCall) -> dict:
        hub = _hubs(hass, True)[0]
        eui = _eui(call.data["deveui"])
        try:
            removed = await hub.ns.async_remove_device(eui)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        if "devices" in hub.gateway_devices:
            hub.gateway_devices["devices"] = [d for d in hub.gateway_devices["devices"] if d["deveui"] != eui]
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            from .const import SIGNAL_GATEWAY
            async_dispatcher_send(hass, SIGNAL_GATEWAY.format(hub.entry.entry_id))
        return {"removed": removed}

    async def _sync(call: ServiceCall) -> dict:
        out = {}
        for hub in _hubs(hass, True):
            try:
                data = await hub.async_sync_devices()
            except Exception as err:  # noqa: BLE001
                raise HomeAssistantError(str(err)) from err
            out[hub.entry.title] = len(data["devices"])
        return {"devices": out}

    async def _tank(call: ServiceCall) -> None:
        ids = call.data["device_id"]
        for device_id in ids if isinstance(ids, list) else [ids]:
            try:
                _runtime(hass, device_id).tank_refilled()
            except ValueError as err:
                raise ServiceValidationError(str(err)) from err

    async def _user(call: ServiceCall) -> str | None:
        if call.context and call.context.user_id:
            u = await hass.auth.async_get_user(call.context.user_id)
            return u.name if u else None
        return None

    async def _log(call: ServiceCall) -> None:
        by = await _user(call)
        ids = call.data["device_id"]
        for device_id in ids if isinstance(ids, list) else [ids]:
            rt = _runtime(hass, device_id)
            if call.data["kind"] == "battery_replaced":
                rt.battery_replaced(by)
                if call.data["note"]:
                    rt.log_service("note", call.data["note"], by)
            else:
                rt.log_service(call.data["kind"], call.data["note"], by)

    async def _battery(call: ServiceCall) -> None:
        by = await _user(call)
        ids = call.data["device_id"]
        for device_id in ids if isinstance(ids, list) else [ids]:
            _runtime(hass, device_id).battery_replaced(by)

    async def _profile(call: ServiceCall) -> dict:
        from .maintenance_ha import async_apply_profile, async_profiles
        prof = (await async_profiles(hass)).get(call.data["profile"])
        if prof is None:
            raise ServiceValidationError(f"No settings profile '{call.data['profile']}'")
        by = await _user(call)
        out = {}
        ids = call.data["device_id"]
        for device_id in ids if isinstance(ids, list) else [ids]:
            rt = _runtime(hass, device_id)
            try:
                out[rt.entry.title] = await async_apply_profile(hass, prof, rt.entry, call.data["include_channels"],
                                                                call.data["send_to_devices"], by)
            except ValueError as err:
                raise ServiceValidationError(str(err)) from err
        return {"applied": out}

    async def _handover(call: ServiceCall) -> dict:
        from .maintenance_ha import async_handover_report, first_hub_entry
        hub = first_hub_entry(hass)
        if hub is None:
            raise ServiceValidationError("No Milesight gateway set up")
        return await async_handover_report(hass, hub)

    async def _compliance(call: ServiceCall) -> dict:
        from .maintenance_ha import first_hub_entry
        hub = first_hub_entry(hass)
        if hub is None:
            raise ServiceValidationError("No Milesight gateway set up")
        period = call.data["period"]
        start, end = call.data.get("start"), call.data.get("end")
        if period == "custom" and (start is None or end is None or end <= start):
            raise ServiceValidationError("A custom period needs a start and an end after it")
        ids = call.data.get("device_id")
        try:
            out = await hub.runtime_data.compliance.async_create(
                period, start if period == "custom" else None, end if period == "custom" else None,
                device_ids=(ids if isinstance(ids, list) else [ids]) if ids else None, send=call.data["send"],
                by=await _user(call))
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        return {"period": out["period"], "sent_to": out["sent_to"],
                "reports": [{k: r[k] for k in ("unit", "status", "url", "excursions", "out_min", "coverage")}
                            for r in out["reports"]]}

    async def _configure_gateway(call: ServiceCall) -> dict:
        from .gateway_api import GatewayError, run_gateway_config
        try:
            return await run_gateway_config(
                hass, call.data["host"], call.data["username"], call.data["password"],
                mode=call.data["mode"], band=call.data["band"],
                mqtt_user=call.data.get("mqtt_user"), mqtt_password=call.data.get("mqtt_password"))
        except GatewayError as err:
            raise ServiceValidationError(str(err)) from err

    from homeassistant.core import SupportsResponse
    async def _forget_gateway(call: ServiceCall) -> dict:
        from .gateway_discovery import norm_hex
        eui = norm_hex(call.data["gateway_eui"])
        removed = [h.entry.title for h in _hubs(hass) if hasattr(h, "forget_gateway") and h.forget_gateway(eui)]
        if not removed:
            raise ServiceValidationError(f"No gateway {eui.upper()} is known")
        return {"forgotten": eui.upper(), "from": removed}

    hass.services.async_register(DOMAIN, SERVICE_FORGET_GW, _forget_gateway, schema=vol.Schema(
        {vol.Required("gateway_eui"): cv.string}), supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_CONFIGURE_GW, _configure_gateway, schema=vol.Schema({
        vol.Required("host"): cv.string, vol.Required("username", default="admin"): cv.string,
        vol.Required("password"): cv.string, vol.Required("mode", default="lns"): vol.In(["lns", "mqtt", "both"]),
        vol.Optional("band", default="EU868"): cv.string, vol.Optional("mqtt_user"): cv.string,
        vol.Optional("mqtt_password"): cv.string}), supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_COMPLIANCE, _compliance, schema=COMPLIANCE_SCHEMA,
                                 supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_LOG, _log, schema=LOG_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_BATTERY, _battery, schema=TANK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_PROFILE, _profile, schema=PROFILE_SCHEMA,
                                 supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_HANDOVER, _handover, schema=vol.Schema({}),
                                 supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_ACK, _ack, schema=ACK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SNOOZE, _snooze, schema=SNOOZE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_PROVISION, _provision, schema=PROVISION_SCHEMA,
                                 supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_DEPROVISION, _deprovision, schema=DEPROVISION_SCHEMA,
                                 supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_SYNC, _sync, schema=vol.Schema({}),
                                 supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_TANK_REFILLED, _tank, schema=TANK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_DOWNLINK, _send, schema=SEND_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DISPLAY, _display, schema=DISPLAY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_OUTPUT_COMMAND, _output, schema=OUTPUT_SCHEMA)
