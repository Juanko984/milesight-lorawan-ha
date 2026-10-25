"""Creates / updates the site landing page (the '<site>' dashboard) for a gateway (Home Assistant storage dashboard, built-in cards)."""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .building import area_names, site_info
from .building_calc import AVERAGES
from .const import DOMAIN, STORAGE_VERSION
from .dashboard_config import build_config

_LOGGER = logging.getLogger(__name__)
ICON = "mdi:office-building"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "site"


def dashboard_url(entry: ConfigEntry) -> str:
    """Dashboard URLs must contain a hyphen: building-<site>."""
    return f"building-{_slug(entry.title)}"


def site_title(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Sidebar name of the landing page: the company / site name, not the gateway entry's technical name."""
    from .const import CONF_SITE_COMPANY
    name = (entry.options.get(CONF_SITE_COMPANY) or "").strip()
    if not name:
        loc = (getattr(hass.config, "location_name", "") or "").strip()
        name = loc if loc and loc.lower() not in ("home", "") else ""
    if not name:
        t = entry.title or "Site"
        name = "Site" if t.lower().startswith("milesight gateway") else t
    return name


def build_context(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    reg = er.async_get(hass)
    eid = entry.entry_id

    def find(platform: str, unique_id: str) -> str | None:
        return reg.async_get_entity_id(platform, DOMAIN, unique_id)

    site = site_info(hass, entry)
    ctx: dict[str, Any] = {
        "title": site_title(hass, entry),
        "site": find("sensor", f"{eid}_site"),
        **{k: find("sensor", f"{eid}_building_{k}") for k in
           ("health", "comfort", "air_quality", "systems", "people", "alerts")},
        "avg": {k: find("sensor", f"{eid}_building_avg_{k}") for k in AVERAGES},
        "devices_online": find("sensor", f"{eid}_fleet_online"),
        "battery_low": find("sensor", f"{eid}_fleet_battery_low"),
        "gateways_online": find("sensor", f"{eid}_net_gateways_online"),
        "uplinks": find("sensor", f"{eid}_net_uplinks"),
        "open_alerts": find("sensor", f"{eid}_alerts_open"),
        "outside": site.get("outside_sensor"),
        "co2_alert": site["co2_alert"],
    }
    ctx["avg"] = {k: v for k, v in ctx["avg"].items() if v}

    # areas: the configured ones in order, else every area the integration has analytics for
    hub = getattr(entry, "runtime_data", None)
    tracker = getattr(hub, "areas", None)
    known = sorted(tracker.summary) if tracker is not None else []
    names = area_names(hass, entry) or known
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    areg, dreg = ar.async_get(hass), dr.async_get(hass)
    areas = []
    for name in names:
        slug = "".join(ch if ch.isalnum() else "_" for ch in name.lower())
        area = areg.async_get_area_by_name(name)
        co2 = None
        if area is not None:      # first CO2 sensor of a Milesight device in this area
            for dev in dr.async_entries_for_area(dreg, area.id):
                for ident in dev.identifiers:
                    if ident[0] == DOMAIN:
                        co2 = co2 or find("sensor", f"{ident[1]}_co2")
        areas.append({"name": name, "icon": area.icon if area is not None else None,
                      "comfort": find("sensor", f"{eid}_area_{slug}_comfort"),
                      "occupancy": find("sensor", f"{eid}_area_{slug}_occupancy"), "co2": co2})
    ctx["areas"] = areas
    try:                          # which operational domains this site has (purpose-fit landing page)
        from .resources import site_tags
        ctx["tags"] = sorted(site_tags(hass))
    except Exception:  # noqa: BLE001
        ctx["tags"] = []
    from .const import CONF_CLASSIC_GAUGES
    classic = bool({**entry.data, **entry.options}.get(CONF_CLASSIC_GAUGES, False))
    ctx["classic_gauges"] = classic
    try:                          # tanks, irrigation, pivots, pumps, cold chain and energy at a glance
        from .dashboard_live import set_classic, site_sections
        set_classic(classic)
        runtimes = sorted((rt for e in hass.config_entries.async_entries(DOMAIN)
                           if hasattr(rt := getattr(e, "runtime_data", None), "deveui")),
                          key=lambda r: r.entry.title.lower())
        ctx["live"] = site_sections(lambda plat, uid: reg.async_get_entity_id(plat, DOMAIN, uid), runtimes,
                                    [hub] if hub is not None else [])
    except Exception:  # noqa: BLE001 - the overview still works without them
        _LOGGER.debug("Could not build the site sections", exc_info=True)
        ctx["live"] = []
    return ctx


async def _nav(hass: HomeAssistant) -> list[tuple[str, str, str]]:
    """The ready-made dashboards in the sidebar (installed by resources.py), for the landing page's buttons."""
    try:
        from .resources import DASHBOARDS, _store as res_store
        state = await res_store(hass).async_load() or {}
    except Exception:  # noqa: BLE001
        return []
    order = [url for url, _i, _n in DASHBOARDS.values()]
    shown = [(url, d) for url, d in (state.get("dashboards") or {}).items() if not d.get("hidden")]
    shown.sort(key=lambda x: order.index(x[0]) if x[0] in order else 99)
    return [(d.get("title") or url, url, d.get("icon") or "mdi:view-dashboard") for url, d in shown]


def _hash(data: Any) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _lovelace_dashboards(hass: HomeAssistant) -> dict:
    data = hass.data.get("lovelace")
    if data is None:
        raise RuntimeError("the dashboards (lovelace) component is not loaded")
    return data.dashboards if hasattr(data, "dashboards") else data["dashboards"]


def _register(hass: HomeAssistant, url: str, title: str, config_id: str, icon: str = ICON):
    """Make the storage dashboard known to the frontend (sidebar) – repeated on every start."""
    from homeassistant.components import frontend
    from homeassistant.components.lovelace.dashboard import LovelaceStorage
    dashboards = _lovelace_dashboards(hass)
    dash = dashboards.get(url)
    if dash is None:
        dash = LovelaceStorage(hass, {"id": config_id, "url_path": url, "title": title, "icon": icon,
                                      "show_in_sidebar": True, "require_admin": False, "mode": "storage"})
        dashboards[url] = dash
    try:
        frontend.async_register_built_in_panel(hass, "lovelace", sidebar_title=title, sidebar_icon=icon,
                                               frontend_url_path=url, config={"mode": "storage"},
                                               require_admin=False, update=True)
    except TypeError:            # older Home Assistant without `update`
        frontend.async_register_built_in_panel(hass, "lovelace", sidebar_title=title, sidebar_icon=icon,
                                               frontend_url_path=url, config={"mode": "storage"},
                                               require_admin=False)
    return dash


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.dashboard_{entry.entry_id}")


async def async_restore_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-register a dashboard created earlier (storage dashboards made by an integration are not in the
    dashboards list, so the sidebar entry is added again at every start)."""
    saved = await _store(hass, entry).async_load()
    if saved and saved.get("own") is True:
        try:
            _register(hass, saved["url"], saved["title"], saved["id"])
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not restore the building dashboard", exc_info=True)
    schedule_auto_update(hass, entry)


def schedule_auto_update(hass: HomeAssistant, entry: ConfigEntry, delay: float = 60) -> None:
    """Create / refresh the site landing page by itself once the gateway's sensors exist (not only with the
    button): at every start and when devices change. A landing page edited by hand is left alone."""
    from homeassistant.helpers.event import async_call_later

    async def _run(_now: Any) -> None:
        try:
            await async_update_dashboard(hass, entry, auto=True)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not create / refresh the site dashboard", exc_info=True)
    try:
        entry.async_on_unload(async_call_later(hass, delay, _run))
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not schedule the site dashboard", exc_info=True)


def refresh_all(hass: HomeAssistant, delay: float = 5) -> None:
    """Devices changed: refresh every gateway's landing page (tank, pump, pivot … sections)."""
    for hub in list(hass.data.get(DOMAIN, {}).get("hubs", {}).values()):
        entry = getattr(hub, "entry", None)
        if entry is not None:
            schedule_auto_update(hass, entry, delay)


async def async_update_dashboard(hass: HomeAssistant, entry: ConfigEntry, auto: bool = False) -> str | None:
    """Generate the site landing page and save it. Returns where it went (URL path or YAML file).
    auto: called by the integration itself – skips quietly when the gateway is not ready yet, when the page was
    edited by hand since it was generated, or when nothing changed (None)."""
    ctx = build_context(hass, entry)
    if not ctx.get("site"):
        if auto:                                   # gateway sensors not registered yet: try again a few times
            tries = hass.data.setdefault(DOMAIN, {}).setdefault("_dash_tries", {})
            tries[entry.entry_id] = tries.get(entry.entry_id, 0) + 1
            if tries[entry.entry_id] <= 5:
                schedule_auto_update(hass, entry, 120)
            return None
        raise RuntimeError("the gateway's Site sensor is not set up yet – try again in a minute")
    ctx["nav"] = await _nav(hass)
    config = build_config(ctx)
    url = dashboard_url(entry)
    backup = None
    try:
        dashboards = _lovelace_dashboards(hass)
        prev = await _store(hass, entry).async_load() or {}
        # ours when we made it before or nothing has this URL; a dashboard the user made is updated in place
        own = bool(prev.get("own") and prev.get("url") == url) or url not in dashboards
        if auto:
            if not own:
                return None
            if url in dashboards:
                try:
                    current = await dashboards[url].async_load(False)
                except Exception:  # noqa: BLE001 - not saved yet
                    current = None
                if current is not None and prev.get("hash") and _hash(current) != prev["hash"]:
                    _LOGGER.info("Site dashboard /%s was edited by hand – not updated (press 'Update site "
                                 "dashboard' on the gateway to regenerate it)", url)
                    return None                    # edited by hand: the button regenerates it
                if current is not None and not prev.get("hash"):
                    backup = current               # made before 0.30 (no fingerprint): replace once, keep a copy
                if current is not None and prev.get("hash") == _hash(config) and prev.get("title") == ctx["title"]:
                    return None                    # up to date
        dash = _register(hass, url, ctx["title"], f"milesight_{entry.entry_id}") if own else dashboards[url]
        await dash.async_save(config)
        first = not prev.get("hash")
        saved = {"url": url, "title": ctx["title"], "id": f"milesight_{entry.entry_id}", "own": own,
                 "hash": _hash(config)}
        if backup is not None or prev.get("backup"):
            saved["backup"] = backup if backup is not None else prev.get("backup")
        await _store(hass, entry).async_save(saved)
        _LOGGER.info("Site dashboard saved to /%s", url)
        if first:
            try:
                from homeassistant.components import persistent_notification
                persistent_notification.async_create(
                    hass, f"The site landing page **{ctx['title']}** is in the sidebar: [open it](/{url}). It shows the "
                          "site banner, buttons to every Milesight dashboard, people, alerts, areas, tanks, farm, cold chain "
                          "and energy, and refreshes by itself unless you edit it."
                          + (" Your previous version was kept in Home Assistant's storage." if backup is not None else ""),
                    title="Milesight LoRaWAN: site dashboard", notification_id=f"{DOMAIN}_dashboard_{entry.entry_id}")
            except Exception:  # noqa: BLE001 - the notification is a convenience
                pass
        return f"/{url}"
    except Exception as err:  # noqa: BLE001 - fall back to a YAML file the user can paste
        if auto:
            _LOGGER.warning("Could not save the site dashboard: %s", err)
            return None
        _LOGGER.warning("Could not save the building dashboard directly (%s) – writing YAML instead", err)
        import yaml
        path = hass.config.path(f"milesight_{url}.yaml")

        def _write() -> None:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, width=1000)
        await hass.async_add_executor_job(_write)
        from homeassistant.components import persistent_notification
        persistent_notification.async_create(
            hass, f"The Building dashboard was written to `{path}`. Create a dashboard (Settings → Dashboards → "
                  "Add dashboard), open it, ⋮ → Edit → ⋮ → Raw configuration editor, and paste the file's content.",
            title="Milesight: building dashboard", notification_id=f"{DOMAIN}_dashboard_{entry.entry_id}")
        return path


async def async_remove_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    saved = await _store(hass, entry).async_load()
    if not saved or not saved.get("own"):
        return
    try:
        from homeassistant.components import frontend
        frontend.async_remove_panel(hass, saved["url"])
        _lovelace_dashboards(hass).pop(saved["url"], None)
    except Exception:  # noqa: BLE001
        pass
