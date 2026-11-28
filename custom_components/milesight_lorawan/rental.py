"""Short-stay booking details, entered by the host on the Property page and shared by all viewers.

A booking is per property AREA (the Home Assistant area a property's devices live in): how many guests the
booking is for, and the arrival / departure date-times. The Property card reads these over the websocket to show
"Booking for N", the check-in time and the check-out countdown, and to judge over-capacity against the booked
count. Stored once in a single hub store (not per-viewer), so every dashboard shows the same booking.

Pure helpers (clean_booking / bookings_summary) are unit-tested; the Store wrapper is exercised by the stubbed
runtime test.
"""
from __future__ import annotations

from typing import Any


def _iso_or_none(v: Any) -> str | None:
    """Keep an ISO-ish date / date-time string ('2026-11-14' or '2026-11-14T15:02'); reject anything else."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or len(s) > 40:
        return None
    # minimal shape check: starts YYYY-MM-DD, the rest (time) is left to the client
    if len(s) >= 10 and s[4] == "-" and s[7] == "-" and s[:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit():
        return s
    return None


def clean_booking(raw: Any) -> dict | None:
    """Validate one booking dict from the client into {guests?, arrival?, departure?, notes?}. Returns None when
    there is nothing worth storing (so clearing a booking removes it)."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        out["name"] = name.strip()[:80]
    g = raw.get("guests")
    if isinstance(g, bool):
        g = None
    if isinstance(g, (int, float)) and 0 < int(g) <= 64:
        out["guests"] = int(g)
    for k in ("arrival", "departure"):
        iso = _iso_or_none(raw.get(k))
        if iso:
            out[k] = iso
    notes = raw.get("notes")
    if isinstance(notes, str) and notes.strip():
        out["notes"] = notes.strip()[:200]
    return out or None


class BookingStore:
    """All properties' bookings in one hub store, keyed by area name."""

    def __init__(self, hass) -> None:
        from homeassistant.helpers.storage import Store
        from .const import DOMAIN, STORAGE_VERSION
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.rentals")
        self._data: dict[str, dict] = {}
        self._loaded = False

    async def async_load(self) -> None:
        self._data = (await self._store.async_load()) or {}
        self._loaded = True

    def all(self) -> dict[str, dict]:
        return dict(self._data)

    def get(self, area: str) -> dict | None:
        return self._data.get(area)

    async def async_set(self, area: str, raw: Any) -> dict | None:
        """Set (or clear, when the cleaned booking is empty) one property's booking. Returns the stored booking."""
        area = (area or "").strip()
        if not area:
            return None
        booking = clean_booking(raw)
        if booking is None:
            self._data.pop(area, None)
        else:
            self._data[area] = booking
        await self._store.async_save(self._data)
        return booking
