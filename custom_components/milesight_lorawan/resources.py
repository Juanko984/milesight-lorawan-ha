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
RETIRED = {"milesight-fleet": "milesight-maintenance/devices",      # merged into Maintenance (tabs) in 0.34
           "milesight-signal": "milesight-maintenance/signal"}
# dashboards whose sidebar slug changed: the old one is removed and a fresh one created under the new slug, so a
# hand-edited or half-deleted copy under the old slug stops coming back.
RENAMED = {"milesight-tanks": "milesight-water"}                    # "Tanks & alerts" → "Water" in 0.76
DASHBOARDS = {  # file -> (url, icon, device tags that call for it; None = every site)
    "alerts.yaml": ("milesight-alerts", "mdi:bell-ring", None),
    "devices.yaml": ("milesight-devices", "mdi:format-list-bulleted", None),
    "maintenance.yaml": ("milesight-maintenance", "mdi:wrench-clock", None),
    "tanks_and_alerts.yaml": ("milesight-water", "mdi:water-percent", {"tank"}),
    "building_analytics.yaml": ("milesight-analytics", "mdi:chart-box-outline", {"comfort", "people"}),
    "farm.yaml": ("milesight-farm", "mdi:tractor-variant", {"pump", "irrigation"}),
    "cold_chain.yaml": ("milesight-cold-chain", "mdi:snowflake-thermometer", {"cold_chain"}),
    "energy.yaml": ("milesight-energy", "mdi:lightning-bolt", {"energy", "hvac"}),
    "coop.yaml": ("milesight-coop", "mdi:egg", {"coop"}),
    "retail.yaml": ("milesight-retail", "mdi:storefront-outline", {"retail"}),
    "washroom.yaml": ("milesight-washroom", "mdi:human-male-female", {"washroom"}),
}


def site_tags(hass: HomeAssistant) -> set[str]:
    """Tags of every Milesight device set up in Home Assistant (from its model)."""
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
    from .models import device_tags
    tags: set[str] = set()
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_DEVICE:
            tags |= device_tags(e.options.get("model", e.data.get("model")), {**e.data, **e.options})
            area = str(e.options.get("area") or e.data.get("area") or "").lower()
            if "coop" in area or "chicken" in area:    # a device assigned to a chicken-coop area
                tags.add("coop")
        elif e.options.get("irr_weather") or e.options.get("irr_soil"):
            tags.add("irrigation")                     # gateway with the forecast-aware irrigation set up
    return tags


def wanted_dashboards(tags: set[str]) -> dict[str, bool]:
    """Pure: url -> whether the site needs this dashboard."""
    return {url: needs is None or bool(needs & tags) for url, _icon, needs in DASHBOARDS.values()}


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


async def async_install_dashboards(hass: HomeAssistant, state: dict[str, Any],
                                   tags: set[str] | None = None) -> dict[str, list[str]]:
    import yaml
    from .dashboard import _lovelace_dashboards, _register

    def _read() -> dict[str, Any]:
        return {f: yaml.safe_load((RES / "dashboards" / f).read_text(encoding="utf-8")) for f in DASHBOARDS}
    configs = await hass.async_add_executor_job(_read)
    configs = {f: _live(hass, f, c) for f, c in configs.items()}
    done = state.setdefault("dashboards", {})
    dashboards = _lovelace_dashboards(hass)
    result: dict[str, list[str]] = {"written": [], "kept": [], "removed": []}
    wanted = wanted_dashboards(site_tags(hass) if tags is None else tags)
    for url in [u for u in done if u in RETIRED]:      # dashboards merged into another one: out of the sidebar
        mine = done.pop(url)
        _hide(hass, url)
        result.setdefault("merged", []).append(mine.get("title") or url)
    # renamed slugs: drop the old dashboard (even a hand-edited / half-deleted one) so the fresh one can appear
    for old, new in RENAMED.items():
        if old in done or old in _lovelace_dashboards(hass):
            done.pop(old, None)
            _hide(hass, old)
            result.setdefault("renamed", []).append((old, new))
    for f, (url, icon, _needs) in DASHBOARDS.items():
        config = configs[f]
        title = config.get("title") or url
        mine = done.get(url)
        if not wanted[url]:
            if mine is not None and not mine.get("hidden"):
                _hide(hass, url)
                mine["hidden"] = True
                result["removed"].append(title)
            continue
        if url in dashboards and mine is None:
            result["kept"].append(title)              # a dashboard the user made with this URL
            continue
        dash = _register(hass, url, title, f"milesight_{url.replace('-', '_')}", icon)
        current = None
        if mine is not None:
            try:
                current = await dash.async_load(False)
            except Exception:  # noqa: BLE001 - not saved yet
                current = None
            if current is not None and _hash(current) != mine.get("hash") and _hash(current) != _hash(config):
                result["kept"].append(title)          # edited in Home Assistant: keep the user's version
                continue
        if mine is not None and current is not None and _hash(current) == mine.get("hash") == _hash(config):
            if mine.get("hidden"):
                mine["hidden"] = False              # back in the sidebar, nothing to rewrite
                result["written"].append(title)
            continue                                # already up to date
        await dash.async_save(config)
        done[url] = {"title": title, "icon": icon, "hash": _hash(config), "hidden": False}
        result["written"].append(title)
    return result


