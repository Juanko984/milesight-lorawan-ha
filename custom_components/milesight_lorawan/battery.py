"""Battery forecast: when will this device need new batteries? Pure Python (unit-tested).

Milesight devices report battery in whole percent and it falls slowly in steps, so the forecast works on one
sample per day (the lowest reading of the day) and fits a straight line through the last months. The drain
scales with how often the device reports, so the slope is corrected when the reporting rate changed (radio
transmissions dominate the consumption). A jump up of 25 points or more means the batteries were replaced:
the history restarts and a 'battery replaced' service entry is made."""
from __future__ import annotations

from typing import Any

DAY = 86400
KEEP_DAYS = 400
FIT_DAYS = 180
MIN_SPAN_DAYS = 14             # need at least two weeks of history
REPLACED_JUMP = 25             # % points up = new batteries
V_FULL, V_EMPTY = 3.6, 3.0     # Li-SOCl2 / lithium primary cells, for devices that only report a voltage


def pct_from_voltage(v: float, full: float = V_FULL, empty: float = V_EMPTY) -> float:
    """Rough: lithium primary cells stay flat most of their life, so voltage alone is a late warning."""
    return round(max(0.0, min(100.0, (v - empty) / (full - empty) * 100)), 1)


class BatteryForecast:
    """state: {'days': [[day_index, pct, uplinks], …], 'replaced': [ts, …]} – day_index = local date ordinal."""

    def __init__(self, state: dict | None = None) -> None:
        st = state or {}
        self.days: list[list[float]] = [list(d) for d in st.get("days", [])]
        self.replaced: list[float] = list(st.get("replaced", []))

    def to_dict(self) -> dict[str, Any]:
        return {"days": self.days, "replaced": self.replaced}

    def add(self, day: int, pct: float, ts: float) -> bool:
        """One battery reading on local day `day` (date ordinal). Returns True when a replacement was detected."""
        if not isinstance(pct, (int, float)) or isinstance(pct, bool) or not 0 <= pct <= 100:
            return False
        replaced = False
        if self.days and pct - self.days[-1][1] >= REPLACED_JUMP and pct >= 80:
            self.days = []
            self.replaced.append(ts)
            self.replaced = self.replaced[-10:]
            replaced = True
        if self.days and self.days[-1][0] == day:
            self.days[-1][1] = min(self.days[-1][1], float(pct))
            self.days[-1][2] = self.days[-1][2] + 1
        else:
            self.days.append([day, float(pct), 1])
        self.days = [d for d in self.days if d[0] > day - KEEP_DAYS]
        return replaced

    def forecast(self, today: int, low_pct: float, uplinks_per_day_now: float | None = None) -> dict[str, Any]:
        """{'days_left': days until the battery reaches low_pct (None if unknown), 'replace_on': date ordinal,
        'pct_per_month', 'method', 'reason'}."""
        pts = [d for d in self.days if d[0] > today - FIT_DAYS]
        out: dict[str, Any] = {"days_left": None, "replace_on": None, "pct_per_month": None, "samples": len(pts),
                               "method": None, "reason": None, "last_replaced": self.replaced[-1] if self.replaced else None}
        if not pts:
            out["reason"] = "no battery readings yet"
            return out
        now_pct = pts[-1][1]
        if now_pct <= low_pct:
            out.update(days_left=0, replace_on=today, method="already low")
            return out
        span = pts[-1][0] - pts[0][0]
        if span < MIN_SPAN_DAYS:
            out["reason"] = f"collecting – {int(span)} of {MIN_SPAN_DAYS} days of history"
            return out
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx else 0.0      # % per day
        if slope >= -1e-4:
            out["reason"] = f"no drop yet ({now_pct:g} % for {int(span)} days)"
            out["method"] = "flat"
            return out
        avg_up = sum(p[2] for p in pts) / n
        if uplinks_per_day_now and avg_up > 0:
            ratio = max(0.25, min(4.0, uplinks_per_day_now / avg_up))
            if abs(ratio - 1) > 0.2:
                slope *= ratio
                out["method"] = f"trend, adjusted ×{ratio:.2f} for the reporting rate"
        out["method"] = out["method"] or "trend"
        left = (now_pct - low_pct) / -slope
        left = min(left, 3650.0)
        out.update(days_left=int(round(left)), replace_on=today + int(round(left)),
                   pct_per_month=round(slope * 30, 2))
        return out
