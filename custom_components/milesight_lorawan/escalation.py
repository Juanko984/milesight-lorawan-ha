"""Alert escalation on the gateway (hub) entry: collects alerts from every Milesight device, the building and
the gateways, and sends / escalates / clears Companion-app notifications. The rules are in alerts.py."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .alerts import ACTION_ACK, ACTION_RUN, DEFAULT_CATEGORIES, AlertEngine, AlertSettings, device_alerts, notify_data
from .const import (
    CONF_ALERT_ACTION_ENTITY,
    CONF_ALERT_ACTION_TITLE,
    CONF_ALERT_BACKUP,
    CONF_ALERT_CATEGORIES,
    CONF_ALERT_DEDUPE_MIN,
    CONF_ALERT_ESCALATE_MIN,
    CONF_ALERT_PRIMARY,
    CONF_ALERT_QUIET_END,
    CONF_ALERT_QUIET_START,
    CONF_ALERT_REPEAT_MIN,
    CONF_ALERT_RESOLVED,
    DOMAIN,
    SIGNAL_ALERTS,
    SIGNAL_ALERTS_CHANGED,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def alert_settings(opts: dict[str, Any]) -> AlertSettings:
    def hour(key: str) -> int | None:
        v = opts.get(key)
        return None if v in (None, "") else int(v) % 24
    qs, qe = hour(CONF_ALERT_QUIET_START), hour(CONF_ALERT_QUIET_END)
    return AlertSettings(
        primary=[t for t in opts.get(CONF_ALERT_PRIMARY) or [] if t],
        backup=[t for t in opts.get(CONF_ALERT_BACKUP) or [] if t],
        escalate_min=float(opts.get(CONF_ALERT_ESCALATE_MIN, 15) or 15),
        repeat_min=float(opts.get(CONF_ALERT_REPEAT_MIN, 0) or 0),
        quiet_start=qs if qs != qe else None, quiet_end=qe if qs != qe else None,
        dedupe_min=float(opts.get(CONF_ALERT_DEDUPE_MIN, 30) or 0),
        notify_resolved=bool(opts.get(CONF_ALERT_RESOLVED, True)),
        categories=tuple(opts.get(CONF_ALERT_CATEGORIES) or DEFAULT_CATEGORIES),
        action_title=(opts.get(CONF_ALERT_ACTION_TITLE) or "Start pump") if opts.get(CONF_ALERT_ACTION_ENTITY) else "",
    )


class AlertManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub) -> None:
        self.hass, self.entry, self.hub = hass, entry, hub
        self.cfg = alert_settings(dict(entry.options))
        self.action_entity: str | None = entry.options.get(CONF_ALERT_ACTION_ENTITY) or None
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.alerts_{entry.entry_id}")
        self.engine = AlertEngine()
        self._unsubs: list = []
        self._pending = None
        self._stopped = False
        self.last_sent: dict[str, Any] | None = None
        self._keep: tuple[str, ...] = ()

    async def async_start(self) -> None:
        self.engine = AlertEngine(await self.store.async_load())
        self._unsubs.append(async_dispatcher_connect(self.hass, SIGNAL_ALERTS, self._soon))
        self._unsubs.append(async_track_time_interval(self.hass, self._run, timedelta(seconds=60)))
        self._unsubs.append(self.hass.bus.async_listen("mobile_app_notification_action", self._on_action))
        self._soon(30)                                     # let the devices load first

    async def async_stop(self) -> None:
        self._stopped = True
        while self._unsubs:
            self._unsubs.pop()()
        if self._pending:
            self._pending()
            self._pending = None
        await self.store.async_save(self.engine.to_dict())

    # ------------------------------------------------------------- collect
    def is_owner(self) -> bool:
        """Devices are not tied to a gateway entry: with several gateway entries only the first one that has
        escalation set up sends alerts (so nobody gets everything twice)."""
        hubs = self.hass.data.get(DOMAIN, {}).get("hubs", {})
        for eid in sorted(hubs):
            if hubs[eid].alerts.cfg.enabled:
                return eid == self.entry.entry_id
        return True

    def active(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        keep: list[str] = []
        for e in self.hass.config_entries.async_entries(DOMAIN):
            if e.data.get("entry_type") == "hub":
                continue
            rt = getattr(e, "runtime_data", None)
            if rt is None or not hasattr(rt, "deveui") or not rt.values:
                if e.data.get("deveui"):
                    keep.append(f"{e.data['deveui']}:")       # not loaded (yet): keep its alerts as they are
                continue
            out.update(device_alerts(e.title, rt.deveui, rt.values, e.data.get("area")))
        building = getattr(self.hub, "building", None)
        if building is None or not building.data:
            keep.append("building:")
        self._keep = tuple(keep)
        for a in (building.data.get("alerts", []) if building is not None else []):
            if a["key"].split(":", 1)[0] in ("co2", "rh", "t"):
                out[f"building:{a['key']}"] = {"title": f"{a['what']} – {a['where']}", "severity": "warning",
                                               "message": f"{a['where']}: {a['what']}. {a['detail']}.",
                                               "category": "building"}
        ts = time.time()
        for gid, g in self.hub.stats.gateways.items():
            if self.hub.stats.online(gid, ts, self.hub.offline_s) is False:
                name = g.get("name") or gid
                out[f"gw:{gid}"] = {"title": f"Gateway offline – {name}", "severity": "critical",
                                    "category": "gateways",
                                    "message": f"{name} has not forwarded any packets – sensors there are not heard."}
        return out

    # ----------------------------------------------------------------- run
    @callback
    def _soon(self, delay: Any = 3) -> None:
        if self._pending is None and not self._stopped:
            self._pending = async_call_later(self.hass, delay if isinstance(delay, (int, float)) else 3, self._later)

    async def _later(self, _now: Any = None) -> None:
        self._pending = None
        await self._run()

    async def _run(self, _now: Any = None) -> None:
        if self._stopped:
            return
        if not self.is_owner():
            if self.engine.alerts:
                self.engine.alerts.clear()
                async_dispatcher_send(self.hass, SIGNAL_ALERTS_CHANGED.format(self.entry.entry_id))
            return
        ts = time.time()
        local = datetime.fromtimestamp(ts, dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC)
        active = self.active()
        msgs = self.engine.update(active, ts, local, self.cfg, self._keep)
        await self._send(msgs)
        self.store.async_delay_save(self.engine.to_dict, 30)
        async_dispatcher_send(self.hass, SIGNAL_ALERTS_CHANGED.format(self.entry.entry_id))

    async def _send(self, msgs: list[dict[str, Any]]) -> None:
        for m in msgs:
            data = notify_data(m)
            for target in m["targets"]:
                domain, _, service = target.partition(".")
                if not service:
                    domain, service = "notify", target
                try:
                    await self.hass.services.async_call(domain, service, data, blocking=False)
                except Exception:  # noqa: BLE001 - one broken phone must not stop the others
                    _LOGGER.warning("Could not notify %s", target, exc_info=True)
            self.last_sent = {"kind": m["kind"], "title": m["title"], "targets": m["targets"], "at": time.time()}
            if m["kind"] != "clear":
                self.hass.bus.async_fire(f"{DOMAIN}_alert", {"alert_id": m["id"], "key": m["key"], "kind": m["kind"],
                                                             "title": m["title"], "message": m["message"],
                                                             "targets": m["targets"], "hub": self.entry.title})

    # ------------------------------------------------------------- actions
    async def async_acknowledge(self, alert_id: str | None = None, by: str | None = None) -> int:
        before = len(self.engine.unacknowledged())
        await self._send(self.engine.acknowledge(alert_id, time.time(), by))
        self.store.async_delay_save(self.engine.to_dict, 5)
        async_dispatcher_send(self.hass, SIGNAL_ALERTS_CHANGED.format(self.entry.entry_id))
        return before - len(self.engine.unacknowledged())

    async def _run_action(self) -> None:
        ent = self.action_entity
        if not ent:
            return
        domain = ent.split(".", 1)[0]
        service = {"button": "press", "input_button": "press", "script": "turn_on"}.get(domain, "turn_on")
        await self.hass.services.async_call(domain, service, {"entity_id": ent}, blocking=False)

    async def _on_action(self, event: Event) -> None:
        action = str(event.data.get("action") or "")
        if not action.startswith((ACTION_ACK, ACTION_RUN)):
            return
        aid = action.removeprefix(ACTION_ACK).removeprefix(ACTION_RUN)
        if self.engine.by_id(aid) is None:
            return                                        # another hub's alert
        user = None
        if event.context and event.context.user_id:
            u = await self.hass.auth.async_get_user(event.context.user_id)
            user = u.name if u else None
        if action.startswith(ACTION_RUN):
            await self._run_action()
        await self.async_acknowledge(aid, user)
