"""Config flow: gateway setup, device auto-discovery, manual add, options."""
from __future__ import annotations

import re
from typing import Any

try:  # Home Assistant 2026.x replaced voluptuous with probatio (same API)
    import probatio as vol
except ImportError:  # older Home Assistant
    import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_CLOSE_HOUR,
    CONF_DEVEUI,
    CONF_EMPTY_GRACE_MIN,
    CONF_ENTRY_TYPE,
    CONF_LEFT_OPEN_MIN,
    CONF_MAX_GAP_MIN,
    CONF_MODEL,
    CONF_OPEN_DAYS,
    CONF_OPEN_HOUR,
    CONF_PAYLOAD_ENCODING,
    CONF_TOPIC,
    DEFAULT_CLOSE_HOUR,
    DEFAULT_EMPTY_GRACE_MIN,
    DEFAULT_LEFT_OPEN_MIN,
    DEFAULT_MAX_GAP_MIN,
    DEFAULT_OPEN_DAYS,
    DEFAULT_OPEN_HOUR,
    DEFAULT_TOPIC,
    DOMAIN,
    ENCODING_BASE64,
    ENCODING_HEX,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_HUB,
    WEEKDAYS,
)
from .models import MODELS

_DEVEUI_RE = re.compile(r"^[0-9a-f]{16}$")


def _model_selector(order: list[str] | None = None) -> SelectSelector:
    keys = list(dict.fromkeys((order or []) + list(MODELS)))
    return SelectSelector(SelectSelectorConfig(
        options=[SelectOptionDict(value=k, label=MODELS[k].label) for k in keys],
        mode=SelectSelectorMode.DROPDOWN,
    ))


def _encoding_selector() -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(
        options=[SelectOptionDict(value=ENCODING_BASE64, label="Base64"),
                 SelectOptionDict(value=ENCODING_HEX, label="Hex string")],
        mode=SelectSelectorMode.DROPDOWN,
    ))


def _int_box(lo: int, hi: int) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=lo, max=hi, step=1, mode=NumberSelectorMode.BOX))


def _device_title(name: str | None, model: str | None, deveui: str) -> str:
    return name or f"{model or 'Milesight'} {deveui[-4:].upper()}"


class MilesightConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._disc: dict[str, Any] = {}

    def _hubs(self) -> list[ConfigEntry]:
        return [e for e in self._async_current_entries() if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB]

    # ------------------------------------------------------------ user entry
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not self._hubs():
            return await self.async_step_hub()
        return self.async_show_menu(step_id="user", menu_options=["manual", "hub"])

    async def async_step_hub(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            topic = user_input[CONF_TOPIC].strip()
            await self.async_set_unique_id(f"hub:{topic}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Milesight gateway ({topic})",
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_HUB, CONF_TOPIC: topic,
                      CONF_PAYLOAD_ENCODING: user_input[CONF_PAYLOAD_ENCODING]},
            )
        return self.async_show_form(step_id="hub", data_schema=vol.Schema({
            vol.Required(CONF_TOPIC, default=DEFAULT_TOPIC): TextSelector(),
            vol.Required(CONF_PAYLOAD_ENCODING, default=ENCODING_BASE64): _encoding_selector(),
        }))

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            deveui = re.sub(r"[^0-9a-fA-F]", "", user_input[CONF_DEVEUI]).lower()
            if not _DEVEUI_RE.match(deveui):
                errors[CONF_DEVEUI] = "invalid_deveui"
            else:
                await self.async_set_unique_id(deveui)
                self._abort_if_unique_id_configured()
                return self._create_device(deveui, user_input[CONF_MODEL], user_input.get("name"))
        return self.async_show_form(step_id="manual", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_DEVEUI): TextSelector(),
            vol.Required(CONF_MODEL): _model_selector(),
            vol.Optional("name"): TextSelector(),
        }))

    # ------------------------------------------------------- auto-discovery
    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        deveui = discovery_info[CONF_DEVEUI]
        await self.async_set_unique_id(deveui)
        self._abort_if_unique_id_configured()
        self._disc = discovery_info
        guess = discovery_info.get("guess")
        self.context["title_placeholders"] = {
            "name": _device_title(discovery_info.get("device_name"), guess, deveui),
            "deveui": deveui.upper(),
        }
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        deveui = self._disc[CONF_DEVEUI]
        guess = self._disc.get("guess")
        if user_input is not None:
            return self._create_device(deveui, user_input[CONF_MODEL], user_input.get("name"))

        candidates = self._disc.get("candidates") or []
        schema = vol.Schema({
            vol.Required(CONF_MODEL, default=guess or next(iter(MODELS))): _model_selector(candidates),
            vol.Optional("name", default=_device_title(self._disc.get("device_name"), guess, deveui)): TextSelector(),
        })
        return self.async_show_form(step_id="confirm", data_schema=schema, description_placeholders={
            "deveui": deveui.upper(),
            "guess": guess or "unknown",
            "candidates": ", ".join(candidates) if candidates else "-",
        })

    def _create_device(self, deveui: str, model: str, name: str | None) -> ConfigFlowResult:
        return self.async_create_entry(
            title=_device_title(name, model, deveui),
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_DEVICE, CONF_DEVEUI: deveui, CONF_MODEL: model},
        )

    # ---------------------------------------------------------------- options
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MilesightOptionsFlow()


class MilesightOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = {**entry.data, **entry.options}
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            schema = {
                vol.Required(CONF_TOPIC, default=opts.get(CONF_TOPIC, DEFAULT_TOPIC)): TextSelector(),
                vol.Required(CONF_PAYLOAD_ENCODING, default=opts.get(CONF_PAYLOAD_ENCODING, ENCODING_BASE64)):
                    _encoding_selector(),
            }
            return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

        features = MODELS[entry.data[CONF_MODEL]].features
        schema = {
            vol.Required(CONF_MAX_GAP_MIN, default=opts.get(CONF_MAX_GAP_MIN, DEFAULT_MAX_GAP_MIN)): _int_box(5, 1440),
        }
        if "door" in features:
            schema[vol.Required(CONF_LEFT_OPEN_MIN, default=opts.get(CONF_LEFT_OPEN_MIN, DEFAULT_LEFT_OPEN_MIN))] = \
                _int_box(1, 1440)
        if "occupancy" in features:
            schema.update({
                vol.Required(CONF_EMPTY_GRACE_MIN, default=opts.get(CONF_EMPTY_GRACE_MIN, DEFAULT_EMPTY_GRACE_MIN)):
                    _int_box(0, 60),
                vol.Required(CONF_OPEN_HOUR, default=opts.get(CONF_OPEN_HOUR, DEFAULT_OPEN_HOUR)): _int_box(0, 23),
                vol.Required(CONF_CLOSE_HOUR, default=opts.get(CONF_CLOSE_HOUR, DEFAULT_CLOSE_HOUR)): _int_box(1, 24),
                vol.Required(CONF_OPEN_DAYS, default=opts.get(CONF_OPEN_DAYS, DEFAULT_OPEN_DAYS)): SelectSelector(
                    SelectSelectorConfig(options=WEEKDAYS, multiple=True, translation_key="weekday")),
            })
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
