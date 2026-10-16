"""Alert escalation: notify the primary people, escalate to the backup when nobody acknowledges, repeat,
hold non-critical alerts during quiet hours, suppress duplicates of flapping alerts and send 'resolved'.
Pure Python (unit-tested); hub.py feeds it the active alerts and sends what it returns.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CATEGORIES = ("safety", "tank", "pumps", "irrigation", "building", "devices", "gateways", "commands")
DEFAULT_CATEGORIES = ["safety", "tank", "pumps", "irrigation", "devices", "gateways"]
_CATEGORIES_V1 = ("safety", "tank", "building", "devices", "gateways", "commands")   # before 0.24


def effective_categories(opts: dict[str, Any]) -> tuple[str, ...]:
    """The chosen alert categories; categories added after the choice was saved start switched on."""
    chosen = opts.get("alert_categories")
    if not chosen:
        return tuple(DEFAULT_CATEGORIES)
    known = opts.get("alert_categories_known") or _CATEGORIES_V1
    return tuple(c for c in CATEGORIES if c in chosen or (c in DEFAULT_CATEGORIES and c not in known))
ACTION_ACK = "MSL_ACK_"
ACTION_RUN = "MSL_RUN_"


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

    @property
    def enabled(self) -> bool:
        return bool(self.primary)


def in_quiet(hour_min: float, start: int | None, end: int | None) -> bool:
    """hour_min: local time as fractional hours."""
    if start is None or end is None or start == end:
        return False
    return start <= hour_min < end if start < end else (hour_min >= start or hour_min < end)


def alert_id(key: str, first: float) -> str:
    return hashlib.sha1(f"{key}|{int(first)}".encode()).hexdigest()[:10]


class AlertEngine:
    """state per alert key: id, title, message, severity, category, first, sent_at, level (0 held, 1 primary,
    2 backup), acked (by / at), resolved_at, notified (targets)."""

    def __init__(self, state: dict | None = None) -> None:
        self.alerts: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (state or {}).get("alerts", {}).items()}

    def to_dict(self) -> dict[str, Any]:
        return {"alerts": self.alerts}

    # ------------------------------------------------------------- queries
    def open_alerts(self) -> list[dict[str, Any]]:
        return [a | {"key": k} for k, a in self.alerts.items() if a.get("resolved_at") is None]

    def unacknowledged(self) -> list[dict[str, Any]]:
        return [a for a in self.open_alerts() if not a.get("acked")]

    def by_id(self, aid: str) -> tuple[str, dict[str, Any]] | None:
        return next(((k, a) for k, a in self.alerts.items() if a["id"] == aid), None)

    # ------------------------------------------------------------- actions
    def acknowledge(self, aid: str | None, ts: float, by: str | None = None) -> list[dict[str, Any]]:
        """Acknowledge one alert (or all open ones). Returns the 'acknowledged' messages for the phones."""
        out = []
        for k, a in self.alerts.items():
            if a.get("resolved_at") is not None or a.get("acked") or (aid is not None and a["id"] != aid):
                continue
            a["acked"] = {"by": by, "at": ts}
            if a.get("notified"):
                # same tag: replaces the alert on every phone (and removes its buttons)
                out.append({"targets": list(a["notified"]), "kind": "acknowledged", "id": a["id"], "key": k,
                            "title": f"✔ {a['title']}", "critical": False, "action": None,
                            "message": f"Acknowledged{(' by ' + by) if by else ''}: {a['message']}"})
        return out

    # ----------------------------------------------------------- main loop
    def update(self, active: dict[str, dict[str, Any]], ts: float, local: datetime,
               cfg: AlertSettings, keep: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        """active: {key: {title, message, severity ('critical' | 'warning'), category, action?}}.
        keep: key prefixes whose source is not loaded yet (their alerts are neither resolved nor dropped).
        Returns notifications [{targets, kind (new | reminder | escalated | again | resolved), id, key, title,
        message, critical, action}]."""
        out: list[dict[str, Any]] = []
        quiet = in_quiet(local.hour + local.minute / 60, cfg.quiet_start, cfg.quiet_end)
        active = {k: a for k, a in active.items() if a.get("category") in cfg.categories}
        resolve_after = min(cfg.dedupe_min, 5) * 60        # 'resolved' only once it stays resolved this long

        for k, a in active.items():
            cur = self.alerts.get(k)
            again = False
            if cur is not None and cur.get("resolved_at") is not None:
                if ts - cur["resolved_at"] <= cfg.dedupe_min * 60:
                    cur["flaps"] = cur.get("flaps", 0) + 1      # flapping: the same alert continues …
                    again = bool(cur.get("resolved_sent"))      # … people were told it was resolved: tell them again
                    cur.update(resolved_at=None, resolved_sent=False)
                    if again:
                        cur["acked"] = None
                else:
                    cur = None
            if cur is None:
                cur = {"id": alert_id(k, ts), "first": ts, "level": 0, "sent_at": None, "level_at": None,
                       "acked": None, "resolved_at": None, "notified": []}
                self.alerts[k] = cur
            cur.update(title=a["title"], message=a["message"], severity=a.get("severity", "warning"),
                       category=a.get("category"), action=a.get("action"))
            if not cfg.enabled or cur.get("acked"):
                continue
            critical = cur["severity"] == "critical"
            if again and cur["level"] >= 1 and cur.get("notified"):
                out.append(self._msg(k, cur, cur["notified"], "again", cfg))
                cur["sent_at"] = ts
                continue
            if cur["level"] == 0:
                if quiet and not critical:
                    cur["held"] = True
                    continue
                out.append(self._msg(k, cur, cfg.primary, "new", cfg))
                cur.update(level=1, sent_at=ts, level_at=ts, held=False)
                cur["notified"] = sorted(set(cur["notified"]) | set(cfg.primary))
                continue
            if quiet and not critical:
                continue
            if cur["level"] == 1 and cfg.backup and ts - (cur.get("level_at") or cur["sent_at"]) >= cfg.escalate_min * 60:
                targets = sorted(set(cfg.backup) | set(cfg.primary))
                out.append(self._msg(k, cur, targets, "escalated", cfg))
                cur.update(level=2, sent_at=ts, level_at=ts)
                cur["notified"] = sorted(set(cur["notified"]) | set(targets))
                continue
            if cfg.repeat_min > 0 and ts - cur["sent_at"] >= cfg.repeat_min * 60:
                targets = cfg.primary if cur["level"] == 1 else sorted(set(cfg.backup) | set(cfg.primary))
                out.append(self._msg(k, cur, targets, "reminder", cfg))
                cur["sent_at"] = ts

        for k, cur in list(self.alerts.items()):
            if k in active or (keep and k.startswith(keep)):
                continue
            if cur.get("resolved_at") is None:
                cur["resolved_at"] = ts
            if not cur.get("resolved_sent") and ts - cur["resolved_at"] >= resolve_after:
                cur["resolved_sent"] = True
                if cfg.enabled and cfg.notify_resolved and cur.get("notified"):
                    out.append({"targets": list(cur["notified"]), "kind": "resolved", "id": cur["id"], "key": k,
                                "title": f"✅ Resolved: {cur['title']}", "message": cur["message"],
                                "critical": False, "action": None})
            if cur.get("resolved_sent") and ts - cur["resolved_at"] > max(cfg.dedupe_min * 60, 3600):
                del self.alerts[k]
        return out

    @staticmethod
    def _msg(key: str, cur: dict[str, Any], targets: list[str], kind: str, cfg: AlertSettings) -> dict[str, Any]:
        prefix = {"new": "", "reminder": "Reminder: ", "escalated": "⚠ Not acknowledged: ", "again": "Again: "}[kind]
        return {"targets": list(targets), "kind": kind, "id": cur["id"], "key": key,
                "title": f"{prefix}{cur['title']}", "message": cur["message"],
                "critical": cur["severity"] == "critical",
                "action": cfg.action_title if cur.get("action") and cfg.action_title else None}


def notify_data(msg: dict[str, Any]) -> dict[str, Any]:
    """Service data for notify.<target> (Home Assistant Companion app: actions, tag, critical / alarm stream)."""
    if msg["kind"] == "clear":
        return {"message": "clear_notification", "data": {"tag": f"milesight_{msg['id']}"}}
    data: dict[str, Any] = {"tag": f"milesight_{msg['id']}", "group": "milesight_alerts"}
    if msg["kind"] not in ("resolved", "acknowledged"):
        actions = [{"action": f"{ACTION_ACK}{msg['id']}", "title": "Acknowledge"}]
        if msg.get("action"):
            actions.append({"action": f"{ACTION_RUN}{msg['id']}", "title": msg["action"]})
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
