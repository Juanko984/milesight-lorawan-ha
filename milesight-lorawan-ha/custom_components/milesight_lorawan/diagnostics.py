"""Diagnostics download (Settings > Devices > ... > Download diagnostics)."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_HUB


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    data: dict[str, Any] = {"data": dict(entry.data), "options": dict(entry.options)}
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
        hub = entry.runtime_data
        data["topic"] = hub.topic
        data["seen_devices"] = sorted(hub.last_uplink)
    else:
        data["runtime"] = entry.runtime_data.diagnostics()
    return data
