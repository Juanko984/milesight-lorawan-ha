"""Recipes: plain-language automations, evaluated by our own role-aware engine (recipes_calc), firing
Home Assistant services, notifications and downlink buttons. Engine-only (v1) — no HA automation mirror.

Every minute this reads the site's role sensors, the device fleet and the costs sensor, hands them to the
pure engine, and runs whatever fires. Recipes are stored on the gateway; the Recipes card reads this sensor
and edits the list over the recipe WebSocket (recipes_ws). Nothing leaves the gateway.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .analytics import Calendar
from .building import hub_device
from .const import DOMAIN, SIGNAL_FLEET, STORAGE_VERSION
from .recipes_calc import CATALOG, RecipeEngine, default_recipe, sentence

_LOGGER = logging.getLogger(__name__)
SIGNAL_RECIPES = f"{DOMAIN}_recipes_{{}}"   # .format(hub entry_id)


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


class RecipeManager:
    """Holds the recipe list + engine, samples every minute, and runs the fires."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.store = None
        self.recipes: list[dict[str, Any]] = []
        self.data: dict[str, Any] = {}
        tz = dt_util.get_time_zone(hass.config.time_zone) or dt_util.UTC
        self.cal = Calendar(tz)
        self.engine = RecipeEngine(self.cal)

    # -- site snapshot the engine runs against -----------------------------
    def _ctx(self) -> dict[str, Any]:
        site = {"lat": getattr(self.hass.config, "latitude", None),
                "lon": getattr(self.hass.config, "longitude", None)}
        roles: dict[str, list[dict[str, Any]]] = {}
        try:
            states = self.hass.states.async_all()
        except Exception:  # noqa: BLE001 - no state machine (tests)
            states = []
        for st in states:
            a = getattr(st, "attributes", {}) or {}
            role = a.get("milesight_role")
            if not role and not (a.get("latitude") is not None and a.get("longitude") is not None):
                continue
            # prefer the device title (so "one device" scope + fire messages read as the device, not a sensor id)
            ent = {"id": st.entity_id, "name": a.get("device") or a.get("friendly_name") or st.entity_id,
                   "area": a.get("area"), "state": st.state, "num": _num(st.state), "attrs": a,
                   "lat": a.get("latitude"), "lon": a.get("longitude"),
                   "site_lat": site["lat"], "site_lon": site["lon"]}
            if role:
                roles.setdefault(role, []).append(ent)
            if a.get("latitude") is not None and a.get("longitude") is not None:
                roles.setdefault("gps", []).append(ent)
        # the device fleet (for offline / battery recipes), with last-seen as epoch
        devices: list[dict[str, Any]] = []
        for e in self.hass.config_entries.async_entries(DOMAIN):
            rt = getattr(e, "runtime_data", None)
            if rt is None or not hasattr(rt, "deveui"):
                continue
            devices.append({"id": rt.deveui.upper(), "name": e.title, "area": e.data.get("area"),
                            "online": bool(getattr(rt, "values", {}).get("online")),
                            "battery": _num(getattr(rt, "values", {}).get("battery")),
                            "last_seen_ts": _num(rt.meta.get("last_seen")) if hasattr(rt, "meta") else None})
        costs = {}
        for r in roles.get("costs", []):
            costs = r["attrs"]
            break
        return {"roles": roles, "devices": devices, "costs": costs, "site": site}

    # -- per-minute tick ---------------------------------------------------
    @callback
    def update(self, _now: Any = None) -> None:
        ts = time.time()
        local = datetime.fromtimestamp(ts, self.cal.tz)
        fires, snaps = self.engine.evaluate(self.recipes, self._ctx(), ts, local)
        running = sum(1 for s in snaps if s["enabled"])
        self.data = {"recipes": snaps, "running": running, "paused": len(snaps) - running,
                     "fired_today": sum(s["fired_today"] for s in snaps),
                     "catalog": [{"key": k, **{kk: c[kk] for kk in ("category", "icon", "title")},
                                  "sentence": sentence(default_recipe(k)),
                                  "enabled": any(r.get("catalog") == k for r in self.recipes)}
                                 for k, c in CATALOG.items()]}
        for f in fires:
            self.hass.async_create_task(self._run_fire(f))
        self._sync_jobs()   # close auto jobs whose sustained rule cleared
        if self.store is not None:
            self.store.async_delay_save(self._to_store, 20)
        async_dispatcher_send(self.hass, SIGNAL_RECIPES.format(self.entry.entry_id))

    @callback
    def maybe_update(self) -> None:
        self.update()

    def _to_store(self) -> dict[str, Any]:
        return {"recipes": self.recipes, "engine": self.engine.s}

    # -- running the actions of one fire -----------------------------------
    async def _run_fire(self, f: dict[str, Any]) -> None:
        title = f"{f['icon']} {f['title']}"
        for a in f.get("actions", []):
            t = a.get("type")
            try:
                if t == "notify":
                    await self._notify(self._targets(a.get("target")), title, f["message"])
                elif t == "raise_alert":
                    await self.hass.services.async_call(
                        "persistent_notification", "create",
                        {"title": f"{title} — {self.entry.title}", "message": f["message"],
                         "notification_id": f"ms_recipe_{f['recipe_id']}_{f['target_name']}"}, blocking=False)
                elif t == "press" and a.get("entity"):
                    ent = a["entity"]
                    dom = ent.split(".", 1)[0]
                    svc = {"button": "press", "input_button": "press", "script": "turn_on",
                           "switch": "turn_off"}.get(dom, "turn_off")
                    await self.hass.services.async_call(dom, svc, {"entity_id": ent}, blocking=False)
                elif t == "log":
                    _LOGGER.info("Recipe %s fired: %s", f["recipe_id"], f["message"])
                elif t == "create_job" and not f.get("test"):
                    self._raise_job(f)
            except Exception:  # noqa: BLE001 - one broken action must not stop the rest
                _LOGGER.warning("Recipe action %s failed", t, exc_info=True)
        if f.get("test"):
            # a manual test always leaves a visible confirmation (so "Test now" is never a silent no-op)
            try:
                await self.hass.services.async_call("persistent_notification", "create",
                    {"title": f"🧪 Recipe test — {f['title']}", "message": f["message"],
                     "notification_id": f"ms_recipe_test_{f['recipe_id']}"}, blocking=False)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Recipe test notice failed", exc_info=True)
        self.hass.bus.async_fire(f"{DOMAIN}_recipe", {"recipe_id": f["recipe_id"], "title": f["title"],
                                                      "message": f["message"], "hub": self.entry.title})

    # -- sensor → job loop -------------------------------------------------
    def _jobs(self):
        return getattr(getattr(self.entry, "runtime_data", None), "jobs", None)

    def _raise_job(self, f: dict[str, Any]) -> None:
        """A firing rule with a 'create a job' action raises a work order."""
        from .jobs_calc import CAT_PRIORITY, SUSTAINED
        jobs = self._jobs()
        if jobs is None:
            return
        c = CATALOG.get(f.get("catalog", ""), {})
        sustained = c.get("cond", {}).get("type") in SUSTAINED
        jobs.raise_from_rule(f, priority=CAT_PRIORITY.get(c.get("category"), "info"), auto_close=sustained)

    def _sync_jobs(self) -> None:
        """Close auto jobs whose sustained rule/target is no longer firing (the reading cleared)."""
        from .jobs_calc import SUSTAINED, rule_job_key
        jobs = self._jobs()
        if jobs is None:
            return
        active: set[str] = set()
        for inst in self.recipes:
            if not inst.get("enabled") or not any(a.get("type") == "create_job" for a in inst.get("actions", [])):
                continue
            c = CATALOG.get(inst.get("catalog", ""), {})
            if c.get("cond", {}).get("type") not in SUSTAINED:
                continue
            rt = self.engine.s.get("rt", {}).get(inst["id"], {})
            for key, stt in (rt.get("targets") or {}).items():
                if stt.get("since") is not None:
                    active.add(rule_job_key(inst["id"], key))
        jobs.sync_auto(active)
        jobs.sync_alerts()   # close swept alert-jobs whose alert has cleared

    def _targets(self, target: str | None) -> list[str]:
        if target and ("." in target):
            return [target]
        cfg = getattr(getattr(self.entry, "runtime_data", None), "alerts", None)
        cfg = getattr(cfg, "cfg", None)
        primary = list(getattr(cfg, "primary", []) or [])
        if target == "on_call" and cfg is not None:
            now = {t for sh in getattr(cfg, "rota", []) for t in sh.targets}
            return sorted(now) or primary
        return primary

    async def _notify(self, targets: list[str], title: str, message: str) -> None:
        for target in targets:
            domain, _, service = target.partition(".")
            if not service:
                domain, service = "notify", target
            try:
                await self.hass.services.async_call(domain, service,
                                                    {"title": title, "message": message}, blocking=False)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Recipe could not notify %s", target, exc_info=True)

    # -- mutations (called by the WebSocket) -------------------------------
    def _uid(self, catalog: str) -> str:
        if not any(r["id"] == catalog for r in self.recipes):
            return catalog
        i = 2
        while any(r["id"] == f"{catalog}_{i}" for r in self.recipes):
            i += 1
        return f"{catalog}_{i}"

    def enable(self, catalog: str) -> dict[str, Any]:
        if catalog not in CATALOG:
            raise ValueError(f"unknown recipe {catalog}")
        inst = default_recipe(catalog)
        inst["id"] = self._uid(catalog)
        self.recipes.append(inst)
        return inst

    def update_recipe(self, inst: dict[str, Any]) -> None:
        for i, r in enumerate(self.recipes):
            if r["id"] == inst.get("id"):
                self.recipes[i] = {**r, **inst}
                return
        raise ValueError("recipe not found")

    def toggle(self, rid: str, enabled: bool) -> None:
        for r in self.recipes:
            if r["id"] == rid:
                r["enabled"] = bool(enabled)
                return
        raise ValueError("recipe not found")

    def delete(self, rid: str) -> None:
        self.recipes = [r for r in self.recipes if r["id"] != rid]
        self.engine.s["rt"].pop(rid, None)

    def test(self, rid: str) -> dict[str, Any] | None:
        """Fire a recipe's actions once, now, and leave a visible confirmation (the Test button)."""
        r = next((x for x in self.recipes if x["id"] == rid), None)
        if r is None:
            return None
        c = CATALOG[r["catalog"]]
        parts = []
        for a in r.get("actions", []):
            t = a.get("type")
            if t == "notify":
                who = self._targets(a.get("target"))
                parts.append("notify " + (", ".join(who) if who else "(no notify target configured)"))
            elif t == "raise_alert":
                parts.append("raise an alert")
            elif t == "press":
                parts.append("switch " + (a.get("entity") or "(no entity set)"))
            elif t == "log":
                parts.append("log")
            elif t == "create_job":
                parts.append("create a job")
        summary = "; ".join(parts) or "do nothing (no actions set)"
        fire = {"recipe_id": rid, "catalog": r["catalog"], "icon": c["icon"], "title": c["title"],
                "target_name": "Test", "detail": "manual test",
                "message": f"Manual test — this recipe would: {summary}.",
                "actions": r.get("actions", []), "ts": time.time(), "test": True}
        self.hass.async_create_task(self._run_fire(fire))
        return {"ok": True, "summary": summary}


class RecipeSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Rules"
    _attr_icon = "mdi:script-text-outline"
    _attr_native_unit_of_measurement = "running"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mgr: RecipeManager) -> None:
        self.hass, self.entry, self.mgr = hass, entry, mgr
        self._attr_device_info = hub_device(entry)
        self._attr_unique_id = f"{entry.entry_id}_recipes"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_RECIPES.format(self.entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self):
        return self.mgr.data.get("running") if self.mgr.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"milesight_role": "recipes", "site": self.entry.title, "hub": self.entry.entry_id,
                **(self.mgr.data or {})}


async def async_setup_recipes(hass: HomeAssistant, entry: ConfigEntry) -> tuple[RecipeManager, list]:
    from homeassistant.helpers.storage import Store

    mgr = RecipeManager(hass, entry)
    mgr.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.recipes_{entry.entry_id}")
    saved = await mgr.store.async_load()
    if isinstance(saved, dict):
        mgr.recipes = saved.get("recipes") or []
        if isinstance(saved.get("engine"), dict):
            mgr.engine = RecipeEngine(mgr.cal, saved["engine"])
    mgr.update()
    ent = RecipeSensor(hass, entry, mgr)
    entry.async_on_unload(async_track_time_interval(hass, mgr.update, timedelta(seconds=60)))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_FLEET, mgr.maybe_update))
    return mgr, [ent]
