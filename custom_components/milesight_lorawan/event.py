"""Event platform (WS buttons and scene panels)."""
from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE, SIGNAL_EVENT
from .entity import MilesightEntity, setup_platform_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "event", MilesightButton)


class MilesightButton(MilesightEntity, EventEntity):
    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        self._attr_event_types = list(runtime.model.event_types)

    async def async_added_to_hass(self) -> None:
        # no state-update subscription: an event entity only changes when the button is pressed
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_EVENT.format(self.runtime.deveui), self._handle_event))

    @callback
    def _handle_event(self, key: str, event_type: str) -> None:
        if key == self.spec.key and event_type in self._attr_event_types:
            self._trigger_event(event_type)
            self.async_write_ha_state()
