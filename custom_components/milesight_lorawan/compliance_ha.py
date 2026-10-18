"""Cold-room compliance reports on the Home Assistant side: find the fridges / freezers / cold rooms, read their
temperature and door history from the recorder (hourly long-term statistics where the raw history has been
purged), write one PDF per unit to /config/www/milesight/compliance/ and e-mail them through a notify service –
weekly (Monday) and / or monthly (the 1st), plus on demand."""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_DEVICE, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

CONF_COMPLIANCE_SCHEDULE = "compliance_schedule"     # off | weekly | monthly | both
CONF_COMPLIANCE_NOTIFY = "compliance_notify"         # notify services, e.g. notify.smtp_haccp (comma separated)
CONF_COMPLIANCE_HOUR = "compliance_hour"
CONF_COMPLIANCE_ATTACH = "compliance_attach"
DEFAULT_COMPLIANCE_SCHEDULE = "weekly"
DEFAULT_COMPLIANCE_HOUR = 6
SIGNAL_COMPLIANCE = f"{DOMAIN}_compliance_{{}}"
KEEP = 200


def notify_services(value: Any) -> list[str]:
    """'notify.smtp_a, smtp_b' -> ['notify.smtp_a', 'notify.smtp_b']."""
    items = value if isinstance(value, list) else re.split(r"[,\s;]+", str(value or ""))
    out = []
    for x in items:
        x = str(x).strip()
        if not x:
            continue
        out.append(x if x.startswith("notify.") else f"notify.{x}")
    return out


