"""Diagnostics download (Settings > Devices > ... > Download diagnostics)."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_HUB


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    options = dict(entry.options)
    if options.get("ns_app_key"):
        options["ns_app_key"] = "**REDACTED**"
    raw = dict(entry.data)
    if raw.get("lns_app_key"):
        raw["lns_app_key"] = "**REDACTED**"
    data: dict[str, Any] = {"data": raw, "options": options}
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
        hub = entry.runtime_data
        data["topic"] = hub.topic
        data["seen_devices"] = sorted(hub.last_uplink)
        data["alerts"] = hub.alerts.engine.to_dict()
        data["gateway_devices"] = hub.gateway_devices
        if getattr(hub, "lns", None) is not None:
            data["network_server"] = hub.lns.summary()          # no keys: session info only
    else:
        data["runtime"] = entry.runtime_data.diagnostics()
    return data
