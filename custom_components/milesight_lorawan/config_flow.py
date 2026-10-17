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
    AreaSelector,
    AreaSelectorConfig,
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ALERT_ACTION_ENTITY,
    CONF_ALERT_ACTION_TITLE,
    CONF_ALERT_BACKUP,
    CONF_ALERT_CATEGORIES,
    CONF_ALERT_DEDUPE_MIN,
    CONF_ALERT_ESCALATE_MIN,
    CONF_ALERT_PRIMARY,
    CONF_ALERT_QUIET_END,
    CONF_ALERT_QUIET_START,
    CONF_ALERT_REPEAT_MIN,
    CONF_ALERT_RESOLVED,
    CONF_APP_KEY,
    CONF_CHANNEL_MAP,
    CONF_NS_APP_KEY,
    CONF_NS_APPLICATION,
    CONF_NS_FPORT,
    CONF_NS_GATEWAY_EUI,
    CONF_NS_PROFILE,
    CONF_NS_REQUEST_TOPIC,
    CONF_NS_RESPONSE_TOPIC,
    CONF_REGISTER,
    CONF_TANK_CAPACITY,
    CONF_TANK_CONE,
    CONF_TANK_DENSITY,
    CONF_TANK_DIAMETER,
    CONF_TANK_DROP_MIN,
    CONF_TANK_DROP_PCT,
    CONF_TANK_HEIGHT,
    CONF_TANK_LENGTH,
    CONF_TANK_LOW_PCT,
    CONF_TANK_PROBE_OFFSET,
    CONF_TANK_REFILL_PCT,
    CONF_TANK_SHAPE,
    CONF_TANK_WIDTH,
    DEFAULT_NS_REQUEST_TOPIC,
    DEFAULT_NS_RESPONSE_TOPIC,
    CONF_AUTO_BACKFILL,
    CONF_CO2_ALERT,
    CONF_SITE_ADDRESS,
    CONF_SITE_AREAS,
    CONF_SITE_COMPANY,
    CONF_SITE_CONTACT,
    CONF_SITE_EMAIL,
    CONF_SITE_LOGO,
    CONF_SITE_OUTSIDE,
    CONF_SITE_PHONE,
    CONF_UPDATE_DASHBOARD,
    DEFAULT_CO2_ALERT,
    DEFAULT_SITE_LOGO,
    CONF_CONFIRMED_DOWNLINKS,
    CONF_DISPLAY_MAX_BYTES,
    CONF_EXTRA_TOPICS,
    CONF_GATEWAY_OFFLINE_MIN,
    CONF_RETRIES,
    DEFAULT_DISPLAY_MAX_BYTES,
    DEFAULT_GATEWAY_OFFLINE_MIN,
    DEFAULT_RETRIES,
    CONF_METER_OFFSET,
    CONF_METER_PPU,
    CONF_METER_SOURCE,
    CONF_METER_TYPE,
    CONF_METER_UNIT,
    METER_TYPES,
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
from .alerts import CATEGORIES, effective_categories
from .channel_map import parse_channel_map
from .models import (MODELS, downlinks, entity_specs, families, load_channels, parse_bulk, pulse_capable,
                     pump_capable, purposes_for, tank_source)
from . import purposes as _purposes
from .ns_api import DEFAULT_APP_KEY, DEFAULT_FPORT, valid_key
from .tank import SHAPES, capacity_l, tank_config

_DEVEUI_RE = re.compile(r"^[0-9a-f]{16}$")




def _model_selector(order: list[str] | None = None) -> SelectSelector:
    # discovery guesses first, then every model alphabetically (natural order: VS121 before VS1210)
    def natural(k: str) -> list:
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", MODELS[k].label)]
    keys = list(dict.fromkeys([k for k in (order or []) if k in MODELS] + sorted(MODELS, key=natural)))
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
        vol.Optional(CONF_EXTRA_TOPICS, default=opts.get(CONF_EXTRA_TOPICS, "")): TextSelector(),
        vol.Required(CONF_GATEWAY_OFFLINE_MIN, default=opts.get(CONF_GATEWAY_OFFLINE_MIN, DEFAULT_GATEWAY_OFFLINE_MIN)):
            _int_box(2, 1440),
    }


def _schedule_dashboard(hass, entry: ConfigEntry) -> None:
    """Build the dashboard once the entry has (possibly) reloaded with the new options and its sensors exist."""
    from homeassistant.helpers.event import async_call_later

    async def _run(_now) -> None:
        from .dashboard import async_update_dashboard
        try:
            await async_update_dashboard(hass, entry)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("Could not create the building dashboard", exc_info=True)
    async_call_later(hass, 20, _run)


_SITE_KEYS = (CONF_SITE_COMPANY, CONF_SITE_ADDRESS, CONF_SITE_CONTACT, CONF_SITE_PHONE, CONF_SITE_EMAIL, CONF_SITE_LOGO,
              CONF_SITE_AREAS, CONF_SITE_OUTSIDE, CONF_CO2_ALERT)


PUMP_KEYS = ("pump_enabled", "pump_normal_a", "pump_dry_pct", "pump_overload_pct", "pump_max_starts",
             "pump_power_factor", "pump_water_entity")