def cold_units(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Every cold-chain temperature probe with its entity ids and the door contact of the same unit (on the device
    itself, or a door contact with the same purpose in the same area)."""
    reg = er.async_get(hass)
    probes, doors = [], []
    for e in hass.config_entries.async_entries(DOMAIN):
        rt = getattr(e, "runtime_data", None)
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE or rt is None or not hasattr(rt, "purpose"):
            continue
        p = rt.purpose
        if p is None or p.group != "cold_chain":
            continue
        door = reg.async_get_entity_id("binary_sensor", DOMAIN, f"{rt.deveui}_door_active") \
            if "contact" in getattr(rt, "_pfam", ()) else None
        if getattr(rt, "tempw", None) is not None:
            key = "temperature" if "temperature" in rt.raw or "temperature_1" not in rt.raw else "temperature_1"
            temp = reg.async_get_entity_id("sensor", DOMAIN, f"{rt.deveui}_{key}")
            if temp:
                probes.append({"rt": rt, "temp": temp, "door": door})
        elif door:
            doors.append({"rt": rt, "door": door})
    for pr in probes:
        if pr["door"] is None:
            area = pr["rt"].entry.data.get("area")
            same = [d for d in doors if area and d["rt"].entry.data.get("area") == area
                    and d["rt"].purpose.key == pr["rt"].purpose.key]
            if len(same) == 1:
                pr["door"] = same[0]["door"]
    return sorted(probes, key=lambda x: ((x["rt"].entry.data.get("area") or "~").lower(), x["rt"].entry.title.lower()))


def _unit(rt: Any):
    from .compliance import Unit
    c = rt.pcfg
    return Unit(name=rt.entry.title, area=rt.entry.data.get("area"), kind=rt.purpose.label, model=rt.model.key,
                deveui=rt.deveui, low=c.get("temp_low"), high=c.get("temp_high"),
                delay_min=float(c.get("temp_delay_min") or 0), left_open_min=c.get("left_open_min"),
                max_gap_s=max(3700.0, float(getattr(rt, "max_gap_s", 7200) or 7200)))


async def _history(hass: HomeAssistant, start: datetime, end: datetime, entity_ids: list[str]):
    """Raw state changes (incl. the state at the start) and, for the part the recorder has purged, hourly
    statistics: ({eid: [(ts, state)]}, {eid: [(ts, min, mean, max)]})."""
    from homeassistant.components.recorder import get_instance, history
    inst = get_instance(hass)
    raw: dict[str, list] = {}
    for eid in entity_ids:
        states = await inst.async_add_executor_job(
            lambda e=eid: history.state_changes_during_period(hass, start, end, e, no_attributes=True,
                                                               include_start_time_state=True))
        raw[eid] = [(s.last_updated.timestamp(), s.state) for s in states.get(eid, [])]
    hourly: dict[str, list] = {}
    try:
        from homeassistant.components.recorder.statistics import statistics_during_period
        stats = await inst.async_add_executor_job(
            lambda: statistics_during_period(hass, start, end, set(entity_ids), "hour", None, {"min", "mean", "max"}))
        for eid, rows in (stats or {}).items():
            out = []
            for r in rows:
                st = r.get("start")
                ts = st.timestamp() if hasattr(st, "timestamp") else float(st)
                out.append((ts, r.get("min"), r.get("mean"), r.get("max")))
            hourly[eid] = out
    except Exception as err:  # noqa: BLE001 - statistics are only the fallback
        _LOGGER.debug("No long-term statistics for the compliance report: %s", err)
    return raw, hourly


class ComplianceManager:
    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self.hass, self.entry = hass, entry
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.compliance_{entry.entry_id}")
        self.data: dict[str, Any] = {"reports": [], "done": []}
        self._unsubs: list = []

    @property
    def schedule(self) -> str:
        return self.entry.options.get(CONF_COMPLIANCE_SCHEDULE, DEFAULT_COMPLIANCE_SCHEDULE)

    async def async_start(self) -> None:
        from homeassistant.helpers.event import async_call_later, async_track_time_change
        self.data = await self.store.async_load() or {"reports": [], "done": []}
        hour = int(self.entry.options.get(CONF_COMPLIANCE_HOUR, DEFAULT_COMPLIANCE_HOUR))
        self._unsubs.append(async_track_time_change(self.hass, self._scheduled, hour=hour, minute=5, second=0))
        self._unsubs.append(async_call_later(self.hass, 300, self._catch_up))

    async def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    def _kinds_due(self, now: datetime) -> list[str]:
        sched = self.schedule
        kinds = []
        if sched in ("weekly", "both"):
            kinds.append("week")
        if sched in ("monthly", "both"):
            kinds.append("month")
        return kinds

    async def _scheduled(self, now: datetime) -> None:
        now = dt_util.as_local(now)
        for kind in self._kinds_due(now):
            if (kind == "week" and now.weekday() == 0) or (kind == "month" and now.day == 1):
                await self._run_period(kind, now)

    async def _catch_up(self, _now: Any = None) -> None:
        """Home Assistant was off when a report was due: create the missing one (last complete period only)."""
        now = dt_util.now()
        hour = int(self.entry.options.get(CONF_COMPLIANCE_HOUR, DEFAULT_COMPLIANCE_HOUR))
        if now.hour < hour:
            return
        for kind in self._kinds_due(now):
            await self._run_period(kind, now)

    async def _run_period(self, kind: str, now: datetime) -> None:
        from .compliance import period_bounds
        start, end, _label = period_bounds(kind, now)
        key = f"{kind}:{start.date().isoformat()}"
        if key in self.data.get("done", []) or not cold_units(self.hass):
            return
        try:
            await self.async_create(kind, now=now, send=True)
        except Exception:  # noqa: BLE001 - try again tomorrow / at the next start
            _LOGGER.exception("Compliance reports for %s could not be created", key)
            return
        self.data.setdefault("done", []).append(key)
        self.data["done"] = self.data["done"][-60:]
        await self.store.async_save(self.data)

    async def async_create(self, kind: str = "week", start: datetime | None = None, end: datetime | None = None,
                           now: datetime | None = None, device_ids: list[str] | None = None,
                           send: bool = True, by: str | None = None) -> dict[str, Any]:
        """Create the reports for every cold unit (or the given devices) and send them."""
        from .building import site_info
        from .compliance import analyse, period_bounds, report_pdf, summary_line
        now = now or dt_util.now()
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
        if start is None or end is None:
            start, end, label = period_bounds(kind, now)
        else:
            start, end = dt_util.as_local(start), dt_util.as_local(end)
            label = f"{start:%d %b %Y} – {(end - timedelta(seconds=1)):%d %b %Y}"
            kind = "custom"
        units = cold_units(self.hass)
        if device_ids:
            from homeassistant.helpers import device_registry as dr
            dreg = dr.async_get(self.hass)
            wanted = set()
            for did in device_ids:
                dev = dreg.async_get(did)
                for ident in (dev.identifiers if dev else ()):
                    if ident[0] == DOMAIN:
                        wanted.add(str(ident[1]).lower())
            units = [u for u in units if u["rt"].deveui.lower() in wanted]
        if not units:
            raise ValueError("No fridge, freezer or cold-room probes – set a temperature sensor's purpose to "
                             "Fridge / cold room or Freezer first")
        site = site_info(self.hass, self.entry)
        created = dt_util.now().strftime("%d %b %Y %H:%M")
        folder = self.hass.config.path("www", "milesight", "compliance", f"{start:%Y}")
        token = secrets.token_hex(6)                     # /local/ is not behind the login: unguessable names
        files, results, lines = [], [], []
        for u in units:
            rt = u["rt"]
            unit = _unit(rt)
            ids = [u["temp"]] + ([u["door"]] if u["door"] else [])
            raw, hourly = await _history(self.hass, start - timedelta(hours=6), end, ids)
            from .compliance import merge_hourly
            temps, raw_from = merge_hourly(raw.get(u["temp"], []), hourly.get(u["temp"], []), start.timestamp())
            actions = [{"ts": float(x.get("at") or 0), "text": x.get("text") or "", "by": x.get("by")}
                       for x in rt.meta.get("_service_log", []) if x.get("kind") == "corrective_action"]
            res = analyse(unit, temps, raw.get(u["door"]) if u["door"] else None, start.timestamp(),
                          end.timestamp(), tz, actions)
            if raw_from:
                res["reasons"] = list(res["reasons"])
                note = (f"before {datetime.fromtimestamp(raw_from, tz):%d %b %H:%M} only hourly statistics were "
                        f"kept by the recorder")
                res.setdefault("notes", []).append(note)
            pdf = report_pdf(site, unit, res, temps, label, created, tz)
            slug = re.sub(r"[^a-z0-9]+", "-", unit.name.lower()).strip("-") or "unit"
            name = f"{slug}-{kind}-{start:%Y%m%d}-{token}.pdf"
            files.append((f"{folder}/{name}", pdf))
            url = f"/local/milesight/compliance/{start:%Y}/{name}"
            results.append({"unit": unit.name, "area": unit.area, "device": rt.deveui, "kind": kind,
                            "period": label, "start": start.isoformat(), "end": end.isoformat(),
                            "status": res["status"], "min": res["min"], "max": res["max"],
                            "out_min": res["out_min"], "excursions": len(res["excursions"]),
                            "coverage": res["coverage"], "url": url, "path": f"{folder}/{name}",
                            "created": dt_util.now().isoformat(), "by": by})
            lines.append(summary_line(unit.name, res))

        def _write() -> None:
            import os
            os.makedirs(folder, exist_ok=True)
            for path, data in files:
                with open(path, "wb") as f:
                    f.write(data)
        await self.hass.async_add_executor_job(_write)

        self.data.setdefault("reports", [])[:0] = results
        del self.data["reports"][KEEP:]
        await self.store.async_save(self.data)
        async_dispatcher_send(self.hass, SIGNAL_COMPLIANCE.format(self.entry.entry_id))
        bad = [r for r in results if r["status"] != "compliant"]
        title = (f"Cold-chain records {label}: " +
                 ("all compliant" if not bad else f"{len(bad)} of {len(results)} need attention"))
        body = "\n".join(f"- {ln}" for ln in lines)
        from homeassistant.components import persistent_notification
        persistent_notification.async_create(
            self.hass, body + "\n\n" + "\n".join(f"[{r['unit']} (PDF)]({r['url']})" for r in results),
            title=f"Milesight LoRaWAN: {title}", notification_id=f"{DOMAIN}_compliance")
        sent = []
        if send:
            sent = await self._send(title, body, results)
        self.hass.bus.async_fire(f"{DOMAIN}_compliance_report", {
            "period": label, "kind": kind, "reports": [{k: r[k] for k in ("unit", "area", "status", "url", "path")}
                                                       for r in results]})
        return {"period": label, "reports": results, "sent_to": sent}

    async def _send(self, title: str, body: str, results: list[dict[str, Any]]) -> list[str]:
        services = notify_services(self.entry.options.get(CONF_COMPLIANCE_NOTIFY))
        attach = bool(self.entry.options.get(CONF_COMPLIANCE_ATTACH, True))
        base = None
        try:
            from homeassistant.helpers.network import get_url
            base = get_url(self.hass, prefer_external=True)
        except Exception:  # noqa: BLE001 - no URL configured: plain paths
            base = None
        links = "\n".join(f"{r['unit']}: {(base or '') + r['url']}" for r in results)
        sent = []
        for svc in services:
            domain, _, name = svc.partition(".")
            if not self.hass.services.has_service(domain, name):
                _LOGGER.warning("Compliance reports: %s does not exist", svc)
                continue
            data: dict[str, Any] = {"title": title, "message": f"{body}\n\n{links}"}
            if attach:
                data["data"] = {"images": [r["path"] for r in results]}     # SMTP: sent as attachments
            try:
                await self.hass.services.async_call(domain, name, data, blocking=True)
                sent.append(svc)
            except Exception as err:  # noqa: BLE001 - e.g. a notifier that rejects 'images': send the links only
                _LOGGER.warning("Compliance reports via %s with attachments failed (%s) – sending links", svc, err)
                try:
                    await self.hass.services.async_call(domain, name, {"title": title,
                                                                       "message": f"{body}\n\n{links}"},
                                                        blocking=True)
                    sent.append(svc)
                except Exception as err2:  # noqa: BLE001
                    _LOGGER.error("Compliance reports could not be sent via %s: %s", svc, err2)
        return sent

    @callback
    def reports(self, n: int = 40) -> list[dict[str, Any]]:
        return [{k: v for k, v in r.items() if k != "path"} for r in self.data.get("reports", [])[:n]]
