"""Number platform: reporting / collection interval and proportional valve opening."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE, ENTRY_TYPE_HUB
from .entity import MilesightEntity, setup_platform_entities
from .models import downlinks, output_for_key, setting_field
from . import setpoints as _setpoints


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
        mgr = getattr(getattr(entry, "runtime_data", None), "irrigation", None)
        if mgr is not None and mgr.enabled:
            async_add_entities(HubSetpoint(hass, entry, o) for o in _setpoints.HUB)
        return
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "number", MilesightNumber)


def _save_option(hass: HomeAssistant, entry: ConfigEntry, option: str, value: float) -> None:
    """Write a setpoint into the entry's options (the entry reloads with it)."""
    hass.config_entries.async_update_entry(entry, options={**entry.options, option: value})


class HubSetpoint(NumberEntity):
    """Gateway: irrigation target / base time / frost temperature as a slider."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_mode = NumberMode.SLIDER

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, option: str) -> None:
        from .building import hub_device
        self.hass, self.entry, self.option = hass, entry, option
        sp = _setpoints.HUB[option]
        self._sp = sp
        self._attr_name, self._attr_icon = sp.name, sp.icon
        self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = sp.min, sp.max, sp.step
        self._attr_native_unit_of_measurement = sp.unit
        self._attr_unique_id = f"{entry.entry_id}_{_setpoints.key(option)}"
        self._attr_device_info = hub_device(entry)

    @property
    def native_value(self) -> float | None:
        mgr = getattr(self.entry.runtime_data, "irrigation", None)
        return _setpoints.hub_values(mgr.cfg)[self.option] if mgr is not None else None

    async def async_set_native_value(self, value: float) -> None:
        _save_option(self.hass, self.entry, self.option, _setpoints.clamp(self._sp, value))


class MilesightNumber(MilesightEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        self._setting = None
        self._setpoint = None
        if spec.key.startswith("sp_"):
            sp = _setpoints.DEVICE[spec.key.removeprefix("sp_")]
            self._setpoint, self._command = sp, None
            self._attr_mode = NumberMode.SLIDER
            self._attr_native_min_value, self._attr_native_max_value = sp.min, sp.max
            self._attr_native_step = sp.step
            if sp.unit:
                self._attr_native_unit_of_measurement = sp.unit
            return
        if spec.key.startswith("set_"):
            self._command = None
            self._setting, field = setting_field(runtime.model.key, spec.key)
            self._field = field["name"]
            tmpl = field
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_native_step = 1 / field.get("scale", 1) if field.get("scale", 1) > 1 else 1
        elif spec.key.startswith("cfg_"):
            self._command = spec.key.removeprefix("cfg_")
            tmpl = downlinks(runtime.model.key)[self._command]
            self._attr_entity_category = EntityCategory.CONFIG
        else:
            self._command = None
            tmpl = output_for_key(runtime.model.key, spec.key)["set"]
        self._attr_native_min_value = tmpl.get("min", 0)
        self._attr_native_max_value = tmpl.get("max", 100 if not self._setting else 65535)
        if not self._setting:
            self._attr_native_step = 1
        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit

    @property
    def native_value(self) -> float | None:
        v = self.raw_value
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def extra_state_attributes(self) -> dict | None:
        if self._setpoint is not None or self._setting or not self._command:
            return None
        confirmed = self.runtime.meta.get("confirmed", {}).get(self._command)
        return {"confirmed_by_device": confirmed} if confirmed is not None else None

    async def async_set_native_value(self, value: float) -> None:
        if self._setpoint is not None:
            _save_option(self.hass, self.runtime.entry, self._setpoint.option,
                         _setpoints.clamp(self._setpoint, value))
            return
        try:
            if self._setting:
                step = self._attr_native_step
                await self.runtime.async_setting(self._setting, self._field,
                                                 value if step < 1 else int(value))
            elif self._command:
                await self.runtime.async_command(self._command, int(value))
            else:
                await self.runtime.async_output(self.spec.key, "set", int(value))
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Could not send command to {self.runtime.entry.title}: {err}") from err
