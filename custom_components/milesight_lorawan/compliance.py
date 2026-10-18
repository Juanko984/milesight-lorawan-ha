"""Cold-room compliance reports (food-safety / HACCP audits): for one fridge, freezer or cold room over a week or a
month, from the recorded temperature and door history – min / max / mean / mean kinetic temperature, time out of
range, excursions (out of range for longer than the alarm delay) with peak and duration, door openings, data
coverage and gaps, corrective actions, a daily table and a chart – as a printable PDF. Pure Python (unit-tested)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any

from .pdfmini import A4, Pdf, fit, text_width, wrap

MIN_COVERAGE = 95.0          # % of the period with readings for a clean record
MKT_DH_R = 10000.0           # ΔH/R in K (ΔH = 83.144 kJ/mol), the usual value for mean kinetic temperature


@dataclass
class Unit:
    name: str
    area: str | None = None
    kind: str = "Fridge / cold room"
    model: str | None = None
    deveui: str | None = None
    low: float | None = None
    high: float | None = None
    delay_min: float = 15
    left_open_min: float | None = None
    max_gap_s: float = 7200   # longer than this without a reading = no data
    extra: dict[str, Any] = field(default_factory=dict)


def period_bounds(kind: str, now: datetime) -> tuple[datetime, datetime, str]:
    """The last complete week (Mon–Sun) or month before `now` (local, tz-aware): (start, end, label)."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "month":
        end = today.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
        return start, end, start.strftime("%B %Y")
    end = today - timedelta(days=today.weekday())
    start = end - timedelta(days=7)
    return start, end, f"Week {start.isocalendar()[1]}, {start:%d %b} – {(end - timedelta(days=1)):%d %b %Y}"


def _segments(points: list[tuple[float, Any]], start: float, end: float, max_gap: float | None):
    """(t0, t1, value) pieces where a reading holds until the next one (at most max_gap), clipped to the period."""
    pts = sorted(points)
    for i, (ts, v) in enumerate(pts):
        nxt = pts[i + 1][0] if i + 1 < len(pts) else end
        t0, t1 = max(ts, start), min(nxt, end)
        if max_gap is not None:
            t1 = min(t1, ts + max_gap)
        if t1 > t0:
            yield t0, t1, v


