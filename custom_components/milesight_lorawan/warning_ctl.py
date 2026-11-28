"""Auto-switch a DS3604 to its warning template (Template 2) when a property's WS302 gets too loud, and back to
the welcome card (Template 1) when it quiets down again.

The link is per-property: the host picks a WS302 (or any WS302 in the area) and a dB limit in the Guest-display
→ Template 2 editor and turns on "Auto-switch on noise". We watch that sensor's level and, crossing the limit
(with a few dB of hysteresis so it doesn't flap), push Template 2 + three beeps; when it falls back below the
limit we re-push the welcome card and switch back to Template 1.
"""
from __future__ import annotations

import time
from typing import Any

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_DEVICE

HYSTERESIS_DB = 5.0        # must drop this far below the limit before we switch back
DEFAULT_LIMIT = 70.0


def _num(v: Any) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _area_eq(a: Any, b: Any) -> bool:
    return str(a or "").strip().casefold() == str(b or "").strip().casefold()


class WarningController:
    """One per gateway hub, driven off the shared BookingStore config."""

    def __init__(self, hass, store) -> None:
        self.hass = hass
        self.store = store
        self._unsub = None
        self._map: dict[str, tuple[str, float]] = {}   # entity_id -> (area, limit)
        self._warn: dict[str, bool] = {}               # area -> currently warning
        self._busy: set[str] = set()

    def shutdown(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _auto_source(self, area: str) -> str | None:
        for st in self.hass.states.async_all("sensor"):
            a = st.attributes
            if a.get("milesight_role") == "sound_monitor" and _area_eq(a.get("area"), area):
                return st.entity_id
        return None

    def reconfigure(self) -> None:
        """(Re)build the watch list from the current per-property display config."""
        from homeassistant.helpers.event import async_track_state_change_event
        self._map = {}
        for area, c in (self.store.config_all() or {}).items():
            if not c.get("warn_auto"):
                continue
            src = c.get("noise_source") or self._auto_source(area)
            if not src:
                continue
            self._map[src] = (area, _num(c.get("noise_limit")) or DEFAULT_LIMIT)
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._map:
            self._unsub = async_track_state_change_event(self.hass, list(self._map), self._on_change)

    def _displays_in(self, area: str) -> list:
        out = []
        for e in self.hass.config_entries.async_entries(DOMAIN):
            if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
                continue
            rt = getattr(e, "runtime_data", None)
            if rt is None or "ds3604" not in getattr(getattr(rt, "model", None), "features", frozenset()):
                continue
            try:
                if _area_eq(rt._area(), area):
                    out.append(rt)
            except Exception:  # noqa: BLE001
                pass
        return out

    def _on_change(self, event) -> None:
        new = event.data.get("new_state")
        if new is None:
            return
        area, limit = self._map.get(new.entity_id, (None, None))
        if area is None:
            return
        level = _num(new.attributes.get("level"))
        if level is None:
            level = _num(new.state)
        if level is None:
            return
        warning = self._warn.get(area, False)
        if not warning and level >= limit:
            self._switch(area, level, limit, True)
        elif warning and level <= limit - HYSTERESIS_DB:
            self._switch(area, level, limit, False)

    def _switch(self, area: str, level: float, limit: float, on: bool) -> None:
        if area in self._busy:
            return
        self._warn[area] = on
        self._busy.add(area)
        self.hass.async_create_task(self._apply(area, level, limit, on))

    async def _apply(self, area: str, level: float, limit: float, on: bool) -> None:
        from .rental_display import build_warning_template, build_welcome_template
        try:
            cfg = self.store.get_config(area) or {}
            displays = self._displays_in(area)
            if on:
                blocks = build_warning_template("noise", level, limit, cfg)
                for rt in displays:
                    try:
                        await rt.async_display(2, blocks, show=True, refresh=True, beeps=3)
                        rt.meta["_warn_active"] = True
                        rt._publish(time.time())
                    except Exception:  # noqa: BLE001
                        pass
            else:
                booking = self.store.get(area)
                blocks = build_welcome_template(booking, cfg)
                for rt in displays:
                    try:
                        await rt.async_display(1, blocks, show=True, refresh=True, only_changed=True)
                        rt.meta["_warn_active"] = False
                        rt._publish(time.time())
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            self._busy.discard(area)
