"""Config flow: gateway setup, device auto-discovery, manual add, options."""
from __future__ import annotations

import re
from typing import Any

try:  # Home Assistant 2026.x replaced voluptuous with probatio (same API)
    import probatio as vol
except ImportError:  # older Home Assistant
    import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
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
    TextSelectorConfig,
)

from .const import (
    CONF_AREA,
    CONF_BATTERY_LOW,
    DEFAULT_BATTERY_LOW,
    CONF_CLOSE_HOUR,
    CONF_CO2_LIMIT,
    CONF_INSTALL_HEIGHT_MM,
    CONF_MAINS_VOLTAGE,
    CONF_RUN_THRESHOLD_A,
    CONF_DEVEUI,
    CONF_DOWNLINK_FORMAT,
    CONF_DOWNLINK_TOPIC,
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
    DEFAULT_DOWNLINK_TOPIC,
    DOWNLINK_CHIRPSTACK,
    DOWNLINK_MILESIGHT,
    DEFAULT_CO2_LIMIT,
    DEFAULT_EMPTY_GRACE_MIN,
    DEFAULT_LEFT_OPEN_MIN,
    DEFAULT_MAX_GAP_MIN,
    DEFAULT_OPEN_DAYS,
    DEFAULT_OPEN_HOUR,
    DEFAULT_RUN_THRESHOLD_A,
    DEFAULT_TOPIC,
    DOMAIN,
    ENCODING_BASE64,
    ENCODING_HEX,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_HUB,
    WEEKDAYS,
)
from .models import MODELS, entity_specs, parse_bulk

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


def _downlink_format_selector() -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(
        options=[SelectOptionDict(value=DOWNLINK_MILESIGHT, label="Milesight gateway"),
                 SelectOptionDict(value=DOWNLINK_CHIRPSTACK, label="ChirpStack v4")],
        mode=SelectSelectorMode.DROPDOWN,
    ))


