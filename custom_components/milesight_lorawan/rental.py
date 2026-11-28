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
    """All properties' bookings (and per-property guest-display settings) in one hub store, keyed by area name."""

    def __init__(self, hass) -> None:
        from homeassistant.helpers.storage import Store
        from .const import DOMAIN, STORAGE_VERSION
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.rentals")
        self._bookings: dict[str, dict] = {}
        self._config: dict[str, dict] = {}
        self._loaded = False

    async def async_load(self) -> None:
        data = (await self._store.async_load()) or {}
        if "bookings" in data or "config" in data:            # current nested shape
            self._bookings = data.get("bookings") or {}
            self._config = data.get("config") or {}
        else:                                                 # migrate the old flat {area: booking} shape
            self._bookings = data
            self._config = {}
        self._loaded = True

    async def _save(self) -> None:
        await self._store.async_save({"bookings": self._bookings, "config": self._config})

    def all(self) -> dict[str, dict]:
        return dict(self._bookings)

    def get(self, area: str) -> dict | None:
        return self._bookings.get(area)

    async def async_set(self, area: str, raw: Any) -> dict | None:
        """Set (or clear, when the cleaned booking is empty) one property's booking. Returns the stored booking."""
        area = (area or "").strip()
        if not area:
            return None
        booking = clean_booking(raw)
        if booking is None:
            self._bookings.pop(area, None)
        else:
            self._bookings[area] = booking
        await self._save()
        return booking

    # ---------------------------------------------------- per-property guest-display settings (Wi-Fi, rules, …)
    def config_all(self) -> dict[str, dict]:
        return dict(self._config)

    def get_config(self, area: str) -> dict | None:
        return self._config.get(area)

    async def async_set_config(self, area: str, raw: Any) -> dict | None:
        from .rental_display import clean_display_config
        area = (area or "").strip()
        if not area:
            return None
        cfg = clean_display_config(raw)
        if cfg is None:
            self._config.pop(area, None)
        else:
            self._config[area] = cfg
        await self._save()
        return cfg
