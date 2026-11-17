"""Reporting framework — the report-type registry, period resolution and the shared report-record shape.

Pure Python (no Home Assistant imports), so it is unit-tested on its own. The Home Assistant glue
(reports_ha.py) owns history retrieval, PDF/CSV rendering and delivery; the websocket / service layer
triggers a run and lists what has been produced. A "report" is a point-in-time, archival artifact for a
defined period (a PDF to file with an auditor, or a CSV for payroll) — distinct from the live dashboards.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Any

# periods a report can cover. "week"/"month" = the last COMPLETE one; "custom" = an explicit start/end.
PERIODS = ("week", "month", "custom")


@dataclass(frozen=True)
class ReportType:
    id: str
    title: str
    icon: str
    desc: str
    formats: tuple[str, ...] = ("pdf",)
    scopes: tuple[str, ...] = ("site",)   # site | area | device — what the run can be narrowed to
    status: str = "ready"                 # "ready" (a generator exists) or "soon" (listed, not yet built)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "icon": self.icon, "desc": self.desc,
                "formats": list(self.formats), "scopes": list(self.scopes), "status": self.status}


# The catalogue. Order is the display order on the Reports page.
REPORT_TYPES: tuple[ReportType, ...] = (
    ReportType("cold_chain", "Cold-chain compliance", "mdi:snowflake-thermometer",
               "Temperature record, time-in-range, excursions and corrective actions per fridge / cold room.",
               ("pdf",), ("site",), "ready"),
    ReportType("device_health", "Device health & uptime", "mdi:access-point-network",
               "Online time, offline events, battery and link quality across the fleet — an SLA / support record.",
               ("pdf", "csv"), ("site",), "ready"),
    ReportType("energy", "Energy & cost", "mdi:lightning-bolt",
               "Consumption, duty cycle and tariff cost per load and per period — for finance.",
               ("pdf", "csv"), ("site",), "soon"),
    ReportType("team", "Team attendance & timesheets", "mdi:account-clock",
               "Hours worked, attendance and overtime per worker — payroll-ready.",
               ("pdf", "csv"), ("site",), "soon"),
    ReportType("occupancy", "Occupancy & area use", "mdi:floor-plan",
               "Occupied time, utilisation and sessions per space / area over the period.",
               ("pdf", "csv"), ("site",), "soon"),
)

BY_ID: dict[str, ReportType] = {t.id: t for t in REPORT_TYPES}


def types_public() -> list[dict[str, Any]]:
    return [t.public() for t in REPORT_TYPES]


def resolve_period(kind: str, now: datetime, start: datetime | None = None,
                   end: datetime | None = None) -> tuple[datetime, datetime, str]:
    """(start, end, label) for a report run. 'week' / 'month' = the last complete one before `now`;
    'custom' = the given [start, end) (end defaults to the start of today)."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "custom" and start is not None:
        e = end or today
        return start, e, f"{start:%d %b %Y} – {(e - timedelta(days=1)):%d %b %Y}"
    if kind == "month":
        e = today.replace(day=1)
        s = (e - timedelta(days=1)).replace(day=1)
        return s, e, s.strftime("%B %Y")
    e = today - timedelta(days=today.weekday())       # last complete Mon–Sun week
    s = e - timedelta(days=7)
    return s, e, f"Week {s.isocalendar()[1]}, {s:%d %b} – {(e - timedelta(days=1)):%d %b %Y}"


def make_record(type_id: str, *, period: str, created: str, status: str = "ok", fmt: str = "pdf",
                url: str | None = None, path: str | None = None, size: int | None = None,
                summary: str = "", rid: str | None = None, scope: str = "site") -> dict[str, Any]:
    """One row in the report library. `status`: ok | warn | error | soon."""
    t = BY_ID.get(type_id)
    return {
        "id": rid or f"{type_id}-{created}", "type": type_id, "title": t.title if t else type_id,
        "icon": t.icon if t else "mdi:file-document-outline", "period": period, "created": created,
        "status": status, "format": fmt, "scope": scope, "url": url, "path": path,
        "size": size, "summary": summary,
    }


def merge_records(*lists: list[dict[str, Any]], limit: int = 60) -> list[dict[str, Any]]:
    """Unify report rows from several sources (e.g. the hub index + the cold-chain engine), newest first,
    de-duplicated by url / id."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for rec in sorted((r for lst in lists for r in lst), key=lambda r: r.get("created") or "", reverse=True):
        key = str(rec.get("url") or rec.get("id") or "")
        if key and key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out[:limit]
