"""Maintenance helpers on the Home Assistant side: settings profiles (store + apply) and the installer handover
report (CSV + printable page in /config/www/milesight/)."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import profiles as _profiles
from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_DEVICE, ENTRY_TYPE_HUB, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


def _store(hass: HomeAssistant) -> Store:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.profiles")


async def async_profiles(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    return (await _store(hass).async_load() or {}).get("profiles", {})


async def async_save_profile(hass: HomeAssistant, entry: Any, name: str) -> dict[str, Any]:
    rt = entry.runtime_data
    prof = _profiles.capture(rt.model.key, dict(entry.options), rt.meta, name.strip(), entry.title, time.time())
    data = await _store(hass).async_load() or {}
    data.setdefault("profiles", {})[prof["name"]] = prof
    await _store(hass).async_save(data)
    return prof


async def async_delete_profile(hass: HomeAssistant, name: str) -> None:
    data = await _store(hass).async_load() or {}
    data.get("profiles", {}).pop(name, None)
    await _store(hass).async_save(data)


def same_model_entries(hass: HomeAssistant, model: str, exclude: str | None = None) -> list[Any]:
    out = []
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE or e.entry_id == exclude:
            continue
        if e.options.get("model", e.data.get("model")) == model:
            out.append(e)
    return sorted(out, key=lambda e: e.title.lower())


async def async_apply_profile(hass: HomeAssistant, profile: dict[str, Any], entry: Any, channels: bool = True,
                              send: bool = True, by: str | None = None) -> dict[str, Any]:
    """Apply to one device: over-the-air settings first (queued on the device, confirmed by its echo), then the
    options (the device reloads with them). Returns {'options': n, 'sent': n, 'failed': [..]}."""
    if entry.options.get("model", entry.data.get("model")) != profile["model"]:
        raise ValueError(f"{entry.title} is not a {profile['model']}")
    rt = getattr(entry, "runtime_data", None)
    sent, failed = 0, []
    if send and rt is not None:
        for kind, (name, value) in _profiles.over_the_air(profile, rt.meta):
            try:
                if kind == "config":
                    await rt.async_command(name, value)
                elif isinstance(value, dict):
                    fields = list(value.items())
                    if not fields:
                        continue
                    rt.meta.setdefault("settings", {})[name] = dict(value)
                    last_k, last_v = fields[-1]
                    await rt.async_setting(name, last_k, last_v)
                else:
                    await rt.async_setting(name, None, bool(value))
                sent += 1
            except Exception as err:  # noqa: BLE001 - keep going with the other settings
                failed.append(f"{name}: {err}")
    new = _profiles.merged_options(dict(entry.options), profile, channels)
    changed = sum(1 for k, v in new.items() if entry.options.get(k) != v)
    if rt is not None:
        rt.log_service("profile", f"Settings profile '{profile['name']}' applied ({changed} options changed, "
                                  f"{sent} settings sent{', ' + str(len(failed)) + ' failed' if failed else ''})", by)
    if new != dict(entry.options):
        hass.config_entries.async_update_entry(entry, options=new)
    return {"options": changed, "sent": sent, "failed": failed}


# ------------------------------------------------------------------ handover report
async def async_handover_report(hass: HomeAssistant, hub_entry: Any) -> dict[str, str]:
    """Writes www/milesight/handover-<site>-<date>.csv and .html; returns their /local/ URLs."""
    import re
    from datetime import datetime
    from homeassistant.util import dt as dt_util
    from .fleet import fleet_devices
    from .handover import report_csv, report_html
    from .building import site_info
    devices = fleet_devices(hass, hub_entry)
    for d in devices:                         # add the commissioning result when there is one
        e = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, d["deveui"].lower())
        rt = getattr(e, "runtime_data", None) if e is not None else None
        d["walk_test"] = ((rt.meta.get("commissioning") or [None])[-1] if rt is not None else None)
    site = site_info(hass, hub_entry)
    now = dt_util.now()
    slug = re.sub(r"[^a-z0-9]+", "-", (hub_entry.title or "site").lower()).strip("-") or "site"
    base = f"handover-{slug}-{now.strftime('%Y%m%d-%H%M')}"
    gateways = [{"id": gid, **{k: g.get(k) for k in ("name", "last_heard", "packets_today")}}
                for gid, g in hub_entry.runtime_data.stats.gateways.items()]
    csv_text = report_csv(devices)
    html = report_html(site, devices, gateways, now.strftime("%d %B %Y %H:%M"))
    folder = hass.config.path("www", "milesight")

    def _write() -> None:
        import os
        os.makedirs(folder, exist_ok=True)
        with open(f"{folder}/{base}.csv", "w", encoding="utf-8", newline="") as f:
            f.write(csv_text)
        with open(f"{folder}/{base}.html", "w", encoding="utf-8") as f:
            f.write(html)
    await hass.async_add_executor_job(_write)
    return {"html": f"/local/milesight/{base}.html", "csv": f"/local/milesight/{base}.csv",
            "devices": str(len(devices))}


def first_hub_entry(hass: HomeAssistant) -> Any:
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB and getattr(e, "runtime_data", None) is not None:
            return e
    return None
