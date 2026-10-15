"""Number platform: reporting / collection interval and proportional valve opening."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
from .entity import MilesightEntity, setup_platform_entities
from .models import downlinks, output_for_key


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "number", MilesightNumber)


class MilesightNumber(MilesightEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        if spec.key.startswith("cfg_"):
            self._command = spec.key.removeprefix("cfg_")
            tmpl = downlinks(runtime.model.key)[self._command]
            self._attr_entity_category = EntityCategory.CONFIG
        else:
            self._command = None
            tmpl = output_for_key(runtime.model.key, spec.key)["set"]
        self._attr_native_min_value = tmpl.get("min", 0)
        self._attr_native_max_value = tmpl.get("max", 100)
        self._attr_native_step = 1
        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit

    @property
    def native_value(self) -> float | None:
        v = self.raw_value
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            if self._command:
                await self.runtime.async_command(self._command, int(value))
            else:
                await self.runtime.async_output(self.spec.key, "set", int(value))
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Could not send command to {self.runtime.entry.title}: {err}") from err
