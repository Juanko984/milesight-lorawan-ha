"""Alert escalation: notify the primary people, escalate to the backup when nobody acknowledges, repeat,
hold non-critical alerts during quiet hours, suppress duplicates of flapping alerts and send 'resolved'.
Pure Python (unit-tested); hub.py feeds it the active alerts and sends what it returns.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CATEGORIES = ("safety", "cold_chain", "security", "tank", "pumps", "irrigation", "energy", "facilities", "building",
              "devices", "gateways", "commands")
DEFAULT_CATEGORIES = ["safety", "cold_chain", "security", "tank", "pumps", "irrigation", "energy", "facilities",
                      "devices", "gateways"]
# purpose group -> alert category
GROUP_CATEGORY = {"cold_chain": "cold_chain", "security": "security", "energy": "energy", "hvac": "energy",
                  "pump": "pumps", "water": "safety", "tank": "tank", "irrigation": "irrigation",
                  "facilities": "facilities", "assets": "devices", "comfort": "building", "people": "building"}
_CATEGORIES_V1 = ("safety", "tank", "building", "devices", "gateways", "commands")   # before 0.24
_CATEGORIES_V2 = ("safety", "tank", "pumps", "irrigation", "building", "devices", "gateways", "commands")   # 0.24


def effective_categories(opts: dict[str, Any]) -> tuple[str, ...]:
    """The chosen alert categories; categories added after the choice was saved start switched on."""
    chosen = opts.get("alert_categories")
    if not chosen:
        return tuple(DEFAULT_CATEGORIES)
    known = opts.get("alert_categories_known") or _CATEGORIES_V1
    return tuple(c for c in CATEGORIES if c in chosen or (c in DEFAULT_CATEGORIES and c not in known))
ACTION_ACK = "MSL_ACK_"
ACTION_RUN = "MSL_RUN_"
ACTION_SNOOZE = "MSL_SNZ_"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HISTORY_DAYS = 35


@dataclass
class Shift:
    """One line of the on-call rota: who is first in line on these days between these times."""
    days: frozenset[int]                  # 0 = Monday
    start: int                            # minutes after midnight
    end: int                              # minutes; end <= start runs past midnight; start == end = all day
    targets: tuple[str, ...]

    def covers(self, local: datetime) -> bool:
        m = local.hour * 60 + local.minute
        day = local.weekday()
        if self.start == self.end:
            return day in self.days
        if self.start < self.end:
            return day in self.days and self.start <= m < self.end
        # overnight: the evening part belongs to the listed day, the morning part to the day after
        return (day in self.days and m >= self.start) or ((day - 1) % 7 in self.days and m < self.end)


class RotaError(ValueError):
    """A rota / quiet-hours line could not be read."""


def _minutes(text: str) -> int:
    t = text.strip()
    if ":" in t:
        h, m = t.split(":", 1)
    else:
        h, m = t, "0"
    h_, m_ = int(h), int(m)
    if not (0 <= h_ <= 24 and 0 <= m_ < 60) or (h_ == 24 and m_):
        raise ValueError(t)
    return (h_ * 60 + m_) % 1440


def _days(text: str) -> frozenset[int]:
    t = text.strip().lower()
    if t in ("*", "daily", "every day", "all", ""):
        return frozenset(range(7))
    if t in ("weekdays", "workdays"):
        return frozenset(range(5))
    if t in ("weekend", "weekends"):
        return frozenset({5, 6})
    out: set[int] = set()
    for part in t.split(","):
        part = part.strip()
        if "-" in part:
            a, b = (DAYS.index(x.strip()[:3]) for x in part.split("-", 1))
            i = a
            while True:
                out.add(i)
                if i == b:
                    break
                i = (i + 1) % 7
        elif part:
            out.add(DAYS.index(part[:3]))
    return frozenset(out)


def parse_rota(text: str | None) -> list[Shift]:
    """Lines like  'Mon-Fri 07:00-17:00: notify.mobile_app_juan'  ·  'Weekend: notify.mobile_app_sam, notify.x'
    · '* 17-07: notify.mobile_app_piet'. The first line that covers the moment is on call."""
    shifts: list[Shift] = []
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # the colon right before the first notify target separates 'when' from 'who'
        idx = line.find("notify.")
        head = line[:idx].rstrip() if idx >= 0 else line
        if idx < 0 or not head.endswith(":"):
            raise RotaError(f"line {n}: write it as 'days hours: notify.target, …'")
        when, who = head[:-1].strip(), line[idx:]
        targets = tuple(t.strip() for t in who.split(",") if t.strip())
        parts = when.split()
        hours = next((p for p in parts if "-" in p and any(ch.isdigit() for ch in p)), None)
        days_txt = " ".join(p for p in parts if p != hours)
        try:
            days = _days(days_txt)
            start, end = (_minutes(x) for x in hours.split("-", 1)) if hours else (0, 0)
        except (ValueError, IndexError) as err:
            raise RotaError(f"line {n}: cannot read '{when}' ({err})") from err
        if not days or not targets:
            raise RotaError(f"line {n}: needs days and at least one notify target")
        shifts.append(Shift(days, start, end, targets))
    return shifts


def parse_category_quiet(text: str | None) -> dict[str, tuple[int, int] | None]:
    """Lines like 'building: 18-07' · 'devices: 20:00-06:30' · 'safety: none' (never held). Hours as minutes."""
    out: dict[str, tuple[int, int] | None] = {}
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        cat, sep, rest = line.partition(":")
        cat, rest = cat.strip().lower().replace(" ", "_"), rest.strip().lower()
        if not sep or cat not in CATEGORIES:
            raise RotaError(f"line {n}: start with a category ({', '.join(CATEGORIES)})")
        if rest in ("none", "never", "off", "-"):
            out[cat] = None
            continue
        try:
            a, b = (_minutes(x) for x in rest.replace(" ", "").split("-", 1))
        except (ValueError, IndexError) as err:
            raise RotaError(f"line {n}: hours like 18-07 or 18:00-06:30") from err
        out[cat] = (a, b)
    return out


@dataclass
class AlertSettings:
    primary: list[str] = field(default_factory=list)       # notify services ("notify.mobile_app_juan")
    backup: list[str] = field(default_factory=list)
    escalate_min: float = 15
    repeat_min: float = 0                                   # 0 = no reminders
    quiet_start: int | None = None                          # hour; None = no quiet hours
    quiet_end: int | None = None
    dedupe_min: float = 30                                  # a re-trigger within this time continues the old alert
    notify_resolved: bool = True
    categories: tuple[str, ...] = tuple(DEFAULT_CATEGORIES)
    action_title: str = ""                                  # e.g. "Start pump" (shown on tank alerts)
    rota: list[Shift] = field(default_factory=list)          # on call first; primary when nobody is on call
    category_quiet: dict[str, tuple[int, int] | None] = field(default_factory=dict)   # minutes; None = never quiet
    snooze_min: float = 60
    dashboards: dict[str, str] = field(default_factory=dict)  # category -> dashboard path for "Open dashboard"

    @property
    def enabled(self) -> bool:
        return bool(self.primary or self.rota)

    def first_line(self, local: datetime) -> list[str]:
        """Who is notified first right now: the on-call people of the rota, else the primary people."""
        for sh in self.rota:
            if sh.covers(local):
                return list(sh.targets)
        return list(self.primary)

    def quiet(self, category: str | None, local: datetime) -> bool:
        hm = local.hour + local.minute / 60
        if category in self.category_quiet:
            q = self.category_quiet[category]
            return q is not None and in_quiet(hm, q[0] / 60, q[1] / 60)
        return in_quiet(hm, self.quiet_start, self.quiet_end)

    def dashboard(self, category: str | None) -> str | None:
        return self.dashboards.get(category or "") or self.dashboards.get("*")


def in_quiet(hour_min: float, start: float | None, end: float | None) -> bool:
    """hour_min: local time as fractional hours."""
    if start is None or end is None or start == end:
        return False
    return start <= hour_min < end if start < end else (hour_min >= start or hour_min < end)


def alert_id(key: str, first: float) -> str:
    return hashlib.sha1(f"{key}|{int(first)}".encode()).hexdigest()[:10]


class AlertEngine:
    """state per alert key: id, title, message, severity, category, first, sent_at, level (0 held, 1 first line,
    2… escalated one person further along the backup list each time), acked (by / at), snoozed_until, resolved_at,
    notified (targets). history: one record per alert of the last 5 weeks, for the weekly summary."""

    def __init__(self, state: dict | None = None) -> None:
        st = state or {}
        self.alerts: dict[str, dict[str, Any]] = {k: dict(v) for k, v in st.get("alerts", {}).items()}
        self.history: list[dict[str, Any]] = [dict(h) for h in st.get("history", [])]
        self.summary_sent: str | None = st.get("summary_sent")

    def to_dict(self) -> dict[str, Any]:
        return {"alerts": self.alerts, "history": self.history, "summary_sent": self.summary_sent}

    # ------------------------------------------------------------- queries
    def open_alerts(self) -> list[dict[str, Any]]:
        return [a | {"key": k} for k, a in self.alerts.items() if a.get("resolved_at") is None]

    def unacknowledged(self) -> list[dict[str, Any]]:
        return [a for a in self.open_alerts() if not a.get("acked")]

    def by_id(self, aid: str) -> tuple[str, dict[str, Any]] | None:
        return next(((k, a) for k, a in self.alerts.items() if a["id"] == aid), None)

    def _hist(self, aid: str) -> dict[str, Any] | None:
        return next((h for h in reversed(self.history) if h["id"] == aid), None)

    # ------------------------------------------------------------- actions
    def acknowledge(self, aid: str | None, ts: float, by: str | None = None) -> list[dict[str, Any]]:
        """Acknowledge one alert (or all open ones). Returns the 'acknowledged' messages for the phones."""
        out = []
        for k, a in self.alerts.items():
            if a.get("resolved_at") is not None or a.get("acked") or (aid is not None and a["id"] != aid):
                continue
            a["acked"] = {"by": by, "at": ts}
            a["snoozed_until"] = None
            h = self._hist(a["id"])
            if h is not None and h.get("acked_at") is None:
                h.update(acked_at=ts, acked_by=by)
            if a.get("notified"):
                # same tag: replaces the alert on every phone (and removes its buttons)
                out.append({"targets": list(a["notified"]), "kind": "acknowledged", "id": a["id"], "key": k,
                            "title": f"✔ {a['title']}", "critical": False, "action": None,
                            "message": f"Acknowledged{(' by ' + by) if by else ''}: {a['message']}"})
        return out

    def snooze(self, aid: str, ts: float, minutes: float, by: str | None = None) -> list[dict[str, Any]]:
        """Hold reminders and escalation of one alert for a while; it comes back if it is still active."""
        found = self.by_id(aid)
        if found is None:
            return []
        k, a = found
        if a.get("resolved_at") is not None or a.get("acked"):
            return []
        a["snoozed_until"] = ts + minutes * 60
        a["snoozed_by"] = by
        h = self._hist(aid)
        if h is not None:
            h["snoozes"] = h.get("snoozes", 0) + 1
        label = _duration(minutes)
        return [{"targets": list(a.get("notified") or []), "kind": "snoozed", "id": a["id"], "key": k,
                 "title": f"⏸ {a['title']}", "critical": False, "action": None, "url": a.get("url"),
                 "message": f"Snoozed for {label}{(' by ' + by) if by else ''}: {a['message']}"}]

    # ----------------------------------------------------------- main loop
    def update(self, active: dict[str, dict[str, Any]], ts: float, local: datetime,
               cfg: AlertSettings, keep: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        """active: {key: {title, message, severity ('critical' | 'warning'), category, action?}}.
        keep: key prefixes whose source is not loaded yet (their alerts are neither resolved nor dropped).
        Returns notifications [{targets, kind (new | reminder | escalated | again | snooze_over | resolved), id,
        key, title, message, critical, action, url}]."""
        out: list[dict[str, Any]] = []
        active = {k: a for k, a in active.items() if a.get("category") in cfg.categories}
        resolve_after = min(cfg.dedupe_min, 5) * 60        # 'resolved' only once it stays resolved this long

        for k, a in active.items():
            cur = self.alerts.get(k)
            again = False
            if cur is not None and cur.get("resolved_at") is not None:
                if ts - cur["resolved_at"] <= cfg.dedupe_min * 60:
                    cur["flaps"] = cur.get("flaps", 0) + 1      # flapping: the same alert continues …
                    h = self._hist(cur["id"])
                    if h is not None:
                        h["flaps"] = h.get("flaps", 0) + 1
                        h["resolved_at"] = None
                    again = bool(cur.get("resolved_sent"))      # … people were told it was resolved: tell them again
                    cur.update(resolved_at=None, resolved_sent=False)
                    if again:
                        cur["acked"] = None
                else:
                    cur = None
            if cur is None:
                cur = {"id": alert_id(k, ts), "first": ts, "level": 0, "sent_at": None, "level_at": None,
                       "acked": None, "resolved_at": None, "notified": [], "snoozed_until": None}
                self.alerts[k] = cur
                self.history.append({"id": cur["id"], "key": k, "title": a["title"], "category": a.get("category"),
                                     "severity": a.get("severity", "warning"), "first": ts, "acked_at": None,
                                     "acked_by": None, "resolved_at": None, "flaps": 0, "level": 0, "snoozes": 0})
            cur.update(title=a["title"], message=a["message"], severity=a.get("severity", "warning"),
                       category=a.get("category"), action=a.get("action"),
                       url=(cfg.dashboards.get("map") if a.get("located") and cfg.dashboards.get("map")
                            else cfg.dashboard(a.get("category"))))
            if not cfg.enabled or cur.get("acked"):
                continue
            critical = cur["severity"] == "critical"
            quiet = cfg.quiet(cur.get("category"), local)
            if again and cur["level"] >= 1 and cur.get("notified"):
                out.append(self._msg(k, cur, cur["notified"], "again", cfg))
                cur["sent_at"] = ts
                continue
            if cur["level"] == 0:
                if quiet and not critical:
                    cur["held"] = True
                    continue
                first = cfg.first_line(local)
                if not first:
                    continue
                out.append(self._msg(k, cur, first, "new", cfg))
                cur.update(level=1, sent_at=ts, level_at=ts, held=False)
                cur["notified"] = sorted(set(cur["notified"]) | set(first))
                self._set_level(cur)
                continue
            if cur.get("snoozed_until"):
                if ts < cur["snoozed_until"]:
                    continue
                cur["snoozed_until"] = None                   # snooze over and still active: tell them again
                out.append(self._msg(k, cur, cur["notified"], "snooze_over", cfg))
                cur.update(sent_at=ts, level_at=ts)
                continue
            if quiet and not critical:
                continue
            nxt = cur["level"] - 1                             # index of the next person on the backup list
            if nxt < len(cfg.backup) and ts - (cur.get("level_at") or cur["sent_at"]) >= cfg.escalate_min * 60:
                person = cfg.backup[nxt]
                targets = sorted(set(cur["notified"]) | {person})
                out.append(self._msg(k, cur, targets, "escalated", cfg))
                cur.update(level=cur["level"] + 1, sent_at=ts, level_at=ts)
                cur["notified"] = targets
                self._set_level(cur)
                continue
            if cfg.repeat_min > 0 and ts - cur["sent_at"] >= cfg.repeat_min * 60:
                out.append(self._msg(k, cur, cur["notified"], "reminder", cfg))
                cur["sent_at"] = ts

        for k, cur in list(self.alerts.items()):
            if k in active or (keep and k.startswith(keep)):
                continue
            if cur.get("resolved_at") is None:
                cur["resolved_at"] = ts
                h = self._hist(cur["id"])
                if h is not None:
                    h["resolved_at"] = ts
            if not cur.get("resolved_sent") and ts - cur["resolved_at"] >= resolve_after:
                cur["resolved_sent"] = True
                if cfg.enabled and cfg.notify_resolved and cur.get("notified"):
                    out.append({"targets": list(cur["notified"]), "kind": "resolved", "id": cur["id"], "key": k,
                                "title": f"✅ Resolved: {cur['title']}", "message": cur["message"],
                                "critical": False, "action": None, "url": cur.get("url")})
            if cur.get("resolved_sent") and ts - cur["resolved_at"] > max(cfg.dedupe_min * 60, 3600):
                del self.alerts[k]
        cutoff = ts - HISTORY_DAYS * 86400
        self.history = [h for h in self.history if h["first"] >= cutoff]
        return out

    def _set_level(self, cur: dict[str, Any]) -> None:
        h = self._hist(cur["id"])
        if h is not None:
            h["level"] = max(h.get("level", 0), cur["level"])

    @staticmethod
    def _msg(key: str, cur: dict[str, Any], targets: list[str], kind: str, cfg: AlertSettings) -> dict[str, Any]:
        prefix = {"new": "", "reminder": "Reminder: ", "escalated": "⚠ Not acknowledged: ", "again": "Again: ",
                  "snooze_over": "Still active: "}[kind]
        return {"targets": list(targets), "kind": kind, "id": cur["id"], "key": key,
                "title": f"{prefix}{cur['title']}", "message": cur["message"],
                "critical": cur["severity"] == "critical", "url": cur.get("url"), "snooze": _duration(cfg.snooze_min),
                "action": cfg.action_title if cur.get("action") and cfg.action_title else None}

    # ------------------------------------------------------------- weekly summary
    def summary(self, ts: float, days: int = 7, names: dict[str, str] | None = None) -> dict[str, Any]:
        """Alerts of the last `days`: count, per category, noisiest sources, mean time to acknowledge."""
        names = names or {}
        since = ts - days * 86400
        recs = [h for h in self.history if h["first"] >= since]
        acked = [h["acked_at"] - h["first"] for h in recs if h.get("acked_at")]
        by_cat: dict[str, int] = {}
        by_source: dict[str, dict[str, Any]] = {}
        for h in recs:
            by_cat[h.get("category") or "other"] = by_cat.get(h.get("category") or "other", 0) + 1
            src = h["key"].split(":", 1)[0]
            label = names.get(src) or h["title"].split(" – ")[-1]
            b = by_source.setdefault(src, {"source": label, "alerts": 0, "flaps": 0})
            b["alerts"] += 1
            b["flaps"] += h.get("flaps", 0)
        noisy = sorted(by_source.values(), key=lambda b: (-(b["alerts"] + b["flaps"]), b["source"]))[:5]
        return {"days": days, "alerts": len(recs), "critical": sum(1 for h in recs if h.get("severity") == "critical"),
                "acknowledged": len(acked), "not_acknowledged": sum(1 for h in recs if not h.get("acked_at")),
                "escalated": sum(1 for h in recs if h.get("level", 0) >= 2),
                "snoozed": sum(1 for h in recs if h.get("snoozes")),
                "mtta_min": round(sum(acked) / len(acked) / 60, 1) if acked else None,
                "by_category": dict(sorted(by_cat.items(), key=lambda x: -x[1])), "noisiest": noisy}


def _duration(minutes: float) -> str:
    m = int(minutes)
    return f"{m // 60} h" if m % 60 == 0 else f"{m} min"


def summary_text(s: dict[str, Any]) -> str:
    if not s["alerts"]:
        return f"No alerts in the last {s['days']} days. 👍"
    lines = [f"{s['alerts']} alerts ({s['critical']} critical) in the last {s['days']} days."]
    if s["mtta_min"] is not None:
        lines.append(f"Mean time to acknowledge: {s['mtta_min']:g} min; {s['not_acknowledged']} never acknowledged"
                     + (f", {s['escalated']} escalated." if s["escalated"] else "."))
    else:
        lines.append("None were acknowledged.")
    lines.append("By category: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in s["by_category"].items()) + ".")
    if s["noisiest"]:
        lines.append("Noisiest: " + "; ".join(f"{n['source']} {n['alerts']}" + (f" (+{n['flaps']} repeats)" if n["flaps"]
                                                                               else "") for n in s["noisiest"]) + ".")
    return "\n".join(lines)


def notify_data(msg: dict[str, Any]) -> dict[str, Any]:
    """Service data for notify.<target> (Home Assistant Companion app: actions, tag, critical / alarm stream).
    Buttons (Android shows three): Acknowledge, Snooze, and the alert's own action, else *View on map* (device with
    a location) or *Open dashboard*. Tapping the notification itself only opens it – no link jumps."""
    if msg["kind"] == "clear":
        return {"message": "clear_notification", "data": {"tag": f"milesight_{msg['id']}"}}
    data: dict[str, Any] = {"tag": f"milesight_{msg['id']}", "group": "milesight_alerts"}
    url = msg.get("url")
    if msg["kind"] not in ("resolved", "acknowledged", "summary"):
        actions = [{"action": f"{ACTION_ACK}{msg['id']}", "title": "Acknowledge"}]
        if msg["kind"] != "snoozed":
            actions.append({"action": f"{ACTION_SNOOZE}{msg['id']}", "title": f"Snooze {msg.get('snooze') or '1 h'}"})
        if msg.get("action"):
            actions.append({"action": f"{ACTION_RUN}{msg['id']}", "title": msg["action"]})
        elif url:
            actions.append({"action": "URI", "title": "View on map" if url.endswith("/map") else "Open dashboard",
                            "uri": url})
        data["actions"] = actions
    if msg.get("critical"):
        data.update({"push": {"sound": {"name": "default", "critical": 1, "volume": 1.0},
                              "interruption-level": "critical"},
                     "ttl": 0, "priority": "high", "channel": "alarm_stream"})
    return {"title": msg["title"], "message": msg["message"], "data": data}


# ------------------------------------------------------------------ sources
SAFETY = {  # value key -> (what, severity)
    "leak_active": ("Water leak", "critical"),
    "smoke_active": ("Smoke detected", "critical"),
    "gas_active": ("Gas detected", "critical"),
    "alarm_fall": ("Fall detected", "critical"),
    "vape_active": ("Vaping detected", "warning"),
    "tamper_status": ("Tampered", "warning"),
}


def device_alerts(name: str, deveui: str, values: dict[str, Any], area: str | None = None) -> dict[str, dict]:
    """Alerts from one device's current values."""
    where = f"{name}{(' (' + area + ')') if area else ''}"
    out: dict[str, dict] = {}
    for key, (what, sev) in SAFETY.items():
        if values.get(key) is True:
            out[f"{deveui}:{key}"] = {"title": f"{what} – {name}", "message": f"{what} at {where}.",
                                      "severity": sev, "category": "safety"}
    if values.get("tank_sudden_drop") is True:
        amt = values.get("tank_drop_amount")
        out[f"{deveui}:tank_drop"] = {
            "title": f"Sudden drop – {name}", "severity": "critical", "category": "tank",
            "message": f"{where} lost {amt:g} L in a short time – possible theft or leak." if isinstance(amt, (int, float))
            else f"{where} dropped suddenly – possible theft or leak."}
    if values.get("tank_low") is True:
        fill, days = values.get("tank_fill"), values.get("tank_days_left")
        parts = ([f"{fill:g} % left"] if isinstance(fill, (int, float)) else []) + \
                ([f"about {days:g} days"] if isinstance(days, (int, float)) else [])
        out[f"{deveui}:tank_low"] = {"title": f"Tank low – {name}", "severity": "warning", "category": "tank",
                                     "message": f"{where} is low" + (f" ({', '.join(parts)})" if parts else "") + ".",
                                     "action": True}
    if values.get("pump_dry_run") is True:
        out[f"{deveui}:pump_dry"] = {
            "title": f"Pump running dry – {name}", "severity": "critical", "category": "pumps",
            "message": f"{where}: the current is well below normal – lost prime, empty well or broken shaft?"}
    if values.get("pump_overload") is True:
        out[f"{deveui}:pump_overload"] = {
            "title": f"Pump overload – {name}", "severity": "critical", "category": "pumps",
            "message": f"{where}: the current is well above normal – blockage, seized bearing or low voltage?"}
    if values.get("pump_short_cycling") is True:
        n = values.get("pump_starts_last_hour")
        out[f"{deveui}:pump_cycling"] = {
            "title": f"Pump short-cycling – {name}", "severity": "warning", "category": "pumps",
            "message": f"{where} started {n} times in the last hour – check the pressure switch / tank."}
    if values.get("pivot_stalled") is True:
        ang = values.get("pivot_angle")
        out[f"{deveui}:pivot_stalled"] = {
            "title": f"Pivot stalled – {name}", "severity": "critical", "category": "irrigation",
            "message": f"{where} has stopped moving" + (f" at {ang:.0f}°" if isinstance(ang, (int, float)) else "")
                       + " during a round."}
    out.update(_purpose_alerts(name, deveui, values, where))
    if values.get("online") is False:
        out[f"{deveui}:offline"] = {"title": f"Offline – {name}", "severity": "warning", "category": "devices",
                                    "message": f"{where} has not reported for a while."}
    if values.get("battery_low") is True:
        out[f"{deveui}:battery"] = {"title": f"Battery low – {name}", "severity": "warning", "category": "devices",
                                    "message": f"{where}: battery at {values.get('battery')} %."}
    if values.get("command_status") == "failed":
        out[f"{deveui}:command"] = {"title": f"Command failed – {name}", "severity": "warning",
                                    "category": "commands", "message": f"{where} did not confirm the last command."}
    return out


