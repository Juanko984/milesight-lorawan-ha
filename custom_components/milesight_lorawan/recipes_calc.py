"""Recipe engine maths: plain-language automations evaluated against role sensors.

Pure Python (no Home Assistant imports). The engine turns a list of recipe instances + a snapshot of the
site (role sensors, the device fleet, the costs sensor, the site centre) into (a) a list of *fires* the HA
layer should act on this tick and (b) a snapshot for the Recipes card. All temporal state (how long a
condition has held, recent edges, last-fired debounce) lives in plain dicts so it can be stored as JSON.

Conditions are role-aware: "any tank" resolves to the live set of tank role sensors every tick, so a device
added next week is covered with no change. The same engine already pattern (per-minute tick, JSON state) as
alerts / building / costs.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Callable

from .analytics import Calendar

CATEGORIES = ("water", "pumps", "cold_chain", "energy", "devices", "farm", "security")

OPS: dict[str, Callable[[float, float], bool]] = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _n(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


# ---------------------------------------------------------------------------
# The starter catalog — each entry is a template; an enabled recipe is an instance of one.
# cond.type ∈ threshold | boolean | offline | edge_count | geofence | costs_projection
#            | battery_sweep | night_flow
# ---------------------------------------------------------------------------
CATALOG: dict[str, dict[str, Any]] = {
    "low_tank": {
        "category": "water", "icon": "💧", "title": "Low tank → notify",
        "cond": {"type": "threshold", "role": "tank", "attr": "fill", "op": "<", "not_silo": True},
        "params": {"threshold": 20, "duration_min": 120},
        "actions": [{"type": "notify", "target": "on_call"}, {"type": "raise_alert"}],
    },
    "pump_dry_run": {
        "category": "pumps", "icon": "⚙️", "title": "Pump dry-run → switch off",
        "cond": {"type": "edge_count", "role": "pump", "attr": "dry_run"},
        "params": {"count": 3, "window_min": 60},
        "actions": [{"type": "press", "entity": None}, {"type": "notify", "target": "on_call"}],
    },
    "fridge_over": {
        "category": "cold_chain", "icon": "❄️", "title": "Fridge over limit → notify",
        "cond": {"type": "threshold", "role": "cold_chain", "attr": "temperature", "op": ">", "limit_attr": "high"},
        "params": {"duration_min": 15},
        "actions": [{"type": "notify", "target": "on_call"}, {"type": "raise_alert"}],
    },
    "device_offline": {
        "category": "devices", "icon": "📡", "title": "Device silent → notify",
        "cond": {"type": "offline"},
        "params": {"duration_min": 60},
        "actions": [{"type": "notify", "target": "maintenance"}],
    },
    "silo_days": {
        "category": "farm", "icon": "🌾", "title": "Silo running out → notify",
        "cond": {"type": "threshold", "role": "tank", "attr": "days_left", "op": "<", "is_silo": True},
        "params": {"threshold": 3, "duration_min": 0},
        "actions": [{"type": "notify", "target": "farm_manager"}],
    },
    "spend_spike": {
        "category": "energy", "icon": "💸", "title": "Spend spike → notify",
        "cond": {"type": "costs_projection"},
        "params": {"factor": 1.25},
        "actions": [{"type": "notify", "target": "on_call"}],
    },
    "overnight_flow": {
        "category": "water", "icon": "🚰", "title": "Overnight flow → notify",
        "cond": {"type": "night_flow", "role": "meter", "attr": "water_today"},
        "params": {"from_hour": 0, "to_hour": 5, "litres": 50},
        "actions": [{"type": "notify", "target": "on_call"}, {"type": "raise_alert"}],
    },
    "mains_outage": {
        "category": "energy", "icon": "🔌", "title": "Mains outage → notify",
        "cond": {"type": "boolean", "role": "mains", "state_on": True},
        "params": {"duration_min": 0},
        "actions": [{"type": "notify", "target": "on_call"}, {"type": "log"}],
    },
    "low_battery_sweep": {
        "category": "devices", "icon": "🔋", "title": "Weekly low-battery sweep",
        "cond": {"type": "battery_sweep"},
        "params": {"threshold": 15, "day": "mon", "hour": 8},
        "actions": [{"type": "notify", "target": "maintenance"}],
    },
    "empty_trough": {
        "category": "farm", "icon": "🐄", "title": "Empty trough → notify",
        "cond": {"type": "boolean", "role": "water_trough", "attr": "empty"},
        "params": {"duration_min": 30},
        "actions": [{"type": "notify", "target": "on_call"}],
    },
    "left_farm": {
        "category": "security", "icon": "🚜", "title": "Left the farm → notify",
        "cond": {"type": "geofence", "role": "gps"},
        "params": {"radius_m": 500},
        "actions": [{"type": "notify", "target": "on_call"}, {"type": "raise_alert"}],
    },
}

TARGET_LABEL = {"on_call": "on-call", "maintenance": "maintenance", "farm_manager": "farm manager",
                "primary": "primary"}
SCOPE_ROLE_LABEL = {"tank": "tank", "cold_chain": "fridge / freezer", "pump": "pump", "mains": "mains board",
                    "water_trough": "trough", "meter": "water meter", "gps": "GPS tracker"}


def default_recipe(key: str) -> dict[str, Any]:
    """A fresh enabled instance of a catalog recipe, with its default params / actions / scope."""
    c = CATALOG[key]
    return {"id": key, "catalog": key, "enabled": True, "params": dict(c["params"]),
            "scope": {"mode": "any", "area": None, "device": None},
            "actions": [dict(a) for a in c["actions"]], "guards": {"working_hours": False, "debounce_min": 30}}


def sentence(inst: dict[str, Any]) -> str:
    """Plain-language description of a recipe instance for the gallery."""
    c = CATALOG.get(inst.get("catalog", ""), {})
    p, sc = inst.get("params", {}), inst.get("scope", {})
    ct = c.get("cond", {})
    role = ct.get("role")
    if sc.get("mode") == "device" and sc.get("device"):
        who = sc["device"]
    elif sc.get("mode") == "area" and sc.get("area"):
        who = f"any {SCOPE_ROLE_LABEL.get(role, role or 'device')} in {sc['area']}"
    elif ct.get("is_silo"):
        who = "any feed silo"
    elif role:
        who = f"any {SCOPE_ROLE_LABEL.get(role, role)}"
    else:
        who = "any device"
    acts = ", ".join(_action_label(a) for a in inst.get("actions", [])) or "notify"
    t = ct.get("type")
    if t == "threshold" and ct.get("limit_attr"):
        body = f"{who} is above its limit for {_mins(p.get('duration_min'))}"
    elif t == "threshold" and ct.get("attr") == "days_left":
        body = f"{who} has under {p.get('threshold')} days left"
    elif t == "threshold":
        unit = "%" if ct.get("attr") in ("fill",) else ""
        body = f"{who} drops below {p.get('threshold')}{unit}" + (
            f" for {_mins(p['duration_min'])}" if p.get("duration_min") else "")
    elif t == "edge_count":
        body = f"{who} dry-runs {p.get('count')}× within {_mins(p.get('window_min'))}"
    elif t == "offline":
        body = f"{who} sends nothing for {_mins(p.get('duration_min'))}"
    elif t == "boolean":
        state = "has no power" if ct.get("role") == "mains" else "reads empty"
        body = f"{who} {state}" + (f" for {_mins(p['duration_min'])}" if p.get("duration_min") else "")
    elif t == "costs_projection":
        body = f"today's spend is on track to beat your usual day by {round((p.get('factor', 1.25) - 1) * 100)}%"
    elif t == "night_flow":
        body = f"a water meter keeps flowing overnight (> {p.get('litres')} L, {p.get('from_hour')}–{p.get('to_hour')}h)"
    elif t == "battery_sweep":
        body = f"any device battery is under {p.get('threshold')}% (weekly digest)"
    elif t == "geofence":
        body = f"{who} moves more than {p.get('radius_m')} m from the site"
    else:
        body = who
    return f"If {body} → {acts}"


def _action_label(a: dict[str, Any]) -> str:
    t = a.get("type")
    if t == "notify":
        return f"notify {TARGET_LABEL.get(a.get('target'), a.get('target') or 'on-call')}"
    return {"raise_alert": "raise an alert", "press": "switch a device", "log": "log"}.get(t, t or "")


def _mins(m: Any) -> str:
    m = _n(m) or 0
    if m and m % 60 == 0:
        h = int(m // 60)
        return f"{h} h" if h != 1 else "1 h"
    return f"{int(m)} min"


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------
class RecipeEngine:
    def __init__(self, cal: Calendar, state: dict | None = None) -> None:
        self.cal = cal
        self.s: dict[str, Any] = state or {"rt": {}}   # id -> {targets:{key:{since,edges,fired}}, fired_day, fired_count, last_fire}

    def _rt(self, rid: str) -> dict[str, Any]:
        return self.s["rt"].setdefault(rid, {"targets": {}, "fired_day": None, "fired_count": 0, "last_fire": None})

    # -- target resolution -------------------------------------------------
    def _targets(self, inst: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
        c = CATALOG.get(inst.get("catalog", ""), {})
        ct = c.get("cond", {})
        role = ct.get("role")
        if ct.get("type") in ("offline", "battery_sweep"):
            ents = ctx.get("devices", [])
        else:
            ents = list(ctx.get("roles", {}).get(role, []))
        # role sub-filters (silos vs tanks)
        if ct.get("is_silo"):
            ents = [e for e in ents if e.get("attrs", {}).get("is_silo")]
        elif ct.get("not_silo"):
            ents = [e for e in ents if not e.get("attrs", {}).get("is_silo")]
        sc = inst.get("scope", {})
        if sc.get("mode") == "device" and sc.get("device"):
            ents = [e for e in ents if e.get("id") == sc["device"] or e.get("name") == sc["device"]]
        elif sc.get("mode") == "area" and sc.get("area"):
            ents = [e for e in ents if str(e.get("area") or "").lower() == str(sc["area"]).lower()]
        return ents

    # -- per-condition "met?" for one target ------------------------------
    @staticmethod
    def _met(ct: dict[str, Any], params: dict[str, Any], e: dict[str, Any], ts: float) -> tuple[bool, str]:
        t = ct["type"]
        if t == "threshold":
            v = _n(e.get("attrs", {}).get(ct["attr"]))
            if v is None:
                v = _n(e.get("num"))
            if v is None:
                return False, ""
            if ct.get("limit_attr"):
                lim = _n(e.get("attrs", {}).get(ct["limit_attr"]))
                if lim is None:
                    return False, ""
                return (v > lim), f"{v:g} over {lim:g}"
            op, val = OPS[ct["op"]], float(params["threshold"])
            unit = "%" if ct.get("attr") == "fill" else (" d" if ct.get("attr") == "days_left" else "")
            return op(v, val), f"{v:g}{unit}"
        if t == "boolean":
            if ct.get("state_on"):
                return str(e.get("state")).lower() == "on", "no power"
            return bool(e.get("attrs", {}).get(ct["attr"])), "empty"
        if t == "offline":
            last = _n(e.get("last_seen_ts"))
            if e.get("online") is False:
                return True, "offline"
            if last is not None and (ts - last) >= float(params["duration_min"]) * 60:
                return True, "silent"
            return False, ""
        if t == "geofence":
            lat, lon = _n(e.get("lat")), _n(e.get("lon"))
            c_lat, c_lon = _n(e.get("site_lat")), _n(e.get("site_lon"))
            if None in (lat, lon, c_lat, c_lon):
                return False, ""
            d = _haversine_m(c_lat, c_lon, lat, lon)
            return d > float(params["radius_m"]), f"{d:.0f} m out"
        return False, ""

    # -- main tick ---------------------------------------------------------
    def evaluate(self, recipes: list[dict[str, Any]], ctx: dict[str, Any], ts: float,
                 local: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        fires: list[dict[str, Any]] = []
        snaps: list[dict[str, Any]] = []
        day = self.cal.key("day", ts)
        for inst in recipes:
            rid = inst["id"]
            c = CATALOG.get(inst.get("catalog", ""), {})
            if not c:
                continue
            rt = self._rt(rid)
            if rt["fired_day"] != day:
                rt["fired_day"], rt["fired_count"] = day, 0
            ct, params = c["cond"], inst.get("params", {})
            targets = self._targets(inst, ctx)
            firing_now, last_detail = 0, None
            if inst.get("enabled"):
                new_fires = self._tick_recipe(inst, c, ct, params, targets, ctx, ts, local, rt)
                for f in new_fires:
                    rt["fired_count"] += 1
                    rt["last_fire"] = ts
                    fires.append(f)
                firing_now = sum(1 for k in rt["targets"].values() if k.get("since") is not None)
            snaps.append({"id": rid, "catalog": inst["catalog"], "enabled": bool(inst.get("enabled")),
                          "category": c["category"], "icon": c["icon"], "title": c["title"],
                          "sentence": sentence(inst), "cond": ct,
                          "params": params, "scope": inst.get("scope", {}), "actions": inst.get("actions", []),
                          "guards": inst.get("guards", {}), "covers": len(targets),
                          "fired_today": rt["fired_count"], "firing_now": firing_now,
                          "last_fire": rt.get("last_fire")})
        return fires, snaps

    def _tick_recipe(self, inst, c, ct, params, targets, ctx, ts, local, rt) -> list[dict[str, Any]]:
        t = ct["type"]
        if t in ("threshold", "boolean", "offline", "geofence"):
            return self._tick_sustained(inst, c, ct, params, targets, ts, rt)
        if t == "edge_count":
            return self._tick_edges(inst, c, ct, params, targets, ts, rt)
        if t == "costs_projection":
            return self._tick_costs(inst, c, params, ctx, ts, local, rt)
        if t == "battery_sweep":
            return self._tick_sweep(inst, c, params, targets, ts, local, rt)
        if t == "night_flow":
            return self._tick_night(inst, c, params, targets, ts, local, rt)
        return []

    def _debounced(self, inst, rt, ts) -> bool:
        deb = float(inst.get("guards", {}).get("debounce_min", 30)) * 60
        return rt.get("last_fire") is not None and (ts - rt["last_fire"]) < deb

    @staticmethod
    def _working_hours(inst, local) -> bool:
        if not inst.get("guards", {}).get("working_hours"):
            return True
        return 6 <= local.hour < 18 and local.weekday() < 6

    def _tick_sustained(self, inst, c, ct, params, targets, ts, rt) -> list[dict[str, Any]]:
        fires: list[dict[str, Any]] = []
        # offline / geofence encode their own timing inside _met, so they don't also wait a sustain window
        dur = 0.0 if ct["type"] in ("offline", "geofence") else float(params.get("duration_min", 0) or 0) * 60
        seen: set[str] = set()
        for e in targets:
            key = e.get("id") or e.get("name")
            seen.add(key)
            met, detail = self._met(ct, params, e, ts)
            st = rt["targets"].setdefault(key, {"since": None, "fired": None})
            if not met:
                st["since"] = None
                st["fired"] = None
                continue
            if st["since"] is None:
                st["since"] = ts
            if (ts - st["since"]) >= dur and st.get("fired") is None and not self._debounced(inst, rt, ts):
                st["fired"] = ts
                fires.append(self._fire(inst, c, e, detail, ts))
        for k in list(rt["targets"]):
            if k not in seen:
                rt["targets"].pop(k, None)
        return fires

    def _tick_edges(self, inst, c, ct, params, targets, ts, rt) -> list[dict[str, Any]]:
        fires, window = [], float(params.get("window_min", 60)) * 60
        count = int(params.get("count", 3))
        seen: set[str] = set()
        for e in targets:
            key = e.get("id") or e.get("name")
            seen.add(key)
            on = bool(e.get("attrs", {}).get(ct["attr"]))
            st = rt["targets"].setdefault(key, {"edges": [], "prev": False, "fired": None})
            if on and not st.get("prev"):
                st["edges"].append(ts)
            st["prev"] = on
            st["edges"] = [x for x in st["edges"] if ts - x <= window]
            if len(st["edges"]) >= count and not self._debounced(inst, rt, ts):
                st["edges"] = []
                fires.append(self._fire(inst, c, e, f"{count}× in {int(window/60)} min", ts))
        for k in list(rt["targets"]):
            if k not in seen:
                rt["targets"].pop(k, None)
        return fires

    def _tick_costs(self, inst, c, params, ctx, ts, local, rt) -> list[dict[str, Any]]:
        costs = ctx.get("costs") or {}
        proj, last_month, dim = _n(costs.get("projected")), _n(costs.get("last_month")), _n(costs.get("days_in_month"))
        if proj is None or not last_month or not dim:
            return []
        usual = last_month / dim
        today = _n(costs.get("today")) or 0
        if today < usual * float(params.get("factor", 1.25)):
            return []
        if rt.get("fired_count", 0) >= 1:          # once per day
            return []
        cur = costs.get("currency", "R")
        return [self._fire(inst, c, {"name": "Site spend"},
                           f"{cur} {today:,.0f} today vs {cur} {usual:,.0f} usual", ts)]

    def _tick_sweep(self, inst, c, params, targets, ts, local, rt) -> list[dict[str, Any]]:
        day = str(params.get("day", "mon"))[:3].lower()
        if DAYS[local.weekday()] != day or local.hour != int(params.get("hour", 8)) or rt.get("fired_count", 0) >= 1:
            return []
        thr = float(params.get("threshold", 15))
        low = [e for e in targets if (_n(e.get("battery")) is not None and _n(e["battery"]) < thr)]
        if not low:
            return []
        names = ", ".join(e.get("name", "?") for e in low[:6]) + (" …" if len(low) > 6 else "")
        return [self._fire(inst, c, {"name": f"{len(low)} device(s)"}, f"under {thr:g}%: {names}", ts)]

    def _tick_night(self, inst, c, params, targets, ts, local, rt) -> list[dict[str, Any]]:
        f_h, t_h = int(params.get("from_hour", 0)), int(params.get("to_hour", 5))
        in_window = f_h <= local.hour < t_h
        base = rt.setdefault("night", {"start": {}, "day": None})
        if in_window and base["day"] != self.cal.key("day", ts):   # window opened: snapshot each meter
            base["day"] = self.cal.key("day", ts)
            base["start"] = {e.get("id") or e.get("name"): _n(e.get("attrs", {}).get("water_today")) or _n(e.get("num")) or 0
                             for e in targets}
        if local.hour != t_h or rt.get("fired_count", 0) >= 1:     # evaluate once, at window close
            return []
        fires, thr = [], float(params.get("litres", 50)) / 1000.0   # kL
        for e in targets:
            key = e.get("id") or e.get("name")
            now = _n(e.get("attrs", {}).get("water_today")) or _n(e.get("num")) or 0
            drawn = now - base["start"].get(key, now)
            if drawn > thr:
                fires.append(self._fire(inst, c, e, f"{drawn*1000:.0f} L overnight", ts))
        return fires

    def _fire(self, inst, c, e, detail, ts) -> dict[str, Any]:
        name = e.get("name") or e.get("id") or "site"
        return {"recipe_id": inst["id"], "catalog": inst["catalog"], "icon": c["icon"],
                "title": c["title"], "target_name": name, "detail": detail,
                "message": f"{name}: {detail}" if detail else name,
                "actions": inst.get("actions", []), "ts": ts}
