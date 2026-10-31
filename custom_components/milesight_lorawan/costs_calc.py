"""Running-costs maths: turn metered energy / water / fuel / feed into money, per day and per month.

Pure Python (no Home Assistant imports). State is plain JSON-serialisable dicts so it can be stored.
Quantities are accumulated in each resource's base unit (kWh / kL / L / t); money is only ever worked
out at report time, so a tariff change applies to the whole period, never to what was already banked.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from typing import Any

from .analytics import Calendar

RESOURCES = ("electricity", "water", "diesel", "feed")

# base unit each meter reports in, and the tariff that prices it
RESOURCE_UNIT = {"electricity": "kWh", "water": "kL", "diesel": "L", "feed": "t"}


def r_per_unit(resource: str, tariff: float | None) -> float | None:
    """Currency per base unit. Electricity is entered in cents/kWh, everything else in currency/unit."""
    if tariff in (None, "", 0) or float(tariff) <= 0:
        return None
    return float(tariff) / 100.0 if resource == "electricity" else float(tariff)


class CostTracker:
    """Accumulates consumed quantity per meter, per day and per month, from readings fed in each tick.

    A meter is 'accum' (a total-increasing counter — kWh / kL meters, daily-reset energy counters) or
    'drain' (a tank / silo level that falls as it is used — litres of fuel, tonnes of feed). Refills and
    counter resets are ignored, so only real consumption is banked.
    """

    def __init__(self, cal: Calendar, state: dict | None = None) -> None:
        self.cal = cal
        self.s: dict[str, Any] = state or {
            "meters": {},                        # id -> {"last": float, "res": str, "kind": str}
            "day": {"key": None, "m": {}},       # today: {id: qty}
            "pday": {"key": None, "res": {}},    # yesterday, aggregated by resource
            "month": {"key": None, "m": {}},     # this month: {id: qty}
            "pmonth": {"key": None, "res": {}},  # last month, aggregated by resource
        }

    # -- period rollover ---------------------------------------------------
    def _by_res(self, m: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for mid, qty in m.items():
            res = self.s["meters"].get(mid, {}).get("res")
            if res:
                out[res] = out.get(res, 0.0) + qty
        return out

    def roll(self, ts: float) -> None:
        """Call once per tick before observing: archive and reset the day / month buckets on a boundary."""
        dk, mk = self.cal.key("day", ts), self.cal.key("month", ts)
        day = self.s["day"]
        if day.get("key") != dk:
            if day.get("key") is not None:
                self.s["pday"] = {"key": day["key"], "res": self._by_res(day["m"])}
            self.s["day"] = {"key": dk, "m": {}}
        month = self.s["month"]
        if month.get("key") != mk:
            if month.get("key") is not None:
                self.s["pmonth"] = {"key": month["key"], "res": self._by_res(month["m"])}
            self.s["month"] = {"key": mk, "m": {}}

    # -- ingest ------------------------------------------------------------
    def observe(self, mid: str, resource: str, kind: str, reading: float | None) -> None:
        if reading is None or not isinstance(reading, (int, float)) or isinstance(reading, bool):
            return
        reading = float(reading)
        meters = self.s["meters"]
        prev = meters.get(mid)
        meters[mid] = {"last": reading, "res": resource, "kind": kind}
        if prev is None or prev.get("last") is None:
            return                                           # first reading just sets the baseline
        last = float(prev["last"])
        if kind == "drain":
            delta = last - reading if reading < last else 0.0   # level fell = used; a refill banks nothing
        else:  # accum
            delta = reading - last if reading >= last else reading   # counter reset → treat new value as the rise
        if delta <= 0:
            return
        self.s["day"]["m"][mid] = self.s["day"]["m"].get(mid, 0.0) + delta
        self.s["month"]["m"][mid] = self.s["month"]["m"].get(mid, 0.0) + delta

    # -- report ------------------------------------------------------------
    def report(self, tariffs: dict[str, float | None], meta: dict[str, dict[str, Any]],
               ts: float, currency: str = "R", rate_per_h: float | None = None) -> dict[str, Any]:
        """tariffs: {resource: price}. meta: {id: {label, icon, res, rate}} for the leaderboard rows.
        Returns everything the Running-costs sensor exposes."""
        rpu = {res: r_per_unit(res, tariffs.get(res)) for res in RESOURCES}
        day_m, month_m = self.s["day"]["m"], self.s["month"]["m"]

        def money(qty: float, res: str) -> float:
            r = rpu.get(res)
            return round(qty * r, 2) if r else 0.0

        rows: list[dict[str, Any]] = []
        today_by_res: dict[str, float] = {r: 0.0 for r in RESOURCES}
        for mid, info in meta.items():
            res = info["res"]
            if rpu.get(res) is None:
                continue                                     # tariff blank → resource hidden
            qd, qm = day_m.get(mid, 0.0), month_m.get(mid, 0.0)
            md, mm = money(qd, res), money(qm, res)
            today_by_res[res] += md
            rows.append({"id": mid, "label": info.get("label") or mid, "icon": info.get("icon"),
                         "resource": res, "today": md, "month": mm,
                         "qty_today": round(qd, 3), "unit": RESOURCE_UNIT[res]})
        rows.sort(key=lambda r: (r["today"], r["month"]), reverse=True)

        today = round(sum(r["today"] for r in rows), 2)
        month = round(sum(r["month"] for r in rows), 2)
        yesterday = round(sum(money(q, res) for res, q in self.s["pday"].get("res", {}).items()), 2)
        last_month = round(sum(money(q, res) for res, q in self.s["pmonth"].get("res", {}).items()), 2)

        dt = datetime.fromtimestamp(ts, self.cal.tz)
        dim = monthrange(dt.year, dt.month)[1]
        dom = dt.day
        projected = round(month / dom * dim, 2) if dom else month

        today_by_res = {r: round(v, 2) for r, v in today_by_res.items() if rpu.get(r) is not None}
        return {
            "currency": currency,
            "today": today, "month": month, "projected": projected,
            "yesterday": yesterday, "last_month": last_month,
            "rate_per_h": round(rate_per_h, 2) if rate_per_h is not None else None,
            "by_resource_today": today_by_res,
            "leaderboard": rows,
            "priced_resources": [r for r in RESOURCES if rpu.get(r) is not None],
            "day_of_month": dom, "days_in_month": dim,
        }
