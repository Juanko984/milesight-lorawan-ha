"""Sensor platform."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE, ENTRY_TYPE_HUB
from .entity import MilesightEntity, setup_platform_entities
from .fleet import async_setup_areas, fleet_sensors
from .building import building_sensors
from .gateway import async_setup_gateway_entities, hub_extra_sensors


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
        async_add_entities(fleet_sensors(hass, entry))
        areas = await async_setup_areas(hass, entry, async_add_entities)
        async_setup_gateway_entities(hass, entry, async_add_entities, "sensor")
        hub = entry.runtime_data
        hub.areas = areas
        hub.building, ents = building_sensors(hass, entry, areas)
        async_add_entities(ents)
        async_add_entities(hub_extra_sensors(hass, entry))
        from .irrigation_ha import irrigation_entities
        async_add_entities(irrigation_entities(hass, entry, "sensor"))
        return
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "sensor", MilesightSensor)


class MilesightSensor(MilesightEntity, SensorEntity):
    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        if spec.device_class:
            self._attr_device_class = SensorDeviceClass(spec.device_class)
        if spec.state_class:
            self._attr_state_class = SensorStateClass(spec.state_class)
        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit
        if spec.precision is not None:
            self._attr_suggested_display_precision = spec.precision

    @property
    def extra_state_attributes(self):
        return self.runtime.attrs.get(self.spec.key)

    @property
    def native_value(self) -> float | int | str | datetime | None:
        v = self.raw_value
        if v is None:
            return None
        kind = self.spec.kind
        if kind == "duration":
            return round(v / 60, 2)
        if kind == "timestamp":
            return dt_util.utc_from_timestamp(v)
        if kind == "text":
            return str(v)[:255]
        if kind == "label":
            return str(v).replace("_", " ").capitalize()[:255]
        return v
