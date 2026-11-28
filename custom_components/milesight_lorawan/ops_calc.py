"""Ops Hub — pure, unit-tested logic for the lightweight management system (tasks, expenses, utility
reconciliation). No Home Assistant imports: the store (ops.py) and websocket (ops_ws.py) use these.

Money is kept as plain numbers (currency is set per gateway; defaults to ZAR/VAT 15%). Nothing here is tax advice;
the VAT split is the standard inclusive-amount formula so hosts can see reclaimable input VAT at a glance.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

VERTICALS = {
    "farm": "Farm",
    "facilities": "Facilities",
    "retail": "Retail",
    "shortstay": "Short-stay",
    "other": "Other",
}
EXPENSE_CATEGORIES = {
    "fuel": ("⛽", "Fuel"),
    "electricity": ("⚡", "Electricity"),
    "water": ("💧", "Water"),
    "feed": ("🌾", "Feed & seed"),
    "supplies": ("🧰", "Supplies"),
    "maintenance": ("🔧", "Maintenance"),
    "services": ("🧽", "Services"),
    "rates": ("🏛", "Rates & taxes"),
    "other": ("•", "Other"),
}
UTILITIES = {"electricity": ("Electricity", "kWh"), "water": ("Water", "kL")}


def money(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 2)


def vat_split(total_incl: Any, rate: float = 0.15) -> dict:
    """Split a VAT-inclusive amount into net + VAT (the standard inclusive formula)."""
    t = money(total_incl)
    if t is None:
        return {"net": None, "vat": None, "total": None}
    vat = round(t * rate / (1.0 + rate), 2)
    return {"net": round(t - vat, 2), "vat": vat, "total": t}


def reconcile(measured: Any, billed: Any, tol_pct: float = 5.0) -> dict:
    """Compare a utility bill's quantity to the metered consumption for the same period.
    status: matched | over (billed exceeds measured — dispute) | under (billed below measured — estimate / arrears)
    | nometer (no measured value to compare)."""
    m, b = money(measured), money(billed)
    if m is None or b is None:
        return {"variance_pct": None, "status": "nometer", "delta": None}
    if m == 0:
        return {"variance_pct": None, "status": "nometer", "delta": round((b or 0), 2)}
    var = (b - m) / m * 100.0
    status = "matched" if abs(var) <= tol_pct else ("over" if var > 0 else "under")
    return {"variance_pct": round(var, 1), "status": status, "delta": round(b - m, 2)}


def rollup(entries: Iterable[dict], key: str, amount_key: str = "amount") -> dict:
    """Sum `amount_key` grouped by `entries[key]` (e.g. by vertical or category)."""
    out: dict[str, float] = {}
    for e in entries or []:
        k = e.get(key) or "other"
        a = money(e.get(amount_key))
        if a is None:
            continue
        out[k] = round(out.get(k, 0.0) + a, 2)
    return out


def _in_period(iso: str | None, start: str | None, end: str | None) -> bool:
    if not iso:
        return False
    d = iso[:10]
    if start and d < start[:10]:
        return False
    if end and d > end[:10]:
        return False
    return True


def summary(expenses: list[dict], bills: list[dict], tasks: list[dict],
            month: str | None = None, vat_rate: float = 0.15) -> dict:
    """Headline KPIs for the Overview: this-month spend, receipts to review, utility flags, open tasks, VAT."""
    month = month or datetime.now().strftime("%Y-%m")
    month_exp = [e for e in expenses if str(e.get("date", ""))[:7] == month]
    spend = round(sum(money(e.get("amount")) or 0 for e in month_exp), 2)
    vat_total = round(sum(money(e.get("vat")) or 0 for e in expenses), 2)
    to_review = sum(1 for e in expenses if e.get("source") == "scan" and not e.get("approved"))
    flags = sum(1 for b in bills if reconcile(b.get("measured"), b.get("billed_qty"))["status"] in ("over", "under"))
    open_tasks = sum(1 for t in tasks if t.get("status") != "done")
    overdue = sum(1 for t in tasks if t.get("status") != "done" and t.get("due")
                  and str(t["due"])[:10] < datetime.now().strftime("%Y-%m-%d"))
    return {"spend_month": spend, "vat_total": vat_total, "to_review": to_review,
            "util_flags": flags, "open_tasks": open_tasks, "overdue_tasks": overdue, "month": month}


# ---------------------------------------------------------------- receipt parsing (pluggable extractor)
_AMT = re.compile(r"(?:R|ZAR)?\s*([0-9][0-9\s,]*\.\d{2})")
_DATE_PATTERNS = (
    (re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"), (1, 2, 3)),     # 2026-11-28
    (re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b"), (3, 2, 1)),     # 28/11/2026
)
_VAT_NO = re.compile(r"\bVAT(?:\s*(?:no|number|reg)\.?)?\s*[:#]?\s*(4\d{9})\b", re.I)
_LITRES = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:L|LTR|LITRE|LITER)S?\b", re.I)
_CAT_HINTS = (
    ("fuel", ("diesel", "petrol", "unleaded", "engen", "shell", "bp", "total ", "sasol", "fuel", "50ppm")),
    ("feed", ("afgri", "feed", "seed", "fertil", "lucerne", "maize")),
    ("electricity", ("eskom", "electricity", "kwh", "prepaid")),
    ("water", ("water", "municipal", " kl ")),
    ("supplies", ("makro", "builders", "hardware", "takealot")),
)


def _num(s: str) -> float:
    return round(float(s.replace(" ", "").replace(",", "")), 2)


def parse_receipt_text(text: str | None, vat_rate: float = 0.15) -> dict:
    """Best-effort extraction of {payee, date, total, vat, vat_no, litres, category} from raw receipt text.

    This is the built-in extractor. The image→text step is a pluggable backend (a cloud OCR API or a local
    engine); when one is configured it supplies the text, otherwise the host pastes/types it. Everything stays
    editable in the review screen — this only pre-fills."""
    out: dict[str, Any] = {"payee": None, "date": None, "total": None, "vat": None,
                           "vat_no": None, "litres": None, "category": None, "text": text or ""}
    if not text:
        return out
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        out["payee"] = lines[0][:60]
    low = text.lower()
    # amounts: the largest looks like the total (incl VAT); prefer a line mentioning total
    amts = [_num(m) for m in _AMT.findall(text)]
    total = None
    for ln in lines:
        if "total" in ln.lower():
            m = _AMT.search(ln)
            if m:
                total = _num(m.group(1))
                break
    if total is None and amts:
        total = max(amts)
    if total is not None:
        out["total"] = total
        # an explicit VAT line, else derive from the inclusive total
        vat = None
        for ln in lines:
            if "vat" in ln.lower() and "no" not in ln.lower() and "number" not in ln.lower():
                m = _AMT.search(ln)
                if m:
                    vat = _num(m.group(1))
                    break
        out["vat"] = vat if vat is not None else vat_split(total, vat_rate)["vat"]
    for pat, (yi, mi, di) in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                out["date"] = f"{int(m.group(yi)):04d}-{int(m.group(mi)):02d}-{int(m.group(di)):02d}"
            except ValueError:
                pass
            break
    mvno = _VAT_NO.search(text)
    if mvno:
        out["vat_no"] = mvno.group(1)
    ml = _LITRES.search(text)
    if ml:
        out["litres"] = round(float(ml.group(1)), 2)
    for cat, hints in _CAT_HINTS:
        if any(hhint in low for hhint in hints):
            out["category"] = cat
            break
    out["category"] = out["category"] or "other"
    return out


def clean_expense(raw: Any, vat_rate: float = 0.15) -> dict | None:
    """Validate an expense entry from the client into a stored dict (or None if there's nothing to store)."""
    if not isinstance(raw, dict):
        return None
    amount = money(raw.get("amount"))
    payee = (raw.get("payee") or "").strip()[:80] if isinstance(raw.get("payee"), str) else ""
    if amount is None and not payee:
        return None
    cat = raw.get("category") if raw.get("category") in EXPENSE_CATEGORIES else "other"
    vert = raw.get("vertical") if raw.get("vertical") in VERTICALS else "other"
    vat = money(raw.get("vat"))
    if vat is None and amount is not None:
        vat = vat_split(amount, vat_rate)["vat"]
    out = {"payee": payee or "—", "amount": amount, "vat": vat, "category": cat, "vertical": vert,
           "site": (raw.get("site") or "").strip()[:60] or None,
           "date": _iso_date(raw.get("date")) or datetime.now().strftime("%Y-%m-%d"),
           "source": raw.get("source") if raw.get("source") in ("scan", "bill", "manual") else "manual",
           "note": (raw.get("note") or "").strip()[:200] or None,
           "approved": bool(raw.get("approved", True))}
    return out


def clean_bill(raw: Any, vat_rate: float = 0.15) -> dict | None:
    if not isinstance(raw, dict):
        return None
    util = raw.get("utility") if raw.get("utility") in UTILITIES else None
    if util is None:
        return None
    out = {"utility": util, "unit": UTILITIES[util][1],
           "account": (raw.get("account") or "").strip()[:60] or None,
           "site": (raw.get("site") or "").strip()[:60] or None,
           "vertical": raw.get("vertical") if raw.get("vertical") in VERTICALS else "other",
           "period_start": _iso_date(raw.get("period_start")), "period_end": _iso_date(raw.get("period_end")),
           "billed_qty": money(raw.get("billed_qty")), "measured": money(raw.get("measured")),
           "amount": money(raw.get("amount")), "vat": money(raw.get("vat")),
           "meter_entity_id": (raw.get("meter_entity_id") or "").strip()[:120] or None}
    if out["vat"] is None and out["amount"] is not None:
        out["vat"] = vat_split(out["amount"], vat_rate)["vat"]
    return out


def clean_task(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = (raw.get("title") or "").strip()[:140] if isinstance(raw.get("title"), str) else ""
    if not title:
        return None
    return {"title": title,
            "vertical": raw.get("vertical") if raw.get("vertical") in VERTICALS else "other",
            "site": (raw.get("site") or "").strip()[:60] or None,
            "assignee": (raw.get("assignee") or "").strip()[:60] or None,
            "due": _iso_date(raw.get("due")),
            "status": raw.get("status") if raw.get("status") in ("todo", "doing", "done") else "todo",
            "priority": raw.get("priority") if raw.get("priority") in ("low", "med", "high") else "med",
            "source": raw.get("source") if raw.get("source") in ("manual", "sensor") else "manual"}


def _iso_date(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-" and s[:4].isdigit():
        return s[:16] if (len(s) > 10 and s[10] in ("T", " ")) else s[:10]
    return None
