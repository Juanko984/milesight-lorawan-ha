"""Ops Hub store — expenses, utility bills and tasks for the lightweight management system, kept in one hub
store and shared by every viewer. Pure validation lives in ops_calc; this just persists the collections."""
from __future__ import annotations

import time
import uuid
from typing import Any

from . import ops_calc as _calc

_COLLECTIONS = ("expenses", "bills", "tasks")
_CLEAN = {"expenses": _calc.clean_expense, "bills": _calc.clean_bill, "tasks": _calc.clean_task}
_DEFAULTS = {"settings": {"currency": "R", "vat_rate": 0.15, "tol_pct": 5.0}}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class OpsStore:
    def __init__(self, hass) -> None:
        from homeassistant.helpers.storage import Store
        from .const import DOMAIN, STORAGE_VERSION
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.ops")
        self._data: dict[str, Any] = {c: {} for c in _COLLECTIONS}
        self._data["settings"] = dict(_DEFAULTS["settings"])

    async def async_load(self) -> None:
        data = (await self._store.async_load()) or {}
        for c in _COLLECTIONS:
            self._data[c] = data.get(c) or {}
        self._data["settings"] = {**_DEFAULTS["settings"], **(data.get("settings") or {})}

    def settings(self) -> dict:
        return dict(self._data["settings"])

    def _list(self, c: str) -> list[dict]:
        return [{"id": k, **v} for k, v in (self._data.get(c) or {}).items()]

    def all(self) -> dict:
        vat = float(self._data["settings"].get("vat_rate") or 0.15)
        exp, bills, tasks = self._list("expenses"), self._list("bills"), self._list("tasks")
        for b in bills:
            b["recon"] = _calc.reconcile(b.get("measured"), b.get("billed_qty"),
                                         float(self._data["settings"].get("tol_pct") or 5.0))
        return {
            "settings": self.settings(),
            "expenses": sorted(exp, key=lambda e: str(e.get("date", "")), reverse=True),
            "bills": sorted(bills, key=lambda b: str(b.get("period_end") or ""), reverse=True),
            "tasks": sorted(tasks, key=lambda t: (t.get("status") == "done", str(t.get("due") or "9999"))),
            "summary": _calc.summary(exp, bills, tasks, vat_rate=vat),
            "by_vertical": _calc.rollup(exp, "vertical"),
            "by_category": _calc.rollup(exp, "category"),
        }

    async def async_set(self, collection: str, item_id: str | None, raw: Any) -> dict | None:
        if collection not in _COLLECTIONS:
            return None
        clean = _CLEAN[collection](raw, float(self._data["settings"].get("vat_rate") or 0.15)) \
            if collection != "tasks" else _CLEAN[collection](raw)
        if clean is None:
            return None
        iid = item_id or _new_id()
        clean["updated"] = round(time.time())
        self._data[collection][iid] = clean
        await self._store.async_save(self._data)
        return {"id": iid, **clean}

    async def async_delete(self, collection: str, item_id: str) -> bool:
        if collection in _COLLECTIONS and item_id in self._data.get(collection, {}):
            self._data[collection].pop(item_id, None)
            await self._store.async_save(self._data)
            return True
        return False

    async def async_set_setting(self, key: str, value: Any) -> dict:
        if key in ("currency",) and isinstance(value, str):
            self._data["settings"][key] = value.strip()[:4] or "R"
        elif key in ("vat_rate", "tol_pct"):
            try:
                self._data["settings"][key] = max(0.0, float(value))
            except (TypeError, ValueError):
                pass
        await self._store.async_save(self._data)
        return self.settings()
