"""Milesight LoRaWAN integration.

A *hub* entry subscribes to the gateway's MQTT uplink topic. Unknown DevEUIs
are offered as discovered devices; each confirmed device becomes its own entry.
"""
from __future__ import annotations

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.storage import Store

from .const import CONF_DEVEUI, CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB, STORAGE_VERSION
from .hub import Hub
from .runtime import DeviceRuntime

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER]


def _is_hub(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {"hubs": {}})

    if _is_hub(entry):
        if not await mqtt.async_wait_for_mqtt_client(hass):
            raise ConfigEntryNotReady("MQTT integration is not available")
        hub = Hub(hass, entry)
        await hub.async_start()
        entry.runtime_data = hub
        domain_data["hubs"][entry.entry_id] = hub
        entry.async_on_unload(entry.add_update_listener(_async_reload))
        return True

    runtime = DeviceRuntime(hass, entry)
    await runtime.async_load()
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    runtime.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if _is_hub(entry):
        await entry.runtime_data.async_stop()
        hass.data.get(DOMAIN, {}).get("hubs", {}).pop(entry.entry_id, None)
        return True

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up stored analytics and allow re-discovery when a device is deleted."""
    if _is_hub(entry):
        return
    deveui = entry.data[CONF_DEVEUI]
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{deveui}").async_remove()
    for hub in hass.data.get(DOMAIN, {}).get("hubs", {}).values():
        hub.forget(deveui)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