def _num(v: Any, fmt: str = "{:g}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else "–"


def _purpose_alerts(name: str, deveui: str, v: dict[str, Any], where: str) -> dict[str, dict]:
    """Alerts that come from a device's purpose (cold chain, openings, loads, bins, flood, buttons …)."""
    out: dict[str, dict] = {}
    what = v.get("purpose")
    cat = GROUP_CATEGORY.get(v.get("purpose_group") or "", "devices")
    sev = v.get("purpose_severity") or "warning"

    def add(key: str, title: str, message: str, category: str = cat, severity: str = "warning") -> None:
        out[f"{deveui}:{key}"] = {"title": f"{title} – {name}", "message": message, "category": category,
                                  "severity": severity}
    if v.get("temp_alarm") is True:
        add("temp_range", "Temperature out of range",
            f"{where}{' (' + what + ')' if what else ''}: {_num(v.get('temperature_now'))} °C – "
            f"out of range for {_num(v.get('temp_out_today'))} min today.", severity=sev)
    if v.get("temp_hot_spot") is True:
        add("hot_spot", "Hot spot", f"{where}: temperature up {_num(v.get('temp_rise_24h'))} °C in 24 h – "
            f"check for spoilage / heating.", "tank")
    if what and v.get("door_left_open") is True:
        add("left_open", f"{what} left open", f"{where} has been open for "
            f"{_num((v.get('door_current_s') or 0) / 60, '{:.0f}')} min.")
    if v.get("after_hours_activity") is True:
        add("after_hours", "After-hours activity", f"{where}{' (' + what + ')' if what else ''}: activity outside "
            f"working hours.", "security", "critical" if sev == "critical" or cat == "security" else "warning")
    for k, val in v.items():
        if val is not True or not k.startswith("load"):
            continue
        prefix, _, flag = k.partition("_")
        prefix += "_"
        label = v.get(f"{prefix}label") or "Load"
        lcat = GROUP_CATEGORY.get(v.get(f"{prefix}group") or "", cat)
        if flag == "ran_too_long":
            add(f"{prefix}long", f"{label} running too long",
                f"{where}: {label.lower()} has run for {_num(v.get(f'{prefix}running_for_h'), '{:.1f}')} h without "
                f"stopping – failing compressor, low gas, door open or a leak?", lcat,
                "critical" if lcat == "cold_chain" else "warning")
        elif flag == "not_running":
            add(f"{prefix}idle", f"{label} not running", f"{where}: {label.lower()} has not run for hours – "
                f"tripped, broken or switched off?", lcat, "critical" if lcat == "cold_chain" else "warning")
        elif flag == "after_hours":
            add(f"{prefix}after", f"{label} on after hours", f"{where}: {label.lower()} is running outside working "
                f"hours.", "energy")
        elif flag == "service_due":
            add(f"{prefix}service", f"{label} service due", f"{where}: service interval reached – press "
                f"'{label} serviced' afterwards.", "pumps")
    if v.get("mains_outage") is True:
        add("outage", "Power outage", f"{where}: no current on any phase.", "energy", "critical")
    if v.get("phase_imbalance_high") is True:
        add("imbalance", "Phase imbalance", f"{where}: phases differ by {_num(v.get('phase_imbalance'))} %.",
            "energy")
    if v.get("bin_full") is True:
        add("bin_full", "Bin full", f"{where} is {_num(v.get('bin_fill'))} % full – time to collect.", "facilities")
    if v.get("water_rising") is True:
        add("flood", "Water rising fast", f"{where}: level {_num(v.get('water_level'))} cm, rising "
            f"{_num(v.get('water_rise_rate'))} cm/h.", "safety", "critical")
    if v.get("clean_due") is True:
        add("clean", "Cleaning due", f"{where}: {_num(v.get('visits_since_clean'))} visits since the last clean.",
            "facilities")
    if v.get("panic_active") is True:
        add("panic", "PANIC button", f"Panic / SOS button pressed at {where}.", "security", "critical")
    if v.get("service_active") is True:
        add("service", "Service requested", f"Service requested at {where}.", "facilities")
    return out
