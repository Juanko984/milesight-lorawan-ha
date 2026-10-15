"""Climate platform (WT thermostats and radiator valves – controlled via downlinks)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
from .decoders import WT_FAN_CODES
from .entity import MilesightEntity, setup_platform_entities

# Home Assistant 2026.x renamed the temperature properties to native_*; support both.
_NATIVE = hasattr(ClimateEntity, "native_target_temperature")

# encoder kind -> HA mode -> device mode name (None = power off)
HVAC_MAP: dict[str, dict[HVACMode, str | None]] = {
    "wt101": {HVACMode.HEAT: "heat", HVACMode.OFF: None},
    "wt102": {HVACMode.HEAT: "heat", HVACMode.OFF: None},
    "wt201": {HVACMode.HEAT: "heat", HVACMode.COOL: "cool", HVACMode.HEAT_COOL: "auto", HVACMode.OFF: None},
    "wt201v2": {HVACMode.HEAT: "heat", HVACMode.COOL: "cool", HVACMode.HEAT_COOL: "auto", HVACMode.OFF: None},
    "wt30x": {HVACMode.HEAT: "heat", HVACMode.COOL: "cool", HVACMode.FAN_ONLY: "fan", HVACMode.OFF: None},
    "wt303": {HVACMode.HEAT: "heat", HVACMode.COOL: "cool", HVACMode.FAN_ONLY: "ventilation", HVACMode.OFF: None},
    "wt401": {HVACMode.HEAT: "heat", HVACMode.COOL: "cool", HVACMode.HEAT_COOL: "auto",
              HVACMode.DRY: "dehumidify", HVACMode.FAN_ONLY: "ventilation", HVACMode.OFF: None},
}
STEP = {"wt101": 1.0, "wt201": 0.5, "wt201v2": 0.5, "wt30x": 0.5}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "climate", MilesightClimate)


def _mode_to_hvac(kind: str, mode: Any) -> HVACMode | None:
    if mode == "em heat":
        return HVACMode.HEAT
    for hvac, name in HVAC_MAP[kind].items():
        if name is not None and name == mode:
            return hvac
    return None


class MilesightClimate(MilesightEntity, ClimateEntity):
    _attr_min_temp = 5
    _attr_max_temp = 35
    if _NATIVE:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        self.kind: str = runtime.model.climate
        self._attr_name = None                       # the device itself
        self._attr_hvac_modes = list(HVAC_MAP[self.kind])
        self._attr_target_temperature_step = STEP.get(self.kind, 0.5)
        features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if self.kind in WT_FAN_CODES:
            features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = list(WT_FAN_CODES[self.kind])
        self._attr_supported_features = features

    # ---------------------------------------------------------------- state
    @property
    def _v(self) -> dict:
        return self.runtime.values

    def _current(self) -> float | None:
        return self._v.get("temperature")

    def _target(self) -> float | None:
        v = self._v
        mode = v.get("temperature_control_mode")
        if self.kind == "wt303":
            key = "cooling_target_temperature" if mode == "cool" else "heating_target_temperature"
            return v.get(key, v.get("target_temperature"))
        if self.kind == "wt401" and mode == "cool" and v.get("target_temperature_2") is not None:
            return v.get("target_temperature_2")
        return v.get("target_temperature")

    if _NATIVE:
        @property
        def native_current_temperature(self) -> float | None:
            return self._current()

        @property
        def native_target_temperature(self) -> float | None:
            return self._target()
    else:
        @property
        def current_temperature(self) -> float | None:
            return self._current()

        @property
        def target_temperature(self) -> float | None:
            return self._target()

    @property
    def current_humidity(self) -> float | None:
        return self._v.get("humidity")

    @property
    def _is_on(self) -> bool:
        v = self._v
        if v.get("system_status") is False or v.get("temperature_control_mode") == "off":
            return False
        return v.get("climate_on", True) is not False

    @property
    def hvac_mode(self) -> HVACMode | None:
        if not self._is_on:
            return HVACMode.OFF
        mode = self._v.get("mode" if self.kind == "wt30x" else "temperature_control_mode")
        if self.kind in ("wt101", "wt102"):
            return HVACMode.HEAT
        return _mode_to_hvac(self.kind, mode)

    @property
    def hvac_action(self) -> HVACAction | None:
        if not self._is_on:
            return HVACAction.OFF
        v = self._v
        status = v.get("temperature_control_status")
        if isinstance(status, str):
            if "heat" in status:
                return HVACAction.HEATING
            if "cool" in status:
                return HVACAction.COOLING
            return HVACAction.IDLE
        if isinstance(v.get("valve_opening"), (int, float)):
            return HVACAction.HEATING if v["valve_opening"] > 0 else HVACAction.IDLE
        return None

    @property
    def fan_mode(self) -> str | None:
        fan = self._v.get("fan_speed" if self.kind == "wt30x" else "fan_mode")
        return fan if fan in (self._attr_fan_modes or []) else None

    # -------------------------------------------------------------- control
    async def _send(self, action: str, value: Any, **kw: Any) -> None:
        try:
            await self.runtime.async_climate(action, value, **kw)
        except Exception as err:  # noqa: BLE001 - surface MQTT / config problems in the UI
            raise HomeAssistantError(f"Could not send command to {self.runtime.entry.title}: {err}") from err

    def _device_mode(self) -> str:
        mode = self._v.get("mode" if self.kind == "wt30x" else "temperature_control_mode")
        valid = [m for m in HVAC_MAP[self.kind].values() if m]
        return mode if mode in valid or mode == "em heat" else valid[0]

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (t := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._send("target", float(t), mode=self._device_mode())

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        name = HVAC_MAP[self.kind].get(hvac_mode)
        if name is None:
            await self._send("power", False, mode=self._device_mode(), target=self._target())
            return
        if self.kind in ("wt101", "wt102"):
            await self._send("power", True)
            return
        if self.kind == "wt201v2":                   # one command sets power + mode + target
            await self._send("mode", name, target=self._target(), on=True)
            return
        if not self._is_on:
            await self._send("power", True)
        await self._send("mode", name)

    async def async_turn_on(self) -> None:
        if self.kind == "wt201v2":
            await self._send("power", True, mode=self._device_mode(), target=self._target())
        else:
            await self._send("power", True)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._send("fan", fan_mode)
