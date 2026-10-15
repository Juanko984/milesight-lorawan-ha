"""Button platform: device commands (reboot, sync time, request update)."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
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
    setup_platform_entities(entry, async_add_entities, "button", MilesightCommandButton)


class MilesightCommandButton(MilesightEntity, ButtonEntity):
    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        if spec.device_class:
            self._attr_device_class = ButtonDeviceClass(spec.device_class)

    async def async_added_to_hass(self) -> None:
        """Buttons have no state to follow."""

    async def async_press(self) -> None:
        command = self.spec.key.removeprefix("cmd_")
        try:
            await self.runtime.async_command(command)
        except Exception as err:  # noqa: BLE001 - surface MQTT / config problems in the UI
            raise HomeAssistantError(f"Could not send {command} to {self.runtime.entry.title}: {err}") from err