def _hub_schema(opts: dict) -> dict:
    return {
        vol.Required(CONF_TOPIC, default=opts.get(CONF_TOPIC, DEFAULT_TOPIC)): TextSelector(),
        vol.Required(CONF_PAYLOAD_ENCODING, default=opts.get(CONF_PAYLOAD_ENCODING, ENCODING_BASE64)):
            _encoding_selector(),
        vol.Required(CONF_DOWNLINK_TOPIC, default=opts.get(CONF_DOWNLINK_TOPIC, DEFAULT_DOWNLINK_TOPIC)): TextSelector(),
        vol.Required(CONF_DOWNLINK_FORMAT, default=opts.get(CONF_DOWNLINK_FORMAT, DOWNLINK_MILESIGHT)):
            _downlink_format_selector(),
    }


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
        return self.async_show_menu(step_id="user", menu_options=["manual", "bulk", "hub"])

    async def async_step_hub(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            topic = user_input[CONF_TOPIC].strip()
            await self.async_set_unique_id(f"hub:{topic}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Milesight gateway ({topic})",
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_HUB, **user_input, CONF_TOPIC: topic},
            )
        return self.async_show_form(step_id="hub", data_schema=vol.Schema(_hub_schema({})))

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            deveui = re.sub(r"[^0-9a-fA-F]", "", user_input[CONF_DEVEUI]).lower()
            if not _DEVEUI_RE.match(deveui):
                errors[CONF_DEVEUI] = "invalid_deveui"
            else:
                await self.async_set_unique_id(deveui)
                self._abort_if_unique_id_configured()
                return self._create_device(deveui, user_input[CONF_MODEL], user_input.get("name"),
                                           user_input.get(CONF_AREA))
        return self.async_show_form(step_id="manual", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_DEVEUI): TextSelector(),
            vol.Required(CONF_MODEL): _model_selector(),
            vol.Optional("name"): TextSelector(),
            vol.Optional(CONF_AREA): TextSelector(),
        }))

    async def async_step_bulk(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"problems": ""}
        if user_input is not None:
            devices, problems = parse_bulk(user_input["devices"])
            existing = {e.unique_id for e in self._async_current_entries()}
            new = [d for d in devices if d[CONF_DEVEUI] not in existing]
            if problems:
                errors["devices"] = "bulk_invalid"
                placeholders["problems"] = "\n".join(f"- {p}" for p in problems[:15])
            elif not new:
                errors["devices"] = "bulk_nothing_new"
            else:
                for dev in new:
                    self.hass.async_create_task(self.hass.config_entries.flow.async_init(
                        DOMAIN, context={"source": SOURCE_IMPORT}, data=dev))
                return self.async_abort(reason="bulk_done", description_placeholders={
                    "count": str(len(new)), "skipped": str(len(devices) - len(new))})
        return self.async_show_form(step_id="bulk", errors=errors, description_placeholders=placeholders,
                                    data_schema=vol.Schema({
                                        vol.Required("devices", default=(user_input or {}).get("devices", "")):
                                            TextSelector(TextSelectorConfig(multiline=True)),
                                    }))

    async def async_step_import(self, data: dict[str, Any]) -> ConfigFlowResult:
        """One device from the bulk list."""
        await self.async_set_unique_id(data[CONF_DEVEUI])
        self._abort_if_unique_id_configured()
        return self._create_device(data[CONF_DEVEUI], data[CONF_MODEL], data.get("name"), data.get(CONF_AREA))

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
            return self._create_device(deveui, user_input[CONF_MODEL], user_input.get("name"), user_input.get(CONF_AREA))

        candidates = self._disc.get("candidates") or []
        schema = vol.Schema({
            vol.Required(CONF_MODEL, default=guess or next(iter(MODELS))): _model_selector(candidates),
            vol.Optional("name", default=_device_title(self._disc.get("device_name"), guess, deveui)): TextSelector(),
            vol.Optional(CONF_AREA): TextSelector(),
        })
        return self.async_show_form(step_id="confirm", data_schema=schema, description_placeholders={
            "deveui": deveui.upper(),
            "guess": guess or "unknown",
            "candidates": ", ".join(candidates) if candidates else "-",
        })

    def _create_device(self, deveui: str, model: str, name: str | None, area: str | None = None) -> ConfigFlowResult:
        data = {CONF_ENTRY_TYPE: ENTRY_TYPE_DEVICE, CONF_DEVEUI: deveui, CONF_MODEL: model}
        if area:
            data[CONF_AREA] = area.strip()
        return self.async_create_entry(title=_device_title(name, model, deveui), data=data)

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
            return self.async_show_form(step_id="init", data_schema=vol.Schema(_hub_schema(opts)))

        model = opts.get(CONF_MODEL, entry.data[CONF_MODEL])
        features = MODELS[model].features
        schema = {
            vol.Required(CONF_MODEL, default=model): _model_selector(),
            vol.Required(CONF_MAX_GAP_MIN, default=opts.get(CONF_MAX_GAP_MIN, DEFAULT_MAX_GAP_MIN)): _int_box(5, 1440),
        }
        if "battery" in {sp.key for sp in entity_specs(model)}:
            schema[vol.Required(CONF_BATTERY_LOW, default=opts.get(CONF_BATTERY_LOW, DEFAULT_BATTERY_LOW))] = _int_box(1, 99)
        if "door" in features:
            schema[vol.Required(CONF_LEFT_OPEN_MIN, default=opts.get(CONF_LEFT_OPEN_MIN, DEFAULT_LEFT_OPEN_MIN))] = \
                _int_box(1, 1440)
        if "em400" in features:
            schema[vol.Required(CONF_INSTALL_HEIGHT_MM, default=opts.get(CONF_INSTALL_HEIGHT_MM, 0))] = \
                _int_box(0, 20000)
        if "load" in features:
            schema[vol.Required(CONF_RUN_THRESHOLD_A, default=opts.get(CONF_RUN_THRESHOLD_A, DEFAULT_RUN_THRESHOLD_A))] = \
                NumberSelector(NumberSelectorConfig(min=0, max=5000, step=0.1, mode=NumberSelectorMode.BOX,
                                                    unit_of_measurement="A"))
            schema[vol.Required(CONF_MAINS_VOLTAGE, default=opts.get(CONF_MAINS_VOLTAGE, 0))] = _int_box(0, 1000)
        if "co2high" in features:
            schema[vol.Required(CONF_CO2_LIMIT, default=opts.get(CONF_CO2_LIMIT, DEFAULT_CO2_LIMIT))] = \
                _int_box(400, 5000)
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
