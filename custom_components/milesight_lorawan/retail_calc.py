"""Retail insights maths: store footfall, in-store-now, average dwell and per-zone dwell / staff coverage.
Pure Python (unit-tested). The hourly sampling / persistence lives in retail.py; this turns a snapshot of the
people-counter and occupancy devices into the numbers the dashboard shows."""
from __future__ import annotations

from typing import Any


def _fmt_dur(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s" if m < 10 else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h < 10 else f"{h}h"


def compute_retail(devices: list[dict[str, Any]], *, person_minutes: float = 0.0,
                   peak: int = 0, peak_at: str | None = None,
                   visitors_yesterday: int | None = None) -> dict[str, Any]:
    """devices: one dict per people-counter / occupancy device, already classified by the tracker:
      {name, area, kind: 'counter'|'zone'|'staff', in_today, out_today, people_now,
       dwell_s (direct avg, or None), occ_person_minutes, occ_sessions, occ_occupied_s}
    person_minutes: store person-minutes accumulated today (for the dwell estimate and the headline).
    """
    counters = [d for d in devices if d.get("kind") == "counter"]
    zones = [d for d in devices if d.get("kind") == "zone"]
    staff = [d for d in devices if d.get("kind") == "staff"]

    visitors_today = sum(int(d.get("in_today") or 0) for d in counters)
    out_total = sum(int(d.get("out_today") or 0) for d in counters)
    in_store_now = max(0, visitors_today - out_total)

    entrances = [{
        "device": d.get("name"), "area": d.get("area"),
        "in": int(d.get("in_today") or 0), "out": int(d.get("out_today") or 0),
        "net": int(d.get("in_today") or 0) - int(d.get("out_today") or 0),
    } for d in counters]
    entrances.sort(key=lambda r: r["in"], reverse=True)

    # average dwell: direct (VS350 passage counters etc.) when any device reports it, else Little's Law estimate
    direct = [float(d["dwell_s"]) for d in devices if isinstance(d.get("dwell_s"), (int, float)) and d["dwell_s"] > 0]
    if direct:
        avg_dwell_s: float | None = sum(direct) / len(direct)
        dwell_source = "measured"
    elif visitors_today > 0 and person_minutes > 0:
        avg_dwell_s = person_minutes * 60.0 / visitors_today
        dwell_source = "estimated"
    else:
        avg_dwell_s, dwell_source = None, None

    zone_rows = []
    for d in zones:
        if isinstance(d.get("dwell_s"), (int, float)) and d["dwell_s"] > 0:
            avg = float(d["dwell_s"])
        else:
            sess = int(d.get("occ_sessions") or 0)
            avg = (float(d["occ_person_minutes"]) * 60.0 / sess) if sess and d.get("occ_person_minutes") else None
        zone_rows.append({"name": d.get("name"), "area": d.get("area"), "staff": False,
                          "people_now": d.get("people_now"), "avg_dwell_s": avg,
                          "avg_dwell": _fmt_dur(avg)})
    zone_rows.sort(key=lambda r: (r["avg_dwell_s"] is None, -(r["avg_dwell_s"] or 0)))

    staff_rows = [{"name": d.get("name"), "area": d.get("area"), "staff": True,
                   "people_now": d.get("people_now"),
                   "coverage_s": float(d.get("occ_occupied_s") or 0.0),
                   "coverage": _fmt_dur(d.get("occ_occupied_s") or 0.0)} for d in staff]
    staff_rows.sort(key=lambda r: r["coverage_s"], reverse=True)

    staff_coverage_s = sum(r["coverage_s"] for r in staff_rows) if staff_rows else None

    compare_pct = None
    if visitors_yesterday:
        compare_pct = round((visitors_today - visitors_yesterday) / visitors_yesterday * 100)

    return {
        "visitors_today": visitors_today,
        "visitors_yesterday": visitors_yesterday,
        "out_today": out_total,
        "in_store_now": in_store_now,
        "peak_today": peak or 0,
        "peak_today_at": peak_at,
        "avg_dwell_s": avg_dwell_s,
        "avg_dwell": _fmt_dur(avg_dwell_s),
        "dwell_source": dwell_source,
        "entrances": entrances,
        "zones": zone_rows,
        "staff_zones": staff_rows,
        "staff_coverage_s": staff_coverage_s,
        "staff_coverage": _fmt_dur(staff_coverage_s) if staff_coverage_s is not None else None,
        "compare_pct": compare_pct,
        "counters": len(counters),
    }
