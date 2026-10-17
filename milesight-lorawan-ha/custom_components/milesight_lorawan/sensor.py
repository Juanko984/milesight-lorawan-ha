"""Sensor platform."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
from .entity import MilesightEntity
from .models import entity_specs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    runtime = entry.runtime_data
    async_add_entities(
        MilesightSensor(runtime, spec)
        for spec in entity_specs(runtime.model.key) if spec.platform == "sensor"
    )


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
        return v
