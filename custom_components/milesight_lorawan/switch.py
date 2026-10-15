"""Switch platform (WS wall switches, sockets and light controllers – controlled via downlinks)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
from .entity import MilesightEntity, setup_platform_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "switch", MilesightSwitch)


class MilesightSwitch(MilesightEntity, SwitchEntity):
    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        if spec.device_class:
            self._attr_device_class = SwitchDeviceClass(spec.device_class)

    @property
    def is_on(self) -> bool | None:
        v = self.raw_value
        return None if v is None else bool(v)

    async def _set(self, on: bool) -> None:
        try:
            if self.runtime.model.control:
                await self.runtime.async_set_switch(self.spec.key, on)
            else:                                    # UC outputs / valves, GS101 valve / relay
                await self.runtime.async_output(self.spec.key, "on" if on else "off")
        except Exception as err:  # noqa: BLE001 - surface MQTT / config problems in the UI
            raise HomeAssistantError(f"Could not send command to {self.runtime.entry.title}: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
