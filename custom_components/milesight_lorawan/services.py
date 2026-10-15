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

    hass.services.async_register(DOMAIN, SERVICE_SEND_DOWNLINK, _send, schema=SEND_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DISPLAY, _display, schema=DISPLAY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_OUTPUT_COMMAND, _output, schema=OUTPUT_SCHEMA)
