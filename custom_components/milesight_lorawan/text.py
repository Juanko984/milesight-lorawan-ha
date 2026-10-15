"""Text platform: DS3604 e-ink display blocks (text 1-10 and QR code of both templates)."""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DISPLAY_MAX_BYTES, CONF_ENTRY_TYPE, DEFAULT_DISPLAY_MAX_BYTES, ENTRY_TYPE_DEVICE
from .entity import MilesightEntity, setup_platform_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "text", DisplayText)


class DisplayText(MilesightEntity, TextEntity):
    """Shows what the display reports (or what was last sent); setting it sends the block to the display."""

    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 255

    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        tpl, _, block = spec.key.removeprefix("display_t").partition("_")
        self._template, self._block = int(tpl), block
        # one block = 4 header bytes + text in one downlink (characters can be up to 3 UTF-8 bytes)
        limit = int(runtime.entry.options.get(CONF_DISPLAY_MAX_BYTES, DEFAULT_DISPLAY_MAX_BYTES))
        self._attr_native_max = max(1, min(255, limit - 4))

    @property
    def native_value(self) -> str | None:
        return self.raw_value

    async def async_set_value(self, value: str) -> None:
        try:
            await self.runtime.async_display(self._template, {self._block: value})
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Could not update {self.name} on {self.runtime.entry.title}: {err}") from err