PIVOT_KEYS = ("pivot_centre", "pivot_sector", "pivot_stall_min")
IRRIGATION_KEYS = ("irr_weather", "irr_soil", "irr_target", "irr_base_minutes", "irr_rain_mm", "irr_rain_hours",
                   "irr_rain_prob", "irr_frost_c")


def _int_box(lo: int, hi: int) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=lo, max=hi, step=1, mode=NumberSelectorMode.BOX))


def _provisioning_hub(hass):
    """The first gateway that can register devices (ns-api set up), or None."""
    for hub in hass.data.get(DOMAIN, {}).get("hubs", {}).values():
        if getattr(hub, "can_provision", False):
            return hub
    return None


def _float_box(lo: float, hi: float, unit: str | None = None, step: Any = "any") -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=lo, max=hi, step=step, mode=NumberSelectorMode.BOX,
                                               unit_of_measurement=unit))


def _purpose_selector(model: str | None = None, load_only: bool = False) -> SelectSelector:
    """Purposes for the model (all when the model is not known yet), grouped by label group."""
    items = purposes_for(model) if model else list(_purposes.PURPOSES.values())
    if load_only:
        items = [p for p in items if "load" in p.families and (p.key in _purposes.LOAD_ANALYTICS or p.key == "pump")]
    opts = [{"value": "none", "label": "– not set –"}] + [
        {"value": p.key, "label": f"{p.label}" + (f"  ·  {_purposes.GROUPS[p.group][0].split('· ')[1]}"
                                                   if p.group else "")} for p in items]
    return SelectSelector(SelectSelectorConfig(options=opts, mode=SelectSelectorMode.DROPDOWN))


def _device_title(name: str | None, model: str | None, deveui: str) -> str:
    return name or f"{model or 'Milesight'} {deveui[-4:].upper()}"


async def _provision_many(hub, devices: list[dict]) -> str:
    """Register devices on the gateway, four at a time. Returns a summary line for the result dialog."""
    import asyncio
    sem = asyncio.Semaphore(4)
    added, existed, failed = 0, 0, []

    async def one(dev: dict) -> None:
        nonlocal added, existed
        async with sem:
            try:
                r = await hub.async_provision(dev[CONF_DEVEUI], dev.get("name") or
                                              _device_title(None, dev[CONF_MODEL], dev[CONF_DEVEUI]),
                                              dev.get(CONF_APP_KEY))
            except Exception as err:  # noqa: BLE001
                failed.append(f"{dev[CONF_DEVEUI].upper()}: {err}")
                return
            if r == "exists":
                existed += 1
            else:
                added += 1
    await asyncio.gather(*(one(d) for d in devices))
    text = f"\n\nGateway: {added} registered, {existed} already registered"
    if failed:
        text += f", {len(failed)} failed:\n" + "\n".join(f"- {f}" for f in failed[:10])
    return text


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
        placeholders = {"error": ""}
        if user_input is not None:
            deveui = re.sub(r"[^0-9a-fA-F]", "", user_input[CONF_DEVEUI]).lower()
            key = re.sub(r"\s", "", user_input.get(CONF_APP_KEY) or "")
            if not _DEVEUI_RE.match(deveui):
                errors[CONF_DEVEUI] = "invalid_deveui"
            elif key and not valid_key(key):
                errors[CONF_APP_KEY] = "invalid_app_key"
            else:
                await self.async_set_unique_id(deveui)
                self._abort_if_unique_id_configured()
                hub = _provisioning_hub(self.hass)
                if hub is not None and user_input.get(CONF_REGISTER):
                    try:
                        await hub.async_provision(deveui, user_input.get("name") or
                                                  _device_title(None, user_input[CONF_MODEL], deveui), key or None)
                    except Exception as err:  # noqa: BLE001 - shown in the form
                        errors["base"] = "provision_failed"
                        placeholders["error"] = str(err)
                if not errors:
                    return self._create_device(deveui, user_input[CONF_MODEL], user_input.get("name"),
                                               user_input.get(CONF_AREA), user_input.get("purpose"))
        schema = {
            vol.Required(CONF_DEVEUI, default=(user_input or {}).get(CONF_DEVEUI, "")): TextSelector(),
            vol.Required(CONF_MODEL, default=(user_input or {}).get(CONF_MODEL, vol.UNDEFINED)): _model_selector(),
            vol.Optional("name", description={"suggested_value": (user_input or {}).get("name")}): TextSelector(),
            vol.Optional(CONF_AREA, description={"suggested_value": (user_input or {}).get(CONF_AREA)}): TextSelector(),
            vol.Optional("purpose", description={"suggested_value": (user_input or {}).get("purpose")}):
                _purpose_selector(),
        }
        hub = _provisioning_hub(self.hass)
        if hub is not None:
            schema[vol.Required(CONF_REGISTER, default=(user_input or {}).get(CONF_REGISTER, True))] = BooleanSelector()
            key_now = (user_input or {}).get(CONF_APP_KEY) if user_input else (hub.ns_app_key or DEFAULT_APP_KEY)
            schema[vol.Optional(CONF_APP_KEY, description={"suggested_value": key_now})] = \
                TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
        return self.async_show_form(step_id="manual", errors=errors, description_placeholders=placeholders,
                                    data_schema=vol.Schema(schema))

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
                gateway = ""
                hub = _provisioning_hub(self.hass)
                if hub is not None and user_input.get(CONF_REGISTER):
                    gateway = await _provision_many(hub, new)
                for dev in new:
                    dev = {k: v for k, v in dev.items() if k != CONF_APP_KEY}
                    self.hass.async_create_task(self.hass.config_entries.flow.async_init(
                        DOMAIN, context={"source": SOURCE_IMPORT}, data=dev))
                return self.async_abort(reason="bulk_done", description_placeholders={
                    "count": str(len(new)), "skipped": str(len(devices) - len(new)), "gateway": gateway})
        schema = {vol.Required("devices", default=(user_input or {}).get("devices", "")):
                  TextSelector(TextSelectorConfig(multiline=True))}
        if _provisioning_hub(self.hass) is not None:
            schema[vol.Required(CONF_REGISTER, default=(user_input or {}).get(CONF_REGISTER, True))] = BooleanSelector()
        return self.async_show_form(step_id="bulk", errors=errors, description_placeholders=placeholders,
                                    data_schema=vol.Schema(schema))

    async def async_step_import(self, data: dict[str, Any]) -> ConfigFlowResult:
        """One device from the bulk list."""
        await self.async_set_unique_id(data[CONF_DEVEUI])
        self._abort_if_unique_id_configured()
        return self._create_device(data[CONF_DEVEUI], data[CONF_MODEL], data.get("name"), data.get(CONF_AREA),
                                   data.get("purpose"))

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
            return self._create_device(deveui, user_input[CONF_MODEL], user_input.get("name"), user_input.get(CONF_AREA),
                                       user_input.get("purpose"))

        candidates = self._disc.get("candidates") or []
        schema = vol.Schema({
            vol.Required(CONF_MODEL, default=guess or next(iter(MODELS))): _model_selector(candidates),
            vol.Optional("name", default=_device_title(self._disc.get("device_name"), guess, deveui)): TextSelector(),
            vol.Optional(CONF_AREA): TextSelector(),
            vol.Optional("purpose"): _purpose_selector(),
        })
        return self.async_show_form(step_id="confirm", data_schema=schema, description_placeholders={
            "deveui": deveui.upper(),
            "guess": guess or "unknown",
            "candidates": ", ".join(candidates) if candidates else "-",
        })

    def _create_device(self, deveui: str, model: str, name: str | None, area: str | None = None,
                       purpose: str | None = None) -> ConfigFlowResult:
        data = {CONF_ENTRY_TYPE: ENTRY_TYPE_DEVICE, CONF_DEVEUI: deveui, CONF_MODEL: model}
        if area:
            data[CONF_AREA] = area.strip()
        if purpose in _purposes.PURPOSES and _purposes.PURPOSES[purpose].families & families(model):
            data["purpose"] = purpose
        return self.async_create_entry(title=_device_title(name, model, deveui), data=data)

    # ---------------------------------------------------------------- options
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MilesightOptionsFlow()


