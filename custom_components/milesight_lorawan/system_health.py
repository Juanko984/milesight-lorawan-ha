"""System Health panel (Settings → System → Repairs → top-right 'System information'): a quick read on the
Milesight integration — gateways online, devices set up and whether the built-in LoRaWAN server is running."""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_DEVICE, ENTRY_TYPE_HUB


@callback
def async_register(hass: HomeAssistant, register: system_health.SystemHealthRegistration) -> None:
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    entries = hass.config_entries.async_entries(DOMAIN)
    hubs = [e for e in entries if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB]
    devices = [e for e in entries if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_DEVICE]

    gw_online = gw_total = 0
    lns = False
    ts = time.time()
    for e in hubs:
        rt = getattr(e, "runtime_data", None)
        if rt is None:
            continue
        if getattr(rt, "lns", None) is not None:
            lns = True
        stats = getattr(rt, "stats", None)
        if stats is not None:
            for gid in getattr(stats, "gateways", {}):
                gw_total += 1
                if stats.online(gid, ts, rt.offline_s):
                    gw_online += 1

    return {
        "Gateways online": f"{gw_online} / {gw_total}" if gw_total else "none yet",
        "Devices set up": len(devices),
        "Built-in LoRaWAN server": "running" if lns else "off (MQTT only)",
    }
