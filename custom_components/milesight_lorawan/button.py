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
        buttons: list = [UpdateDashboardButton(hass, entry), _HubButton(hass, entry, "acknowledge_alerts"),
                         _HubButton(hass, entry, "install_resources"), _HubButton(hass, entry, "alert_summary"),
                         _HubButton(hass, entry, "handover_report"), _HubButton(hass, entry, "compliance_week"),
                         _HubButton(hass, entry, "compliance_month")]
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
            elif command == "pivot_stop":
                self.runtime.pivot_stopped()
            elif command.startswith("load") and command.endswith("_serviced"):
                self.runtime.load_serviced(command.removesuffix("serviced"))
            elif command in ("cleaned", "panic_clear", "service_clear"):
                self.runtime.purpose_clear(command.removesuffix("_clear"))
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
    _attr_name = "Update site dashboard"
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
            raise HomeAssistantError(f"Could not update the site dashboard: {err}") from err


class _HubButton(ButtonEntity):
    """Gateway: acknowledge every open alert / read the device list from the gateway."""

    _attr_has_entity_name = True
    KINDS = {"acknowledge_alerts": ("Acknowledge all alerts", "mdi:bell-check-outline"),
             "sync_gateway": ("Sync devices with gateway", "mdi:sync"),
             "install_resources": ("Install dashboards and blueprints", "mdi:package-down"),
             "alert_summary": ("Send alert summary", "mdi:email-newsletter"),
             "handover_report": ("Create handover report", "mdi:clipboard-check-outline"),
             "compliance_week": ("Cold-chain report: last week", "mdi:file-certificate-outline"),
             "compliance_month": ("Cold-chain report: last month", "mdi:file-certificate")}

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
            elif self.kind == "alert_summary":
                await hub.alerts.async_send_summary()
            elif self.kind in ("compliance_week", "compliance_month"):
                await hub.compliance.async_create(self.kind.removeprefix("compliance_"), send=True)
            elif self.kind == "handover_report":
                from homeassistant.components import persistent_notification
                from .const import DOMAIN
                from .maintenance_ha import async_handover_report
                out = await async_handover_report(self.hass, self.entry)
                persistent_notification.async_create(
                    self.hass, f"{out['devices']} devices. [Open the printable report]({out['html']}) · "
                               f"[Download CSV]({out['csv']})\n\nThe files are in /config/www/milesight/.",
                    title="Milesight LoRaWAN: handover report", notification_id=f"{DOMAIN}_handover")
            elif self.kind == "install_resources":
                from homeassistant.components import persistent_notification
                from homeassistant.loader import async_get_integration
                from .const import DOMAIN
                from .resources import async_install, summary
                version = str((await async_get_integration(self.hass, DOMAIN)).version)
                out = await async_install(self.hass, version, force=True)
                persistent_notification.async_create(
                    self.hass, summary(out), title="Milesight LoRaWAN: blueprints and dashboards",
                    notification_id=f"{DOMAIN}_resources")
            else:
                await hub.async_sync_devices()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"{self._attr_name} failed: {err}") from err
