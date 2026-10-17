"""Shared entity base."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, SIGNAL_UPDATE
from .models import EntitySpec, dynamic_spec, entity_specs
from .runtime import DeviceRuntime


class MilesightEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: DeviceRuntime, spec: EntitySpec) -> None:
        self.runtime = runtime
        self.spec = spec
        self._attr_unique_id = f"{runtime.deveui}_{spec.key}"
        self._attr_name = spec.name
        if spec.icon:
            self._attr_icon = spec.icon
        if spec.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = spec.enabled_default
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.deveui)},
            name=runtime.entry.title,
            manufacturer=MANUFACTURER,
            model=runtime.model.key,
            serial_number=runtime.deveui.upper(),
            sw_version=runtime.raw.get("firmware_version"),
            hw_version=runtime.raw.get("hardware_version"),
            suggested_area=runtime.entry.data.get("area"),
        )

    @property
    def raw_value(self):
        return self.runtime.values.get(self.spec.key)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_UPDATE.format(self.runtime.deveui), self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


def setup_platform_entities(entry, async_add_entities, platform: str, factory) -> None:
    """Add the model's fixed entities, plus – for controllers with configurable channels –
    entities for every channel as soon as it first reports (no 'unknown' placeholders)."""
    runtime: DeviceRuntime = entry.runtime_data
    added: set[str] = set()
    all_fixed = [runtime.adjust_spec(s) for s in entity_specs(runtime.model.key) + runtime.extra_specs()]
    fixed = [s for s in all_fixed if s.platform == platform]
    added.update(s.key for s in all_fixed)       # keys owned by any platform are never added dynamically
    async_add_entities(factory(runtime, s) for s in fixed)
    if not runtime.model.dynamic:
        return

    @callback
    def _discover() -> None:
        new = []
        for key in list(runtime.values):
            if key in added:
                continue
            spec = dynamic_spec(key)
            if spec is None or spec.platform != platform:
                continue
            added.add(key)
            new.append(factory(runtime, spec))
        if new:
            async_add_entities(new)

    entry.async_on_unload(async_dispatcher_connect(
        runtime.hass, SIGNAL_UPDATE.format(runtime.deveui), _discover))
    _discover()