def _split_days(t0: float, t1: float, tz: tzinfo):
    """Split [t0, t1) at local midnights: (day 'YYYY-MM-DD', a, b)."""
    while t0 < t1:
        d = datetime.fromtimestamp(t0, tz)
        nxt = d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        b = min(t1, nxt.timestamp())
        yield d.strftime("%Y-%m-%d"), t0, b
        t0 = b


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def analyse(unit: Unit, temps: list[tuple[float, Any]], doors: list[tuple[float, Any]] | None, start: float,
            end: float, tz: tzinfo, actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """temps: (ts, °C) readings (the last one before the start may be included); doors: (ts, open?) changes."""
    temps = [(ts, f) for ts, v in temps if (f := _num(v)) is not None]
    lo, hi = unit.low, unit.high

    def out_of(v: float) -> int:
        return -1 if lo is not None and v < lo else (1 if hi is not None and v > hi else 0)

    days: dict[str, dict[str, Any]] = {}
    d = datetime.fromtimestamp(start, tz)
    while d.timestamp() < end:
        days[d.strftime("%Y-%m-%d")] = {"min": None, "max": None, "sum": 0.0, "cov": 0.0, "out": 0.0,
                                        "exc": 0, "door": 0.0, "door_n": 0, "len": 0.0}
        d = (d + timedelta(days=1, hours=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    for name, a, b in _split_days(start, end, tz):
        if name in days:
            days[name]["len"] += b - a

    covered = out_s = wsum = 0.0
    mkt_sum = 0.0
    tmin = tmax = None
    for ts, v in temps:                                   # min / max from the readings inside the period
        if start <= ts < end:
            tmin = v if tmin is None else min(tmin, v)
            tmax = v if tmax is None else max(tmax, v)
            dd = days.get(datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d"))
            if dd is not None:
                dd["min"] = v if dd["min"] is None else min(dd["min"], v)
                dd["max"] = v if dd["max"] is None else max(dd["max"], v)
    runs: list[dict[str, Any]] = []                       # contiguous out-of-range stretches
    cur = None
    last_t1 = None
    for t0, t1, v in _segments(temps, start, end, unit.max_gap_s):
        dur = t1 - t0
        covered += dur
        wsum += v * dur
        mkt_sum += math.exp(-MKT_DH_R / (v + 273.15)) * dur
        o = out_of(v)
        for name, a, b in _split_days(t0, t1, tz):
            dd = days.get(name)
            if dd is not None:
                dd["cov"] += b - a
                dd["sum"] += v * (b - a)
                if o:
                    dd["out"] += b - a
        if o:
            out_s += dur
            if cur is not None and cur["dir"] == o and last_t1 is not None and t0 - last_t1 < 1:
                cur["end"] = t1
                cur["peak"] = max(cur["peak"], v) if o > 0 else min(cur["peak"], v)
            else:
                cur = {"start": t0, "end": t1, "dir": o, "peak": v}
                runs.append(cur)
        else:
            cur = None
        last_t1 = t1
    delay = float(unit.delay_min or 0) * 60
    excursions, brief = [], 0
    for r in runs:
        r["minutes"] = round((r["end"] - r["start"]) / 60)
        if r["end"] - r["start"] >= delay:
            r["open"] = r["end"] >= end - 1 and bool(temps) and out_of(temps[-1][1]) != 0
            excursions.append(r)
            dd = days.get(datetime.fromtimestamp(r["start"], tz).strftime("%Y-%m-%d"))
            if dd is not None:
                dd["exc"] += 1
        else:
            brief += 1

    door = {"count": 0, "open_s": 0.0, "longest_s": 0.0, "long": []}
    if doors is not None:
        changes = sorted((ts, bool(v) if isinstance(v, bool) else str(v).lower() in ("on", "open", "true", "1"))
                         for ts, v in doors if v not in (None, "unknown", "unavailable"))
        for t0, t1, is_open in _segments(changes, start, end, None):
            if not is_open:
                continue
            dur = t1 - t0
            door["open_s"] += dur
            door["longest_s"] = max(door["longest_s"], dur)
            if unit.left_open_min and dur >= unit.left_open_min * 60:
                door["long"].append({"start": t0, "minutes": round(dur / 60)})
            for name, a, b in _split_days(t0, t1, tz):
                if name in days:
                    days[name]["door"] += b - a
        prev = None
        for ts, is_open in changes:
            if is_open and prev is not True and start <= ts < end:
                door["count"] += 1
                dd = days.get(datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d"))
                if dd is not None:
                    dd["door_n"] += 1
            prev = is_open

    gaps = []                                             # stretches without readings
    edge = start
    for t0, t1, _v in _segments(temps, start, end, unit.max_gap_s):
        if t0 - edge >= unit.max_gap_s:
            gaps.append({"start": edge, "end": t0, "hours": round((t0 - edge) / 3600, 1)})
        edge = max(edge, t1)
    if end - edge >= unit.max_gap_s:
        gaps.append({"start": edge, "end": end, "hours": round((end - edge) / 3600, 1)})

    acts = sorted([a for a in (actions or []) if start <= float(a.get("ts", 0)) < end + 86400],
                  key=lambda a: a["ts"])
    for e in excursions:                                  # a corrective action logged during or after it, same day+1
        e["action"] = next((a for a in acts if e["start"] - 600 <= a["ts"] <= e["end"] + 86400), None)
    span = end - start
    coverage = round(covered / span * 100, 1) if span > 0 else 0.0
    reasons = []
    if excursions:
        reasons.append(f"{len(excursions)} excursion{'s' if len(excursions) != 1 else ''} out of range for longer "
                       f"than {int(unit.delay_min)} min")
    missing = [e for e in excursions if e["action"] is None]
    if missing:
        reasons.append(f"{len(missing)} without a recorded corrective action")
    if coverage < MIN_COVERAGE:
        reasons.append(f"data coverage {coverage:g} % (below {MIN_COVERAGE:g} %)")
    if not temps:
        reasons = ["no temperature readings in this period"]
    status = "compliant" if not reasons else ("deviations" if excursions and not missing and coverage >= MIN_COVERAGE
                                              else "not_compliant")
    day_rows = []
    for name, dd in days.items():
        day_rows.append({
            "day": name, "min": dd["min"], "max": dd["max"],
            "mean": round(dd["sum"] / dd["cov"], 1) if dd["cov"] else None,
            "out_min": round(dd["out"] / 60), "excursions": dd["exc"], "door_min": round(dd["door"] / 60),
            "door_count": dd["door_n"], "coverage": round(dd["cov"] / dd["len"] * 100) if dd["len"] else 0})
    return {
        "status": status, "reasons": reasons, "readings": sum(1 for ts, _ in temps if start <= ts < end),
        "min": tmin, "max": tmax, "mean": round(wsum / covered, 2) if covered else None,
        "mkt": round(MKT_DH_R / -math.log(mkt_sum / covered) - 273.15, 2) if covered else None,
        "out_min": round(out_s / 60), "in_range_pct": round((1 - out_s / covered) * 100, 2) if covered else None,
        "excursions": excursions, "brief": brief, "door": door, "coverage": coverage, "gaps": gaps,
        "days": day_rows, "actions": acts, "start": start, "end": end,
    }


def chart_points(temps: list[tuple[float, Any]], start: float, end: float, buckets: int = 400) -> list[tuple[float, float]]:
    """Thin the readings for the chart, keeping each bucket's min and max so peaks stay visible."""
    pts = [(ts, f) for ts, v in temps if start <= ts < end and (f := _num(v)) is not None]
    if len(pts) <= buckets * 2:
        return pts
    width = (end - start) / buckets
    out: list[tuple[float, float]] = []
    b: list[tuple[float, float]] = []
    edge = start + width
    for p in pts:
        while p[0] >= edge:
            if b:
                lo, hi = min(b, key=lambda x: x[1]), max(b, key=lambda x: x[1])
                out += sorted({lo, hi})
            b, edge = [], edge + width
        b.append(p)
    if b:
        lo, hi = min(b, key=lambda x: x[1]), max(b, key=lambda x: x[1])
        out += sorted({lo, hi})
    return out


def merge_hourly(raw: list[tuple[float, Any]], hourly: list[tuple], start: float) -> tuple[list, float | None]:
    """Fill the stretch before the first raw reading with hourly statistics (mean held for the hour, with the
    hour's min and max as short points so peaks and lows still count). Returns (points, raw_from)."""
    def num(v: Any) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    first = next((ts for ts, v in raw if num(v) is not None and ts >= start), None)
    if not hourly or (first is not None and first - start < 3 * 3600):
        return raw, None
    cut = first if first is not None else float("inf")
    pts = []
    for ts, lo, mean, hi in hourly:
        if ts + 3600 > cut:
            break
        if mean is None:
            continue
        pts.append((ts, mean))
        for k, v in enumerate(x for x in (lo, hi) if x is not None and x != mean):
            pts += [(ts + 1200 + k * 1200, v), (ts + 1201 + k * 1200, mean)]
    keep = [(ts, v) for ts, v in raw if ts >= cut]
    return sorted(pts) + keep, (cut if pts else None)


def _dur(minutes: float) -> str:
    m = int(round(minutes))
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} h {m:02d} min"
    d, h = divmod(h, 24)
    return f"{d} d {h} h"


def _t(v: Any, nd: int = 1) -> str:
    return "–" if v is None else f"{v:.{nd}f} °C"


STATUS = {"compliant": ("COMPLIANT", "#1a7f37"), "deviations": ("DEVIATIONS – ACTIONED", "#9a6700"),
          "not_compliant": ("NOT COMPLIANT", "#cf222e")}


def report_pdf(site: dict[str, Any], unit: Unit, res: dict[str, Any], temps: list[tuple[float, Any]],
               period_label: str, created: str, tz: tzinfo) -> bytes:
    """The printable record for one unit."""
    pdf = Pdf(title=f"Temperature record – {unit.name} – {period_label}", author=site.get("company") or "")
    W, H = A4
    M = 40
    ink, mute, line_c, band = "#1b1b1b", "#57606a", "#d0d7de", "#f6f8fa"

    def fmt(ts: float, f: str = "%d %b %H:%M") -> str:
        return datetime.fromtimestamp(ts, tz).strftime(f)

    state = {"page": None, "y": 0.0}

    def footers() -> None:
        foot = " · ".join(x for x in (site.get("company"), site.get("site"), f"created {created}") if x)
        for n, pg in enumerate(pdf.pages, 1):
            pg.line(M, H - 32, W - M, H - 32, line_c)
            pg.text(M, H - 20, fit(foot, 7.5, W - 2 * M - 80), 7.5, color=mute)
            pg.text(W - M, H - 20, f"Page {n} of {len(pdf.pages)}", 7.5, color=mute, align="right")

    def new_page(first: bool = False):
        p = pdf.page()
        state["page"] = p
        if not first:
            p.text(M, 40, fit(f"{unit.name} · {period_label}", 9, W - 2 * M), 9, True, mute)
            state["y"] = 60
        return p

    def need(h: float) -> None:
        if state["y"] + h > H - 50:
            new_page()

    def heading(s: str) -> None:
        need(40)
        p = state["page"]
        state["y"] += 22
        p.text(M, state["y"], s, 12, True, ink)
        state["y"] += 8

    def table(cols: list[tuple[str, float, str]], rows: list[list[str]], colors: list[str | None] | None = None):
        """cols: (title, width, align)."""
        def head():
            p = state["page"]
            p.rect(M, state["y"], W - 2 * M, 16, fill=band)
            x = M
            for title, w, al in cols:
                p.text(x + (w - 4 if al == "right" else 4), state["y"] + 11, title, 7.5, True, mute,
                       "right" if al == "right" else "left")
                x += w
            state["y"] += 16
        need(32)
        head()
        for i, r in enumerate(rows):
            if state["y"] + 14 > H - 50:
                new_page()
                head()
            p = state["page"]
            x = M
            for (title, w, al), cell in zip(cols, r):
                col = (colors[i] if colors else None) or ink
                p.text(x + (w - 4 if al == "right" else 4), state["y"] + 10, fit(cell, 8, w - 8), 8,
                       color=col, align="right" if al == "right" else "left")
                x += w
            state["y"] += 14
            p.line(M, state["y"], W - M, state["y"], line_c, 0.3)

    # ---------------------------------------------------------------- page 1: header
    p = new_page(first=True)
    p.rect(0, 0, W, 78, fill="#0b3d62")
    p.text(M, 32, "Cold-chain temperature record", 18, True, "#ffffff")
    p.text(M, 52, fit(" · ".join(x for x in (site.get("company"), site.get("site"), site.get("address")) if x),
                      10, W - 2 * M - 170), 10, color="#d6e4f0")
    p.text(M, 67, f"Period: {period_label}  ({fmt(res['start'], '%d %b %Y %H:%M')} – "
                  f"{fmt(res['end'] - 1, '%d %b %Y %H:%M')})", 9, color="#d6e4f0")
    label, colour = STATUS[res["status"]]
    bw = text_width(label, 11, True) + 24
    p.rect(W - M - bw, 26, bw, 26, fill=colour)
    p.text(W - M - bw / 2, 43, label, 11, True, "#ffffff", "center")

    y = 100
    info = [("Unit", unit.name), ("Area", unit.area or "–"), ("Type", unit.kind),
            ("Allowed range", f"{'–' if unit.low is None else f'{unit.low:g}'} … "
                              f"{'–' if unit.high is None else f'{unit.high:g}'} °C"),
            ("Alarm delay", f"{unit.delay_min:g} min"),
            ("Sensor", " · ".join(x for x in (unit.model, (unit.deveui or "").upper()) if x) or "–")]
    for i, (k, v) in enumerate(info):
        x = M + (i % 3) * ((W - 2 * M) / 3)
        yy = y + (i // 3) * 30
        p.text(x, yy, k.upper(), 7, True, mute)
        p.text(x, yy + 13, fit(v, 10.5, (W - 2 * M) / 3 - 8), 10.5, True, ink)
    y += 66

    # KPI boxes
    door = res["door"]
    kpis = [("Minimum", _t(res["min"])), ("Maximum", _t(res["max"])), ("Mean", _t(res["mean"])),
            ("Mean kinetic temp.", _t(res["mkt"])),
            ("Time out of range", _dur(res["out_min"])), ("Excursions", f"{len(res['excursions'])}"
                                                                         f"  (+{res['brief']} brief)"),
            ("Door open", f"{_dur(door['open_s'] / 60)} ({door['count']}×)" if door["count"] or door["open_s"]
             else "–"), ("Data coverage", f"{res['coverage']:g} %")]
    bw = (W - 2 * M - 3 * 8) / 4
    for i, (k, v) in enumerate(kpis):
        x = M + (i % 4) * (bw + 8)
        yy = y + (i // 4) * 48
        bad = (k == "Excursions" and res["excursions"]) or (k == "Data coverage" and res["coverage"] < MIN_COVERAGE) \
            or (k == "Time out of range" and res["out_min"] > 0)
        p.rect(x, yy, bw, 40, fill=band, stroke=line_c)
        p.text(x + 8, yy + 13, k, 7.5, color=mute)
        p.text(x + 8, yy + 31, fit(v, 12.5, bw - 14, True), 12.5, True, "#cf222e" if bad else ink)
    y += 100

    if res["reasons"]:
        for ln in wrap("Findings: " + "; ".join(res["reasons"]) + ".", 9, W - 2 * M):
            p.text(M, y, ln, 9, color=colour)
            y += 12
    else:
        p.text(M, y, "Findings: the temperature stayed within the allowed range for the whole period "
                     "(short door openings and defrost cycles below the alarm delay are not excursions).", 8.5,
               color=colour)
        y += 12
    for note in res.get("notes", []):
        p.text(M, y, fit("Note: " + note + ".", 8, W - 2 * M), 8, color=mute)
        y += 11
    y += 6

    # ---------------------------------------------------------------- chart
    cx, cy, cw, ch = M + 34, y + 10, W - 2 * M - 34, 190
    pts = chart_points(temps, res["start"], res["end"])
    vals = [v for _, v in pts]
    lim = [x for x in (unit.low, unit.high) if x is not None]
    vmin = min(vals + lim) if vals or lim else 0
    vmax = max(vals + lim) if vals or lim else 10
    if vmax - vmin < 4:
        vmin, vmax = vmin - 2, vmax + 2
    pad = (vmax - vmin) * 0.08
    vmin, vmax = math.floor(vmin - pad), math.ceil(vmax + pad)

    def X(ts: float) -> float:
        return cx + (ts - res["start"]) / (res["end"] - res["start"]) * cw

    def Y(v: float) -> float:
        return cy + ch - (v - vmin) / (vmax - vmin) * ch

    p.text(M, y, "Temperature over the period", 10, True, ink)
    if unit.low is not None or unit.high is not None:
        top = Y(min(vmax, unit.high if unit.high is not None else vmax))
        bot = Y(max(vmin, unit.low if unit.low is not None else vmin))
        p.rect(cx, top, cw, bot - top, fill="#e6f4ea")
    for e in res["excursions"]:
        p.rect(X(e["start"]), cy, max(1.0, X(e["end"]) - X(e["start"])), ch, fill="#fde2e1")
    step = max(1, round((vmax - vmin) / 6))
    v = math.ceil(vmin / step) * step
    while v <= vmax:
        p.line(cx, Y(v), cx + cw, Y(v), line_c, 0.3)
        p.text(cx - 4, Y(v) + 3, f"{v:g}°", 7, color=mute, align="right")
        v += step
    ndays = max(1, round((res["end"] - res["start"]) / 86400))
    every = 1 if ndays <= 8 else (2 if ndays <= 16 else 4)
    d = datetime.fromtimestamp(res["start"], tz)
    i = 0
    while d.timestamp() < res["end"]:
        x = X(d.timestamp())
        p.line(x, cy, x, cy + ch, line_c, 0.3)
        if i % every == 0:
            p.text(x + 2, cy + ch + 10, d.strftime("%a %d" if ndays <= 8 else "%d %b"), 7, color=mute)
        d = (d + timedelta(days=1, hours=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        i += 1
    for lim_v in (unit.low, unit.high):
        if lim_v is not None and vmin <= lim_v <= vmax:
            p.line(cx, Y(lim_v), cx + cw, Y(lim_v), "#cf222e", 0.8, dash=(4, 3))
    seg: list[tuple[float, float]] = []
    prev_ts = None
    for ts, val in pts:
        if prev_ts is not None and ts - prev_ts > unit.max_gap_s:
            p.polyline(seg, "#0969da", 0.9)
            seg = []
        seg.append((X(ts), Y(val)))
        prev_ts = ts
    p.polyline(seg, "#0969da", 0.9)
    p.rect(cx, cy, cw, ch, stroke="#8c959f", width=0.5)
    p.text(cx, cy + ch + 22, "Blue: temperature · green band: allowed range · red dashed: limits · "
                             "red shading: excursions", 7, color=mute)
    state["y"] = cy + ch + 30

    # ---------------------------------------------------------------- daily table
    heading("Daily summary")
    cols = [("Day", 92, "left"), ("Min", 56, "right"), ("Max", 56, "right"), ("Mean", 56, "right"),
            ("Out of range", 72, "right"), ("Excursions", 58, "right"), ("Door open", 70, "right"),
            ("Coverage", 55, "right")]
    rows, colors = [], []
    for r in res["days"]:
        day = datetime.strptime(r["day"], "%Y-%m-%d").strftime("%a %d %b %Y")
        rows.append([day, _t(r["min"]), _t(r["max"]), _t(r["mean"]), _dur(r["out_min"]) if r["out_min"] else "–",
                     str(r["excursions"] or "–"),
                     f"{_dur(r['door_min'])} ({r['door_count']}×)" if r["door_count"] or r["door_min"] else "–",
                     f"{r['coverage']} %"])
        colors.append("#cf222e" if r["excursions"] else (mute if r["coverage"] < MIN_COVERAGE else None))
    table(cols, rows, colors)

    # ---------------------------------------------------------------- excursions
    heading("Excursions (out of range longer than the alarm delay)")
    if res["excursions"]:
        cols = [("Start", 82, "left"), ("End", 82, "left"), ("Duration", 64, "right"), ("Peak", 56, "right"),
                ("Corrective action", W - 2 * M - 284, "left")]
        rows = []
        for e in res["excursions"]:
            a = e.get("action")
            rows.append([fmt(e["start"]), "ongoing" if e.get("open") else fmt(e["end"]), _dur(e["minutes"]),
                         _t(e["peak"]), (f"{a['text']} ({a.get('by') or ''} {fmt(a['ts'])})".replace(" ( ", " (")
                                         if a else "NONE RECORDED")])
        table(cols, rows, [None if e.get("action") else "#cf222e" for e in res["excursions"]])
    else:
        need(16)
        state["page"].text(M, state["y"] + 12, "None.", 9, color=ink)
        state["y"] += 18

    if res["door"]["long"]:
        heading(f"Door left open longer than {unit.left_open_min:g} min")
        table([("Opened", 120, "left"), ("Open for", 80, "right")],
              [[fmt(x["start"]), _dur(x["minutes"])] for x in res["door"]["long"]])

    heading("Data gaps (no reading for longer than the device's offline time)")
    if res["gaps"]:
        table([("From", 120, "left"), ("To", 120, "left"), ("Length", 70, "right")],
              [[fmt(g["start"]), fmt(g["end"]), f"{g['hours']:g} h"] for g in res["gaps"]])
    else:
        need(16)
        state["page"].text(M, state["y"] + 12, "None – readings were received throughout the period.", 9,
                           color=ink)
        state["y"] += 18

    heading("Corrective actions and notes")
    if res["actions"]:
        table([("When", 90, "left"), ("By", 90, "left"), ("Action", W - 2 * M - 180, "left")],
              [[fmt(a["ts"]), a.get("by") or "–", a.get("text") or ""] for a in res["actions"]])
    else:
        need(16)
        state["page"].text(M, state["y"] + 12, "None recorded. Record actions in Home Assistant: device → "
                                                "Log corrective action, or the service milesight_lorawan."
                                                "log_corrective_action.", 8.5, color=mute)
        state["y"] += 18

    # ---------------------------------------------------------------- sign-off
    need(90)
    p = state["page"]
    y = state["y"] + 40
    third = (W - 2 * M - 40) / 3
    for i, lab in enumerate(("Reviewed by (name)", "Signature", "Date")):
        x = M + i * (third + 20)
        p.line(x, y, x + third, y, "#8c959f", 0.6)
        p.text(x, y + 11, lab, 7.5, color=mute)
    p.text(M, y + 34, fit(f"{res['readings']} readings. Times in {datetime.fromtimestamp(res['start'], tz).tzname()}."
                          f" Mean kinetic temperature with dH/R = 10 000 K. Generated automatically from the sensor "
                          f"history recorded by Home Assistant.", 7, W - 2 * M), 7, color=mute)
    footers()
    return pdf.output()


def summary_line(unit_name: str, res: dict[str, Any]) -> str:
    label = STATUS[res["status"]][0].title()
    return (f"{unit_name}: {label} – {_t(res['min'])} … {_t(res['max'])}, out of range "
            f"{_dur(res['out_min'])}, {len(res['excursions'])} excursion(s), coverage {res['coverage']:g} %")
