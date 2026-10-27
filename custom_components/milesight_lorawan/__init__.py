"""Milesight LoRaWAN integration.

A *hub* entry subscribes to the gateway's MQTT uplink topic. Unknown DevEUIs
are offered as discovered devices; each confirmed device becomes its own entry.
"""
from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DEVEUI, CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB, MANUFACTURER, STORAGE_VERSION
from .hub import Hub
from .runtime import DeviceRuntime
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)
HUB_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]   # fleet, gateway health, dashboard
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.SWITCH, Platform.EVENT, Platform.CLIMATE, Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.TEXT]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_services(hass)
    return True


def _is_hub(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {"hubs": {}})

    if _is_hub(entry):
        from .const import CONF_LNS_ENABLED
        lns_only = bool({**entry.data, **entry.options}.get(CONF_LNS_ENABLED))
        try:
            mqtt_ok = await mqtt.async_wait_for_mqtt_client(hass)
        except Exception:  # noqa: BLE001 - MQTT not set up at all
            mqtt_ok = False
        if not mqtt_ok and not lns_only:
            raise ConfigEntryNotReady("MQTT integration is not available")
        # the gateway devices are linked to the hub device (via_device), so it must exist first
        from homeassistant.helpers import device_registry as dr
        dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id,
                                               identifiers={(DOMAIN, f"hub_{entry.entry_id}")},
                                               name=entry.title, manufacturer=MANUFACTURER, model="LoRaWAN gateway")
        hub = Hub(hass, entry)
        await hub.async_start()
        entry.runtime_data = hub
        domain_data["hubs"][entry.entry_id] = hub
        await hass.config_entries.async_forward_entry_setups(entry, HUB_PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_reload))
        from .dashboard import async_restore_dashboard
        await async_restore_dashboard(hass, entry)
        try:
            from homeassistant.loader import async_get_integration
            from .commissioning_ws import async_setup_panel
            await async_setup_panel(hass, str((await async_get_integration(hass, DOMAIN)).version))
        except Exception:  # noqa: BLE001 - the panel is a convenience, never block the gateway
            _LOGGER.warning("Could not set up the commissioning panel", exc_info=True)
        if not domain_data.get("resources_started"):
            domain_data["resources_started"] = True
            hass.async_create_task(_async_install_resources(hass))
        return True

    runtime = DeviceRuntime(hass, entry)
    await runtime.async_load()
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    runtime.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    _schedule_sync(hass)

    # keep the "main name" (the entry title) in sync when the user renames the device in Home Assistant, so the
    # new name shows everywhere — the group header, the cards and the dashboards (which read the entry title).
    from homeassistant.helpers import device_registry as dr

    @callback
    def _sync_title(event) -> None:
        data = event.data
        if data.get("action") != "update" or "name_by_user" not in (data.get("changes") or {}):
            return
        dev = dr.async_get(hass).async_get(data["device_id"])
        if not dev or entry.entry_id not in dev.config_entries:
            return
        name = (dev.name_by_user or "").strip()
        if name and name != entry.title:
            hass.config_entries.async_update_entry(entry, title=name)

    entry.async_on_unload(hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _sync_title))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if _is_hub(entry):
        ok = await hass.config_entries.async_unload_platforms(entry, HUB_PLATFORMS)
        try:
            from .dashboard import async_remove_panel
            await async_remove_panel(hass, entry)
        except Exception:  # noqa: BLE001 - never let cleanup block the unload / leave the entry stuck
            _LOGGER.exception("Could not remove the Milesight dashboard panel")
        hub = getattr(entry, "runtime_data", None)
        if hub is not None:
            try:
                await hub.async_stop()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error stopping the Milesight gateway hub")
        hass.data.get(DOMAIN, {}).get("hubs", {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN, {}).get("hubs"):
            try:
                from .commissioning_ws import async_remove_panel as _remove_commissioning
                _remove_commissioning(hass)
            except Exception:  # noqa: BLE001
                pass
        return ok

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok and getattr(entry, "runtime_data", None) is not None:
        try:
            await entry.runtime_data.async_stop()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error stopping Milesight device runtime")
    return ok


async def async_remove_config_entry_device(hass: HomeAssistant, entry: ConfigEntry, device_entry) -> bool:
    """Let the user delete a device from the Home Assistant UI. For a gateway sub-device, also forget it from the
    hub's statistics so it can be discovered again; otherwise just allow the removal."""
    hub = getattr(entry, "runtime_data", None)
    for domain, ident in device_entry.identifiers:
        if domain == DOMAIN and ident.startswith("gw_") and hub is not None and hasattr(hub, "forget_gateway"):
            hub.forget_gateway(ident[3:])
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up stored analytics and allow re-discovery when a device is deleted."""
    if _is_hub(entry):
        # the generated dashboard and the gateway's statistics belong to this entry
        for key in (f"{DOMAIN}.dashboard_{entry.entry_id}", f"lovelace.milesight_{entry.entry_id}",
                    f"{DOMAIN}.hub_{entry.entry_id}", f"{DOMAIN}.alerts_{entry.entry_id}",
                    f"{DOMAIN}.areas_{entry.entry_id}"):
            await Store(hass, STORAGE_VERSION if key.startswith(DOMAIN) else 1, key).async_remove()
        return
    deveui = entry.data[CONF_DEVEUI]
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{deveui}").async_remove()
    _schedule_sync(hass)
    for hub in hass.data.get(DOMAIN, {}).get("hubs", {}).values():
        hub.forget(deveui)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_install_resources(hass: HomeAssistant) -> None:
    """Blueprints and dashboards ship inside the integration (HACS installs nothing else): put them in place
    once after every update, and re-add the dashboards to the sidebar at every start."""
    from homeassistant.loader import async_get_integration
    from .resources import async_install, summary
    try:
        version = str((await async_get_integration(hass, DOMAIN)).version)
        out = await async_install(hass, version)
    except Exception:  # noqa: BLE001 - never block the gateway
        _LOGGER.warning("Could not install the Milesight blueprints / dashboards", exc_info=True)
        return
    # devices set up alongside the gateway were skipped by their own sync: label them all once they exist
    from homeassistant.helpers.event import async_call_later

    async def _late(_now) -> None:
        from .resources import async_label_devices
        try:
            await async_label_devices(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not label the Milesight devices", exc_info=True)
    async_call_later(hass, 60, _late)
    if out:
        from homeassistant.components import persistent_notification
        persistent_notification.async_create(
            hass, f"Version {version}.\n\n{summary(out)}", title="Milesight LoRaWAN: blueprints and dashboards",
            notification_id=f"{DOMAIN}_resources")


def _schedule_sync(hass: HomeAssistant) -> None:
    """A device was added, removed or changed model: a few seconds later, show / hide the dashboards that
    depend on the site's devices (Water Level only with a tank or silo sensor …) and label the device."""
    from homeassistant.helpers.event import async_call_later
    data = hass.data.setdefault(DOMAIN, {"hubs": {}})
    if data.get("sync_pending") or not data.get("resources_started"):
        return                              # at start-up the version install does the same
    async def _run(_now) -> None:
        data["sync_pending"] = None
        from .resources import async_sync, summary
        try:
            out = await async_sync(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not update the Milesight dashboards", exc_info=True)
            return
        db = out.get("dashboards") or {}
        if db.get("written") or db.get("removed"):
            from homeassistant.components import persistent_notification
            persistent_notification.async_create(hass, summary(out), title="Milesight LoRaWAN: dashboards",
                                                 notification_id=f"{DOMAIN}_resources")
    data["sync_pending"] = async_call_later(hass, 10, _run)
