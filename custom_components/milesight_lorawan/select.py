"""Select platform: alarm conditions / modes of device settings."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
from .entity import MilesightEntity, setup_platform_entities
from .models import setting_field


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "select",
                            lambda rt, spec: DisplayTemplateSelect(rt, spec) if spec.key == "display_template"
                            else MilesightSettingSelect(rt, spec))


class DisplayTemplateSelect(MilesightEntity, SelectEntity):
    """DS3604: which of the two templates is shown."""

    _attr_options = ["1", "2"]

    @property
    def current_option(self) -> str | None:
        v = self.runtime.values.get("current_template_id")
        return str(v) if v in (1, 2) else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.runtime.async_display(int(option), {}, show=True)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Could not switch the template on {self.runtime.entry.title}: {err}") from err


class MilesightSettingSelect(MilesightEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        self._setting, field = setting_field(runtime.model.key, spec.key)
        self._field = field["name"]
        self._attr_options = list(field["map"])

    @property
    def current_option(self) -> str | None:
        v = self.raw_value
        return v if v in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.runtime.async_setting(self._setting, self._field, option)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Could not send setting to {self.runtime.entry.title}: {err}") from err