class MilesightOptionsFlow(OptionsFlow):
    async def async_step_connection(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Gateway: MQTT topics, formats, gateway offline time."""
        entry = self.config_entry
        if user_input is not None:
            return self.async_create_entry(data={**entry.options, **user_input})
        opts = {**entry.data, **entry.options}
        return self.async_show_form(step_id="connection", data_schema=vol.Schema(_hub_schema(opts)))

    async def async_step_site(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Gateway: site information for the banner and the Building dashboard."""
        entry = self.config_entry
        if user_input is not None:
            update = bool(user_input.pop(CONF_UPDATE_DASHBOARD, False))
            data = {k: v for k, v in entry.options.items() if k not in _SITE_KEYS}
            data.update({k: v for k, v in user_input.items() if v not in (None, "", [])})
            data[CONF_SITE_LOGO] = user_input.get(CONF_SITE_LOGO) or ""      # cleared logo stays cleared
            if update:
                _schedule_dashboard(self.hass, entry)
            return self.async_create_entry(data=data)
        o = entry.options

        def sv(key: str, default: Any = None) -> dict:
            return {"suggested_value": o.get(key, default)}
        schema = {
            vol.Optional(CONF_SITE_COMPANY, description=sv(CONF_SITE_COMPANY)): TextSelector(),
            vol.Optional(CONF_SITE_CONTACT, description=sv(CONF_SITE_CONTACT)):
                EntitySelector(EntitySelectorConfig(domain="person")),
            vol.Optional(CONF_SITE_ADDRESS, description=sv(CONF_SITE_ADDRESS)): TextSelector(),
            vol.Optional(CONF_SITE_PHONE, description=sv(CONF_SITE_PHONE)):
                TextSelector(TextSelectorConfig(type=TextSelectorType.TEL)),
            vol.Optional(CONF_SITE_EMAIL, description=sv(CONF_SITE_EMAIL)):
                TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
            vol.Optional(CONF_SITE_LOGO, description=sv(CONF_SITE_LOGO, DEFAULT_SITE_LOGO)): TextSelector(),
            vol.Optional(CONF_SITE_AREAS, description=sv(CONF_SITE_AREAS, [])):
                AreaSelector(AreaSelectorConfig(multiple=True)),
            vol.Optional(CONF_SITE_OUTSIDE, description=sv(CONF_SITE_OUTSIDE)):
                EntitySelector(EntitySelectorConfig(domain=["sensor", "weather"])),
            vol.Required(CONF_CO2_ALERT, default=o.get(CONF_CO2_ALERT, DEFAULT_CO2_ALERT)): _int_box(600, 5000),
            vol.Required(CONF_UPDATE_DASHBOARD, default=True): BooleanSelector(),
        }
        hass_name = self.hass.config.location_name
        return self.async_show_form(step_id="site", data_schema=vol.Schema(schema),
                                    description_placeholders={"ha_name": hass_name or "Home"})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return self.async_show_menu(step_id="init", menu_options=["site", "alerts", "irrigation", "provisioning",
                                                                      "connection"])
        model = entry.options.get(CONF_MODEL, entry.data[CONF_MODEL])
        sections = ((["purpose"] if purposes_for(model) else [])
                    + (["channels"] if MODELS[model].dynamic else []) + (["tank"] if tank_source(model) else [])
                    + (["pump"] if pump_capable(model) else []) + (["pivot"] if "at101" in MODELS[model].features else []))
        if sections:
            return self.async_show_menu(step_id="init", menu_options=["general", *sections])
        return await self.async_step_general()

    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Device: model, offline time, battery, meters, door / occupancy / CO₂ settings …"""
        entry = self.config_entry
        if user_input is not None:
            return self.async_create_entry(data={**entry.options, **user_input})
        opts = {**entry.data, **entry.options}
        model = opts.get(CONF_MODEL, entry.data[CONF_MODEL])
        features = MODELS[model].features
        schema = {
            vol.Required(CONF_MODEL, default=model): _model_selector(),
            vol.Required(CONF_MAX_GAP_MIN, default=opts.get(CONF_MAX_GAP_MIN, DEFAULT_MAX_GAP_MIN)): _int_box(5, 1440),
        }
        if pulse_capable(model):
            schema[vol.Required(CONF_METER_TYPE, default=opts.get(CONF_METER_TYPE, "none"))] = SelectSelector(
                SelectSelectorConfig(options=METER_TYPES, translation_key="meter_type"))
            schema[vol.Optional(CONF_METER_UNIT, default=opts.get(CONF_METER_UNIT, "m³"))] = SelectSelector(
                SelectSelectorConfig(options=["L", "m³", "gal", "ft³", "kWh", "Wh"]))
            schema[vol.Optional(CONF_METER_PPU, default=opts.get(CONF_METER_PPU, 1))] = NumberSelector(
                NumberSelectorConfig(min=0.0001, max=1_000_000, step="any", mode=NumberSelectorMode.BOX))
            schema[vol.Optional(CONF_METER_OFFSET, default=opts.get(CONF_METER_OFFSET, 0))] = NumberSelector(
                NumberSelectorConfig(min=0, max=100_000_000, step="any", mode=NumberSelectorMode.BOX))
            schema[vol.Optional(CONF_METER_SOURCE, default=opts.get(CONF_METER_SOURCE, ""))] = TextSelector()
        if downlinks(model):
            schema[vol.Required(CONF_CONFIRMED_DOWNLINKS, default=opts.get(CONF_CONFIRMED_DOWNLINKS, False))] = \
                BooleanSelector()
            schema[vol.Required(CONF_RETRIES, default=opts.get(CONF_RETRIES, DEFAULT_RETRIES))] = _int_box(0, 5)
        if "ds3604" in features:
            schema[vol.Required(CONF_DISPLAY_MAX_BYTES, default=opts.get(CONF_DISPLAY_MAX_BYTES,
                                                                         DEFAULT_DISPLAY_MAX_BYTES))] = _int_box(11, 242)
        hist = downlinks(model).get("history") or {}
        if hist.keys() & {"fetch", "fetch_since"}:
            schema[vol.Required(CONF_AUTO_BACKFILL, default=opts.get(CONF_AUTO_BACKFILL, True))] = BooleanSelector()
        if "battery" in {sp.key for sp in entity_specs(model)}:
            schema[vol.Required(CONF_BATTERY_LOW, default=opts.get(CONF_BATTERY_LOW, DEFAULT_BATTERY_LOW))] = _int_box(1, 99)
        if "door" in features and opts.get("purpose") in (None, "", "none"):
            schema[vol.Required(CONF_LEFT_OPEN_MIN, default=opts.get(CONF_LEFT_OPEN_MIN, DEFAULT_LEFT_OPEN_MIN))] = \
                _int_box(1, 1440)
        if "em400" in features and not tank_source(model):
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
        return self.async_show_form(step_id="general", data_schema=vol.Schema(schema))

    # ------------------------------------------------- controller channels
    async def async_step_channels(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """UC controllers: name, unit and scale per Modbus register / analog input."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        rt = getattr(entry, "runtime_data", None)
        raw = getattr(rt, "raw", {}) or {}
        seen = sorted(k for k in raw if re.fullmatch(
            r"(modbus_chn_\d+(?:_reg_\d+)?|adc_\d+|adv_\d+|analog_input_\d+|pt100_\d+|gpio_counter_\d+)", k))
        placeholders = {"problems": "", "seen": ", ".join(f"{k} = {raw[k]}" for k in seen[:24]) or
                        "none yet – channels appear after the controller's first report"}
        if user_input is not None:
            text = user_input.get(CONF_CHANNEL_MAP, "") or ""
            _, problems = parse_channel_map(text)
            if problems:
                errors[CONF_CHANNEL_MAP] = "channel_map_invalid"
                placeholders["problems"] = "\n\n" + "\n".join(f"- {p}" for p in problems[:15])
            else:
                return self.async_create_entry(data={**entry.options, CONF_CHANNEL_MAP: text})
        current = (user_input or {}).get(CONF_CHANNEL_MAP, entry.options.get(CONF_CHANNEL_MAP, ""))
        return self.async_show_form(step_id="channels", errors=errors, description_placeholders=placeholders,
                                    data_schema=vol.Schema({
                                        vol.Optional(CONF_CHANNEL_MAP, description={"suggested_value": current}):
                                            TextSelector(TextSelectorConfig(multiline=True)),
                                    }))

    # ---------------------------------------------------------------- tank
    async def async_step_tank(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Level / distance sensors: tank or silo shape and size → litres, usage, days left, refills, theft."""
        entry = self.config_entry
        model = entry.options.get(CONF_MODEL, entry.data[CONF_MODEL])
        src = tank_source(model)
        errors: dict[str, str] = {}
        placeholders = {"capacity": "–"}
        o = {**entry.options, **(user_input or {})}
        if user_input is not None:
            cfg = tank_config(o)
            shape = o.get(CONF_TANK_SHAPE, "none")
            need = {"vertical_cylinder": (cfg.diameter_mm,), "horizontal_cylinder": (cfg.diameter_mm, cfg.length_mm),
                    "rectangular": (cfg.length_mm, cfg.width_mm), "cone_bottom": (cfg.diameter_mm, cfg.cone_mm),
                    "linear": (cfg.capacity_l,)}.get(shape, ())
            if shape != "none" and (cfg.height_mm <= 0 or any(v <= 0 for v in need)):
                errors["base"] = "tank_dimensions"
            elif shape != "none" and src == "distance" and cfg.empty_distance_mm <= 0:
                errors["install_height_mm"] = "tank_empty_distance"
            else:
                return self.async_create_entry(data={**entry.options, **user_input})
        cfg = tank_config(o)
        if cfg.enabled:
            placeholders["capacity"] = f"{capacity_l(cfg):,.0f} L"

        def num(key: str, default: float, lo: float, hi: float, unit: str | None = None) -> None:
            schema[vol.Required(key, default=o.get(key, default))] = _float_box(lo, hi, unit)
        schema: dict = {vol.Required(CONF_TANK_SHAPE, default=o.get(CONF_TANK_SHAPE, "none")): SelectSelector(
            SelectSelectorConfig(options=list(SHAPES), translation_key="tank_shape"))}
        if src == "distance":
            num(CONF_INSTALL_HEIGHT_MM, 0, 0, 30000, "mm")
        num(CONF_TANK_HEIGHT, 0, 0, 30000, "mm")
        num(CONF_TANK_DIAMETER, 0, 0, 30000, "mm")
        num(CONF_TANK_LENGTH, 0, 0, 50000, "mm")
        num(CONF_TANK_WIDTH, 0, 0, 50000, "mm")
        num(CONF_TANK_CONE, 0, 0, 30000, "mm")
        num(CONF_TANK_CAPACITY, 0, 0, 10_000_000, "L")
        if src == "depth":
            num(CONF_TANK_PROBE_OFFSET, 0, 0, 30000, "mm")
        num(CONF_TANK_DENSITY, 0, 0, 3000, "kg/m³")
        num(CONF_TANK_LOW_PCT, 20, 0, 99, "%")
        num(CONF_TANK_REFILL_PCT, 5, 1, 100, "%")
        num(CONF_TANK_DROP_PCT, 0, 0, 100, "%")
        num(CONF_TANK_DROP_MIN, 60, 5, 1440, "min")
        return self.async_show_form(step_id="tank", errors=errors, description_placeholders=placeholders,
                                    data_schema=vol.Schema(schema))

    # ------------------------------------------------------------- purpose
    async def async_step_purpose(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What the device is fitted to (fridge, gate, pump, bin …) – sets labels, looks, defaults and alerts."""
        entry = self.config_entry
        model = entry.options.get(CONF_MODEL, entry.data[CONF_MODEL])
        chans = load_channels(model)
        keys = ["purpose"] + [f"purpose_{n}" for n in range(1, chans + 1)]
        if user_input is not None:
            data = {k: v for k, v in entry.options.items() if k not in keys}
            changed = (user_input.get("purpose") or "none") != \
                (entry.options.get("purpose", entry.data.get("purpose")) or "none")
            for k in keys:
                data[k] = user_input.get(k) or "none"
            if changed:                                    # a new purpose starts from its own defaults
                data = {k: v for k, v in data.items() if not k.startswith("p_")}
            self._pending = data
            if _purposes.setting_fields(data.get("purpose"), families(model)):
                return await self.async_step_purpose_settings()
            return self.async_create_entry(data=data)
        cur = entry.options.get("purpose", entry.data.get("purpose")) or "none"
        schema = {vol.Required("purpose", default=cur): _purpose_selector(model)}
        for n in range(1, chans + 1):
            schema[vol.Required(f"purpose_{n}", default=entry.options.get(f"purpose_{n}") or "none")] = \
                _purpose_selector(model, load_only=True)
        return self.async_show_form(step_id="purpose", data_schema=vol.Schema(schema),
                                    description_placeholders={"model": model})

    async def async_step_purpose_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        data = getattr(self, "_pending", None) or dict(entry.options)
        model = data.get(CONF_MODEL, entry.data[CONF_MODEL])
        purpose = data.get("purpose")
        fields = _purposes.setting_fields(purpose, families(model))
        if "run_w" in fields and "socket" not in MODELS[model].features:
            fields.remove("run_w")
        hours = "after_hours" in fields
        if user_input is not None:
            out = {k: v for k, v in data.items() if not k.startswith("p_")}
            defaults = (_purposes.get(purpose).defaults if _purposes.get(purpose) else {})
            for f in fields:
                v = user_input.get(f"p_{f}")
                if v not in (None, ""):
                    out[f"p_{f}"] = v
                elif f in defaults and f != "after_hours":
                    out[f"p_{f}"] = "off"                  # cleared on purpose: no alarm for this
            if hours:
                for k in (CONF_OPEN_HOUR, CONF_CLOSE_HOUR, CONF_OPEN_DAYS):
                    if k in user_input:
                        out[k] = user_input[k]
            return self.async_create_entry(data=out)
        cfg = _purposes.settings(purpose, data)
        units = {"temp_low": ("°C", -60, 150), "temp_high": ("°C", -60, 150), "temp_delay_min": ("min", 0, 1440),
                 "temp_rise_day": ("°C", 0.5, 50), "left_open_min": ("min", 1, 1440), "max_run_h": ("h", 0, 168),
                 "no_run_h": ("h", 0, 168), "service_h": ("h", 0, 100000), "run_w": ("W", 0, 10000),
                 "bin_depth_mm": ("mm", 100, 5000), "full_pct": ("%", 10, 100),
                 "empty_distance_mm": ("mm", 100, 20000), "rise_cm_h": ("cm/h", 0.5, 500),
                 "co2_limit": ("ppm", 400, 5000), "clean_visits": ("visits", 1, 10000), "latch_min": ("min", 1, 1440)}
        schema: dict = {}
        for f in fields:
            if f == "after_hours":
                schema[vol.Required("p_after_hours", default=bool(cfg.get("after_hours", False)))] = BooleanSelector()
                continue
            unit, lo, hi = units[f]
            schema[vol.Optional(f"p_{f}", description={"suggested_value": cfg.get(f)})] = _float_box(lo, hi, unit)
        # (an emptied box is saved as 'off', so a default limit can be switched off)
        if hours:
            schema.update({
                vol.Required(CONF_OPEN_HOUR, default=data.get(CONF_OPEN_HOUR, DEFAULT_OPEN_HOUR)): _int_box(0, 23),
                vol.Required(CONF_CLOSE_HOUR, default=data.get(CONF_CLOSE_HOUR, DEFAULT_CLOSE_HOUR)): _int_box(1, 24),
                vol.Required(CONF_OPEN_DAYS, default=data.get(CONF_OPEN_DAYS, DEFAULT_OPEN_DAYS)): SelectSelector(
                    SelectSelectorConfig(options=WEEKDAYS, multiple=True, translation_key="weekday")),
            })
        p = _purposes.get(purpose)
        return self.async_show_form(step_id="purpose_settings", data_schema=vol.Schema(schema),
                                    description_placeholders={"purpose": p.label if p else "–"})

    # ---------------------------------------------------------------- pump
    async def async_step_pump(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Current clamps on a pump: run hours, starts per hour, dry-run / overload, water per kWh."""
        entry = self.config_entry
        if user_input is not None:
            data = {k: v for k, v in entry.options.items() if k not in PUMP_KEYS}
            data.update({k: v for k, v in user_input.items() if v not in (None, "")})
            return self.async_create_entry(data=data)
        o = entry.options
        schema = {
            vol.Required("pump_enabled", default=o.get("pump_enabled", False)): BooleanSelector(),
            vol.Required("pump_normal_a", default=o.get("pump_normal_a", 0)): _float_box(0, 5000, "A"),
            vol.Required("pump_dry_pct", default=o.get("pump_dry_pct", 60)): _float_box(10, 99, "%"),
            vol.Required("pump_overload_pct", default=o.get("pump_overload_pct", 125)): _float_box(101, 300, "%"),
            vol.Required("pump_max_starts", default=o.get("pump_max_starts", 6)): _int_box(1, 60),
            vol.Required("pump_power_factor", default=o.get("pump_power_factor", 0.85)): _float_box(0.3, 1),
            vol.Optional("pump_water_entity", description={"suggested_value": o.get("pump_water_entity")}):
                EntitySelector(EntitySelectorConfig(domain="sensor", device_class=["water", "volume"])),
        }
        return self.async_show_form(step_id="pump", data_schema=vol.Schema(schema))

    # --------------------------------------------------------------- pivot
    async def async_step_pivot(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """AT101 on a centre pivot's end tower: where the centre is, how big the round is, when it is stalled."""
        entry = self.config_entry
        if user_input is not None:
            data = {k: v for k, v in entry.options.items() if k not in PIVOT_KEYS}
            if user_input.get("pivot_enabled"):
                c = user_input.get("pivot_centre") or {}
                data.update({"pivot_centre": {"latitude": c.get("latitude"), "longitude": c.get("longitude")},
                             "pivot_sector": user_input.get("pivot_sector", 360),
                             "pivot_stall_min": user_input.get("pivot_stall_min", 30)})
            return self.async_create_entry(data=data)
        o = entry.options
        rt = getattr(entry, "runtime_data", None)
        raw = getattr(rt, "raw", {}) or {}
        centre = o.get("pivot_centre") or {"latitude": self.hass.config.latitude,
                                           "longitude": self.hass.config.longitude}
        schema = {
            vol.Required("pivot_enabled", default=bool(o.get("pivot_centre"))): BooleanSelector(),
            vol.Required("pivot_centre", default=centre): LocationSelector(LocationSelectorConfig(radius=False)),
            vol.Required("pivot_sector", default=o.get("pivot_sector", 360)): _float_box(10, 360, "°"),
            vol.Required("pivot_stall_min", default=o.get("pivot_stall_min", 30)): _int_box(5, 1440),
        }
        last = (f"{raw['latitude']:.6f}, {raw['longitude']:.6f}"
                if isinstance(raw.get("latitude"), (int, float)) and isinstance(raw.get("longitude"), (int, float))
                else "no fix yet")
        return self.async_show_form(step_id="pivot", data_schema=vol.Schema(schema),
                                    description_placeholders={"last_fix": last})

    # ---------------------------------------------------------- irrigation
    async def async_step_irrigation(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Gateway: weather forecast + soil moisture → irrigate or skip, frost warning the evening before."""
        entry = self.config_entry
        if user_input is not None:
            data = {k: v for k, v in entry.options.items() if k not in IRRIGATION_KEYS}
            data.update({k: v for k, v in user_input.items() if v not in (None, "", [])})
            return self.async_create_entry(data=data)
        o = entry.options

        def num(key: str, default: float, lo: float, hi: float, unit: str | None = None) -> None:
            schema[vol.Required(key, default=o.get(key, default))] = _float_box(lo, hi, unit)
        schema: dict = {
            vol.Optional("irr_weather", description={"suggested_value": o.get("irr_weather")}):
                EntitySelector(EntitySelectorConfig(domain="weather")),
            vol.Optional("irr_soil", description={"suggested_value": o.get("irr_soil", [])}):
                EntitySelector(EntitySelectorConfig(domain="sensor", multiple=True)),
        }
        num("irr_target", 30, 1, 100, "%")
        num("irr_base_minutes", 60, 1, 1440, "min")
        num("irr_rain_mm", 5, 0.1, 200, "mm")
        num("irr_rain_hours", 24, 1, 72, "h")
        num("irr_rain_prob", 60, 0, 100, "%")
        num("irr_frost_c", 2, -10, 10, "°C")
        return self.async_show_form(step_id="irrigation", data_schema=vol.Schema(schema))

    # -------------------------------------------------- alert escalation
    async def async_step_alerts(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Gateway: who gets alerts, when to escalate, quiet hours."""
        entry = self.config_entry
        keys = (CONF_ALERT_PRIMARY, CONF_ALERT_BACKUP, CONF_ALERT_ESCALATE_MIN, CONF_ALERT_REPEAT_MIN,
                CONF_ALERT_QUIET_START, CONF_ALERT_QUIET_END, CONF_ALERT_DEDUPE_MIN, CONF_ALERT_RESOLVED,
                CONF_ALERT_CATEGORIES, CONF_ALERT_ACTION_ENTITY, CONF_ALERT_ACTION_TITLE)
        if user_input is not None:
            data = {k: v for k, v in entry.options.items() if k not in keys}
            data.update({k: v for k, v in user_input.items() if v not in (None, "")})
            data["alert_categories_known"] = list(CATEGORIES)      # categories added later start switched on
            return self.async_create_entry(data=data)
        o = entry.options
        services = sorted(f"notify.{s}" for s in self.hass.services.async_services().get("notify", {})
                          if s not in ("send_message",))
        notify = SelectSelector(SelectSelectorConfig(options=services, multiple=True, custom_value=True,
                                                     mode=SelectSelectorMode.DROPDOWN))

        def sv(key: str, default: Any = None) -> dict:
            return {"suggested_value": o.get(key, default)}
        schema = {
            vol.Optional(CONF_ALERT_PRIMARY, description=sv(CONF_ALERT_PRIMARY, [])): notify,
            vol.Optional(CONF_ALERT_BACKUP, description=sv(CONF_ALERT_BACKUP, [])): notify,
            vol.Required(CONF_ALERT_ESCALATE_MIN, default=o.get(CONF_ALERT_ESCALATE_MIN, 15)): _int_box(1, 1440),
            vol.Required(CONF_ALERT_REPEAT_MIN, default=o.get(CONF_ALERT_REPEAT_MIN, 0)): _int_box(0, 1440),
            vol.Optional(CONF_ALERT_QUIET_START, description=sv(CONF_ALERT_QUIET_START)): _int_box(0, 23),
            vol.Optional(CONF_ALERT_QUIET_END, description=sv(CONF_ALERT_QUIET_END)): _int_box(0, 23),
            vol.Required(CONF_ALERT_DEDUPE_MIN, default=o.get(CONF_ALERT_DEDUPE_MIN, 30)): _int_box(0, 1440),
            vol.Required(CONF_ALERT_RESOLVED, default=o.get(CONF_ALERT_RESOLVED, True)): BooleanSelector(),
            vol.Required(CONF_ALERT_CATEGORIES, default=list(effective_categories(dict(o)))):
                SelectSelector(SelectSelectorConfig(options=list(CATEGORIES), multiple=True,
                                                    translation_key="alert_category")),
            vol.Optional(CONF_ALERT_ACTION_ENTITY, description=sv(CONF_ALERT_ACTION_ENTITY)):
                EntitySelector(EntitySelectorConfig(domain=["switch", "script", "button", "input_boolean"])),
            vol.Optional(CONF_ALERT_ACTION_TITLE, description=sv(CONF_ALERT_ACTION_TITLE, "Start pump")): TextSelector(),
        }
        return self.async_show_form(step_id="alerts", data_schema=vol.Schema(schema))

    # ------------------------------------------------ gateway provisioning
    async def async_step_provisioning(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Gateway: the ns-api request / response topics, tested by reading the gateway's device list."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        o = entry.options
        keys = (CONF_NS_REQUEST_TOPIC, CONF_NS_RESPONSE_TOPIC, CONF_NS_GATEWAY_EUI, CONF_NS_APP_KEY, CONF_NS_FPORT,
                CONF_NS_APPLICATION, CONF_NS_PROFILE)
        if user_input is not None:
            req = (user_input.get(CONF_NS_REQUEST_TOPIC) or "").strip()
            resp = (user_input.get(CONF_NS_RESPONSE_TOPIC) or "").strip()
            key = re.sub(r"\s", "", user_input.get(CONF_NS_APP_KEY) or "")
            if not req:                                    # switched off
                return self.async_create_entry(data={k: v for k, v in o.items() if k not in keys})
            if not resp or resp == req:
                errors[CONF_NS_RESPONSE_TOPIC] = "ns_topics"
            elif key and not valid_key(key):
                errors[CONF_NS_APP_KEY] = "invalid_app_key"
            else:
                from .provisioning import NsApiClient
                client = NsApiClient(self.hass, req, resp, (user_input.get(CONF_NS_GATEWAY_EUI) or "").strip())
                try:
                    overview = await client.async_overview()
                except Exception as err:  # noqa: BLE001 - shown in the form
                    errors["base"] = "ns_no_answer"
                    placeholders["error"] = str(err)
                else:
                    self._ns = {**user_input, CONF_NS_REQUEST_TOPIC: req, CONF_NS_RESPONSE_TOPIC: resp,
                                CONF_NS_APP_KEY: key or DEFAULT_APP_KEY, "_overview": overview}
                    return await self.async_step_provisioning_target()
                finally:
                    await client.async_stop()
        cur = {**o, **(user_input or {})}

        def sv(key: str, default: Any = None) -> dict:
            return {"suggested_value": cur.get(key, default)}
        schema = {
            vol.Optional(CONF_NS_REQUEST_TOPIC, description=sv(CONF_NS_REQUEST_TOPIC, DEFAULT_NS_REQUEST_TOPIC)):
                TextSelector(),
            vol.Optional(CONF_NS_RESPONSE_TOPIC, description=sv(CONF_NS_RESPONSE_TOPIC, DEFAULT_NS_RESPONSE_TOPIC)):
                TextSelector(),
            vol.Optional(CONF_NS_GATEWAY_EUI, description=sv(CONF_NS_GATEWAY_EUI)): TextSelector(),
            vol.Optional(CONF_NS_APP_KEY, description=sv(CONF_NS_APP_KEY, DEFAULT_APP_KEY)):
                TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            vol.Required(CONF_NS_FPORT, default=cur.get(CONF_NS_FPORT, DEFAULT_FPORT)): _int_box(1, 223),
        }
        return self.async_show_form(step_id="provisioning", errors=errors, description_placeholders=placeholders,
                                    data_schema=vol.Schema(schema))

    async def async_step_provisioning_target(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the gateway application and device profile new devices are added to."""
        entry = self.config_entry
        ns = self._ns
        ov = ns["_overview"]
        if user_input is not None:
            data = {**entry.options, **{k: v for k, v in ns.items() if not k.startswith("_")}, **user_input}
            return self.async_create_entry(data=data)
        apps = ov.get("applications") or {}
        profiles = ov.get("profiles") or {}
        default_profile = entry.options.get(CONF_NS_PROFILE) or next(
            (pid for pid, name in profiles.items() if name.lower().replace("-", "").replace("_", "") == "classaotaa"),
            next(iter(profiles), vol.UNDEFINED))
        default_app = entry.options.get(CONF_NS_APPLICATION) or next(iter(apps), vol.UNDEFINED)

        def sel(options: dict[str, str]) -> SelectSelector:
            return SelectSelector(SelectSelectorConfig(
                options=[SelectOptionDict(value=k, label=v) for k, v in options.items()], custom_value=True,
                mode=SelectSelectorMode.DROPDOWN))
        return self.async_show_form(step_id="provisioning_target", data_schema=vol.Schema({
            vol.Required(CONF_NS_APPLICATION, default=default_app): sel(apps),
            vol.Required(CONF_NS_PROFILE, default=default_profile): sel(profiles),
        }), description_placeholders={"devices": str(len(ov.get("devices") or [])),
                                      "apps": str(len(apps)), "profiles": str(len(profiles))})