def _live(hass: HomeAssistant, file: str, config: dict) -> dict:
    """Add the 'Live' view (gauges, sliders, pivot map) for the devices that are set up."""
    try:
        from homeassistant.helpers import entity_registry as er
        from .dashboard_live import with_live_view
        reg = er.async_get(hass)
        runtimes = [rt for e in hass.config_entries.async_entries(DOMAIN)
                    if hasattr(rt := getattr(e, "runtime_data", None), "deveui")]
        hubs = list(hass.data.get(DOMAIN, {}).get("hubs", {}).values())
        return with_live_view(file, config, lambda plat, uid: reg.async_get_entity_id(plat, DOMAIN, uid),
                              sorted(runtimes, key=lambda r: r.entry.title.lower()), hubs)
    except Exception:  # noqa: BLE001 - the bundled dashboard still works without the live view
        _LOGGER.debug("Could not build the live view for %s", file, exc_info=True)
        return config


def _refresh_landing(hass: HomeAssistant) -> None:
    """The site landing pages show buttons to these dashboards and the devices' sections: refresh them."""
    try:
        from .dashboard import refresh_all
        refresh_all(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not refresh the site dashboards", exc_info=True)


def _hide(hass: HomeAssistant, url: str) -> None:
    """Take an integration-made dashboard out of the sidebar (its content stays stored for later)."""
    from .dashboard import _lovelace_dashboards
    try:
        from homeassistant.components import frontend
        frontend.async_remove_panel(hass, url)
    except Exception:  # noqa: BLE001
        pass
    try:
        _lovelace_dashboards(hass).pop(url, None)
    except Exception:  # noqa: BLE001
        pass


async def async_install(hass: HomeAssistant, version: str | None = None, force: bool = False) -> dict[str, Any]:
    """Install / update blueprints and dashboards; returns what happened. Runs once per version unless forced."""
    store = _store(hass)
    state = await store.async_load() or {}
    if not force and version and state.get("version") == version:
        await async_restore(hass, state)
        try:                                   # labels for devices set up before the gateway (at every start)
            await async_label_devices(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not label the Milesight devices", exc_info=True)
        return {}
    out = {"blueprints": await async_install_blueprints(hass, state)}
    try:
        tags = site_tags(hass)
        out["dashboards"] = await async_install_dashboards(hass, state, tags)
        state["tags"] = sorted(tags)
        state["live"] = _hash([_live(hass, f, {}) for f in DASHBOARDS])
    except Exception as err:  # noqa: BLE001 - dashboards (lovelace) not available
        _LOGGER.warning("Could not install the Milesight dashboards: %s", err)
        out["dashboards"] = {"written": [], "kept": [], "error": str(err)}
    state["version"] = version
    await store.async_save(state)
    try:
        await async_label_devices(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not label the Milesight devices", exc_info=True)
    _refresh_landing(hass)
    _LOGGER.info("Milesight resources: %s", out)
    return out


async def async_restore(hass: HomeAssistant, state: dict[str, Any] | None = None) -> None:
    """Integration-made dashboards are not in the dashboards list: put them back in the sidebar at every start."""
    if state is None:
        state = await _store(hass).async_load() or {}
    from .dashboard import _register
    for url, d in (state.get("dashboards") or {}).items():
        if d.get("hidden"):
            continue
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
    if db.get("merged"):
        lines.append(f"{' and '.join(db['merged'])} are now tabs of the Maintenance dashboard.")
    if db.get("renamed"):
        lines.append("A dashboard was renamed; the old sidebar entry was removed and a fresh one created "
                     f"({', '.join(f'{o} → {n}' for o, n in db['renamed'])}).")
    if db.get("removed"):
        lines.append(f"Dashboards removed from the sidebar (no devices need them yet): {', '.join(db['removed'])}.")
    if db.get("kept"):
        lines.append(f"Dashboards you changed were kept: {', '.join(db['kept'])}.")
    if db.get("error"):
        lines.append(f"Dashboards could not be created: {db['error']}.")
    return "\n\n".join(lines) or "Everything is up to date."


async def async_sync(hass: HomeAssistant) -> dict[str, Any]:
    """Devices were added / removed / changed model: show or hide the dashboards that depend on them and
    label the devices. Does not touch blueprints."""
    store = _store(hass)
    state = await store.async_load() or {}
    tags = site_tags(hass)
    live = _hash([_live(hass, f, {}) for f in DASHBOARDS])
    if state.get("tags") == sorted(tags) and state.get("dashboards") and state.get("live") == live:
        await async_label_devices(hass)
        return {}
    try:
        out = {"dashboards": await async_install_dashboards(hass, state, tags)}
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not update the Milesight dashboards", exc_info=True)
        return {"dashboards": {"written": [], "kept": [], "error": str(err)}}
    state["tags"] = sorted(tags)
    state["live"] = live
    await store.async_save(state)
    await async_label_devices(hass)
    _refresh_landing(hass)
    return out


async def async_label_devices(hass: HomeAssistant) -> None:
    """Give each Milesight device Home Assistant labels for what it is used for (filter devices, entities
    and automations by 'Milesight · Tank / silo' …). Labels people removed by hand are not added again."""
    from homeassistant.helpers import device_registry as dr
    from .const import CONF_DEVEUI, CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
    from .models import TAGS, device_tags
    try:
        from homeassistant.helpers import label_registry as lr
    except ImportError:            # Home Assistant before labels
        return
    store = _store(hass)
    state = await store.async_load() or {}
    labelled: dict[str, list[str]] = state.setdefault("labelled", {})
    lreg, dreg = lr.async_get(hass), dr.async_get(hass)
    from .const import DOWNLINK_CHIRPSTACK
    hubs = list(hass.data.get(DOMAIN, {}).get("hubs", {}).values())
    state["_chirpstack"] = bool(hubs) and all(getattr(h, "downlink_format", None) == DOWNLINK_CHIRPSTACK for h in hubs)
    ids: dict[str, str] = {}
    changed = False
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        device = dreg.async_get_device(identifiers={(DOMAIN, e.data.get(CONF_DEVEUI))})
        if device is None:
            continue
        if _connection_label(e, device, lreg, dreg, state):
            changed = True
            device = dreg.async_get(device.id) or device
        tags = device_tags(e.options.get("model", e.data.get("model")), {**e.data, **e.options})
        new = [t for t in sorted(tags) if t not in labelled.get(device.id, [])]
        if not new:
            continue
        add = set()
        for t in new:
            if t not in ids:
                name, icon = TAGS[t]
                label = lreg.async_get_label_by_name(name) or lreg.async_create(name, icon=icon)
                ids[t] = label.label_id
            add.add(ids[t])
        dreg.async_update_device(device.id, labels=set(device.labels) | add)
        labelled[device.id] = sorted(set(labelled.get(device.id, [])) | set(new))
        changed = True
    state.pop("_chirpstack", None)
    if changed:
        await store.async_save(state)


def _chirpstack_hub(state: dict[str, Any]) -> bool:
    return bool(state.get("_chirpstack"))


def _connection_label(entry: Any, device: Any, lreg: Any, dreg: Any, state: dict[str, Any]) -> bool:
    """One label per device for how it reaches Home Assistant (gateway's network server, ChirpStack or the
    built-in one); swapped when that changes. Returns True when the device's labels changed."""
    from .models import NETWORK_SERVERS, network_of
    ns = network_of((getattr(getattr(entry, "runtime_data", None), "meta", None) or {}).get("network_server"),
                    dict(entry.data), _chirpstack_hub(state))
    conn: dict[str, str] = state.setdefault("connection", {})
    if conn.get(device.id) == ns:
        return False
    _text, name, icon = NETWORK_SERVERS[ns]
    wanted = (lreg.async_get_label_by_name(name) or lreg.async_create(name, icon=icon)).label_id
    others = set()
    for key, (_t, other, _i) in NETWORK_SERVERS.items():
        if key != ns and (lab := lreg.async_get_label_by_name(other)) is not None:
            others.add(lab.label_id)
    dreg.async_update_device(device.id, labels=(set(device.labels) - others) | {wanted})
    conn[device.id] = ns
    return True
