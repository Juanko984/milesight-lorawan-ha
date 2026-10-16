"""Ships the blueprints and ready-made dashboards with the integration.

HACS only installs custom_components/milesight_lorawan, so the blueprints and dashboards live in resources/ and are
put in place by the integration itself: blueprints are copied to config/blueprints/automation/milesight_lorawan/,
dashboards are created as storage dashboards in the sidebar. This happens automatically after every update (new
version) and with the gateway's *Install dashboards and blueprints* button. Files or dashboards the user changed
are left alone.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)
RES = pathlib.Path(__file__).parent / "resources"
DASHBOARDS = {  # file -> (url, icon)
    "fleet_overview.yaml": ("milesight-fleet", "mdi:access-point-network"),
    "signal_quality.yaml": ("milesight-signal", "mdi:signal"),
    "tanks_and_alerts.yaml": ("milesight-tanks", "mdi:storage-tank"),
    "building_analytics.yaml": ("milesight-analytics", "mdi:chart-box-outline"),
}


def _hash(data: Any) -> str:
    return hashlib.sha256(repr(data).encode() if not isinstance(data, bytes) else data).hexdigest()[:16]


def _store(hass: HomeAssistant) -> Store:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.resources")


def plan_blueprints(bundled: dict[str, bytes], on_disk: dict[str, bytes | None],
                    written: dict[str, str]) -> tuple[list[str], list[str]]:
    """Pure: which blueprint files to write, and which to keep because the user edited them.
    Missing → written. Different from ours → written, unless we installed it before and it has changed since
    (edited in Home Assistant). Files from a manual import (no record yet) are replaced: the folder is ours."""
    write, kept = [], []
    for name, data in bundled.items():
        cur = on_disk.get(name)
        if cur == data:
            continue
        if cur is not None and name in written and written[name] != _hash(cur):
            kept.append(name)
        else:
            write.append(name)
    return write, kept


async def async_install_blueprints(hass: HomeAssistant, state: dict[str, Any]) -> dict[str, list[str]]:
    dst = pathlib.Path(hass.config.path("blueprints", "automation", "milesight_lorawan"))
    written = state.setdefault("blueprints", {})

    def _work() -> dict[str, list[str]]:
        bundled = {p.name: p.read_bytes() for p in sorted((RES / "blueprints").glob("*.yaml"))}
        on_disk = {n: (dst / n).read_bytes() if (dst / n).exists() else None for n in bundled}
        write, kept = plan_blueprints(bundled, on_disk, written)
        for n, data in bundled.items():
            if on_disk[n] == data:
                written[n] = _hash(data)          # already ours: remember it so later edits are respected
        if write:
            dst.mkdir(parents=True, exist_ok=True)
        for n in write:
            (dst / n).write_bytes(bundled[n])
            written[n] = _hash(bundled[n])
        return {"written": write, "kept": kept}
    result = await hass.async_add_executor_job(_work)
    if result["written"]:
        try:   # let the automation editor see new / changed blueprints without a restart
            for blueprints in (hass.data.get("blueprint") or {}).values():
                if hasattr(blueprints, "async_reset_cache"):
                    blueprints.async_reset_cache()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not refresh the blueprint cache", exc_info=True)
    return result


async def async_install_dashboards(hass: HomeAssistant, state: dict[str, Any]) -> dict[str, list[str]]:
    import yaml
    from .dashboard import _lovelace_dashboards, _register

    def _read() -> dict[str, Any]:
        return {f: yaml.safe_load((RES / "dashboards" / f).read_text(encoding="utf-8")) for f in DASHBOARDS}
    configs = await hass.async_add_executor_job(_read)
    done = state.setdefault("dashboards", {})
    dashboards = _lovelace_dashboards(hass)
    result: dict[str, list[str]] = {"written": [], "kept": []}
    for f, (url, icon) in DASHBOARDS.items():
        config = configs[f]
        title = config.get("title") or url
        mine = done.get(url)
        if url in dashboards and mine is None:
            result["kept"].append(title)              # a dashboard the user made with this URL
            continue
        dash = _register(hass, url, title, f"milesight_{url.replace('-', '_')}", icon)
        if mine is not None:
            try:
                current = await dash.async_load(False)
            except Exception:  # noqa: BLE001 - not saved yet
                current = None
            if current is not None and _hash(current) != mine.get("hash") and _hash(current) != _hash(config):
                result["kept"].append(title)          # edited in Home Assistant: keep the user's version
                continue
        await dash.async_save(config)
        done[url] = {"title": title, "icon": icon, "hash": _hash(config)}
        result["written"].append(title)
    return result


async def async_install(hass: HomeAssistant, version: str | None = None, force: bool = False) -> dict[str, Any]:
    """Install / update blueprints and dashboards; returns what happened. Runs once per version unless forced."""
    store = _store(hass)
    state = await store.async_load() or {}
    if not force and version and state.get("version") == version:
        await async_restore(hass, state)
        return {}
    out = {"blueprints": await async_install_blueprints(hass, state)}
    try:
        out["dashboards"] = await async_install_dashboards(hass, state)
    except Exception as err:  # noqa: BLE001 - dashboards (lovelace) not available
        _LOGGER.warning("Could not install the Milesight dashboards: %s", err)
        out["dashboards"] = {"written": [], "kept": [], "error": str(err)}
    state["version"] = version
    await store.async_save(state)
    _LOGGER.info("Milesight resources: %s", out)
    return out


async def async_restore(hass: HomeAssistant, state: dict[str, Any] | None = None) -> None:
    """Integration-made dashboards are not in the dashboards list: put them back in the sidebar at every start."""
    if state is None:
        state = await _store(hass).async_load() or {}
    from .dashboard import _register
    for url, d in (state.get("dashboards") or {}).items():
        try:
            _register(hass, url, d["title"], f"milesight_{url.replace('-', '_')}", d.get("icon") or "mdi:view-dashboard")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not restore dashboard %s", url, exc_info=True)


def summary(out: dict[str, Any]) -> str:
    bp, db = out.get("blueprints") or {}, out.get("dashboards") or {}
    lines = []
    if bp.get("written"):
        lines.append(f"Blueprints installed / updated: {', '.join(n.removesuffix('.yaml') for n in bp['written'])}.")
    if bp.get("kept"):
        lines.append(f"Blueprints you changed were kept: {', '.join(n.removesuffix('.yaml') for n in bp['kept'])}.")
    if db.get("written"):
        lines.append(f"Dashboards in the sidebar: {', '.join(db['written'])}.")
    if db.get("kept"):
        lines.append(f"Dashboards you changed were kept: {', '.join(db['kept'])}.")
    if db.get("error"):
        lines.append(f"Dashboards could not be created: {db['error']}.")
    return "\n\n".join(lines) or "Everything is up to date."
