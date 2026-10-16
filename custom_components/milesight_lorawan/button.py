"""Button platform: device commands (reboot, sync time, request update)."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE, ENTRY_TYPE_HUB
from .entity import MilesightEntity, setup_platform_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
        hub = entry.runtime_data
        buttons: list = [UpdateDashboardButton(hass, entry), _HubButton(hass, entry, "acknowledge_alerts")]
        if getattr(hub, "ns", None) is not None:
            buttons.append(_HubButton(hass, entry, "sync_gateway"))
        async_add_entities(buttons)
        return
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "button", MilesightCommandButton)


class MilesightCommandButton(MilesightEntity, ButtonEntity):
    def __init__(self, runtime, spec) -> None:
        super().__init__(runtime, spec)
        if spec.device_class:
            self._attr_device_class = ButtonDeviceClass(spec.device_class)

    async def async_added_to_hass(self) -> None:
        """Buttons have no state to follow."""

    async def async_press(self) -> None:
        command = self.spec.key.removeprefix("cmd_")
        try:
            if command == "tank_refilled":
                self.runtime.tank_refilled()
            elif command == "tank_clear_alarm":
                self.runtime.tank_clear_alarm()
            elif command == "fetch_history":
                await self.runtime.async_fetch_history()
            elif command.startswith("display_"):
                await self.runtime.async_display_command(command.removeprefix("display_"))
            else:
                await self.runtime.async_command(command)
        except Exception as err:  # noqa: BLE001 - surface MQTT / config problems in the UI
            raise HomeAssistantError(f"Could not send {command} to {self.runtime.entry.title}: {err}") from err


class UpdateDashboardButton(ButtonEntity):
    """Gateway: (re)generate the Building dashboard from the site information and areas."""

    _attr_has_entity_name = True
    _attr_name = "Update building dashboard"
    _attr_icon = "mdi:view-dashboard-edit-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from .building import hub_device
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_update_dashboard"
        self._attr_device_info = hub_device(entry)

    async def async_press(self) -> None:
        from .dashboard import async_update_dashboard
        try:
            await async_update_dashboard(self.hass, self.entry)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Could not update the building dashboard: {err}") from err


class _HubButton(ButtonEntity):
    """Gateway: acknowledge every open alert / read the device list from the gateway."""

    _attr_has_entity_name = True
    KINDS = {"acknowledge_alerts": ("Acknowledge all alerts", "mdi:bell-check-outline"),
             "sync_gateway": ("Sync devices with gateway", "mdi:sync")}

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, kind: str) -> None:
        from .building import hub_device
        self.hass, self.entry, self.kind = hass, entry, kind
        self._attr_name, self._attr_icon = self.KINDS[kind]
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_device_info = hub_device(entry)

    async def async_press(self) -> None:
        hub = self.entry.runtime_data
        try:
            if self.kind == "acknowledge_alerts":
                await hub.alerts.async_acknowledge(None, None)
            else:
                await hub.async_sync_devices()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"{self._attr_name} failed: {err}") from err
