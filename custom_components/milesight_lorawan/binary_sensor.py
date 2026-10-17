"""Binary sensor platform."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE, ENTRY_TYPE_HUB
from .entity import MilesightEntity, setup_platform_entities
from .gateway import async_setup_gateway_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
        async_setup_gateway_entities(hass, entry, async_add_entities, "binary_sensor")
        from .irrigation_ha import irrigation_entities
        async_add_entities(irrigation_entities(hass, entry, "binary_sensor"))
        return
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "binary_sensor", MilesightBinarySensor)


class MilesightBinarySensor(MilesightEntity, BinarySensorEntity):
    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        if spec.device_class:
            self._attr_device_class = BinarySensorDeviceClass(spec.device_class)

    @property
    def extra_state_attributes(self):
        return self.runtime.attrs.get(self.spec.key)

    @property
    def is_on(self) -> bool | None:
        v = self.raw_value
        return None if v is None else bool(v)
