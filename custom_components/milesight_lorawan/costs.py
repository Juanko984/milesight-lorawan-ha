"""Running costs: four tariffs on the gateway turn metered energy, water, fuel and feed into money.

Reuses the devices you already have — CT clamps and energy meters bill electricity, water meters bill
water, fuel tanks bill diesel, feed silos bill feed. No new hardware. The maths lives in costs_calc.py;
this module reads each device's current meter / level every minute, feeds it to the tracker, prices it
with your tariffs and exposes it on a single "costs" role sensor for the dashboard cards.
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .analytics import Calendar
from .building import hub_device
from .const import (
    CONF_CURRENCY,
    CONF_ENTRY_TYPE,
    CONF_TARIFF_DIESEL,
    CONF_TARIFF_ELEC,
    CONF_TARIFF_FEED,
    CONF_TARIFF_WATER,
    DEFAULT_CURRENCY,
    DOMAIN,
    ENTRY_TYPE_DEVICE,
    SIGNAL_FLEET,
    STORAGE_VERSION,
)
from .costs_calc import CostTracker

SIGNAL_COSTS = f"{DOMAIN}_costs_{{}}"   # .format(hub entry_id)

_ELEC_KEYS = ("energy", "energy_a", "energy_b", "energy_c", "forward_active_energy")
_POWER_W_KEYS = ("power", "power_a", "power_b", "power_c")   # instantaneous watts


def tariffs(entry: ConfigEntry) -> dict[str, float | None]:
    o = entry.options
    return {"electricity": o.get(CONF_TARIFF_ELEC), "water": o.get(CONF_TARIFF_WATER),
            "diesel": o.get(CONF_TARIFF_DIESEL), "feed": o.get(CONF_TARIFF_FEED)}


def currency(hass: HomeAssistant, entry: ConfigEntry) -> str:
    return (entry.options.get(CONF_CURRENCY) or getattr(hass.config, "currency", None)
            or DEFAULT_CURRENCY)


def any_tariff(entry: ConfigEntry) -> bool:
    return any(v not in (None, "", 0) and float(v) > 0 for v in tariffs(entry).values())


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _elec_icon(rt) -> str:
    feats = getattr(rt.model, "features", frozenset())
    purpose = " ".join(str(rt.entry.options.get(k) or "") for k in ("purpose", "purpose_1", "purpose_2")).lower()
    if "pump" in feats or rt.entry.options.get("pump_enabled"):
        return "⚙️"
    if any(w in purpose for w in ("fridge", "cold", "freezer", "chiller")):
        return "❄️"
    if "socket" in feats or "load" in feats:
        return "🔌"
    return "⚡"


def device_meters(rt) -> list[dict[str, Any]]:
    """What this device bills, right now. Each: {id, label, icon, res, kind, reading, power_w}."""
    v = getattr(rt, "values", {}) or {}
    out: list[dict[str, Any]] = []
    label = rt.entry.title

    elec = sum(x for k in _ELEC_KEYS if (x := _num(v.get(k))) is not None)
    has_elec = any(_num(v.get(k)) is not None for k in _ELEC_KEYS)
    if has_elec:
        watts = sum(x for k in _POWER_W_KEYS if (x := _num(v.get(k))) is not None)
        kw = watts / 1000.0 + (_num(v.get("active_power")) or 0.0)   # active_power is already kW
        out.append({"id": f"{rt.deveui}:elec", "label": label, "icon": _elec_icon(rt),
                    "res": "electricity", "kind": "accum", "reading": elec, "power_kw": kw})

    if _num(v.get("meter_reading")) is not None and rt.entry.options.get("meter_type") == "water":
        out.append({"id": f"{rt.deveui}:water", "label": label, "icon": "🚰",
                    "res": "water", "kind": "accum", "reading": _num(v.get("meter_reading")), "power_kw": 0.0})

    cfg = getattr(rt, "tank_cfg", None)
    if cfg is not None:
        if cfg.contents == "fuel" and _num(v.get("tank_volume")) is not None:
            out.append({"id": f"{rt.deveui}:diesel", "label": label, "icon": "⛽",
                        "res": "diesel", "kind": "drain", "reading": _num(v.get("tank_volume")), "power_kw": 0.0})
        elif cfg.contents == "feed":
            kg = _num(v.get("tank_mass"))   # tank_mass is kg (litres/1000 × density)
            if kg is not None:
                out.append({"id": f"{rt.deveui}:feed", "label": label, "icon": "🌾",
                            "res": "feed", "kind": "drain", "reading": kg / 1000.0, "power_kw": 0.0})
    return out


class CostsTracker:
    """Reads every device's meter each minute, banks consumption and prices it with the current tariffs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.data: dict[str, Any] = {}
        self.store = None
        tz = dt_util.get_time_zone(hass.config.time_zone) or dt_util.UTC
        self.cal = Calendar(tz)
        self.tracker = CostTracker(self.cal)

    def _runtimes(self) -> list[Any]:
        out = []
        for e in self.hass.config_entries.async_entries(DOMAIN):
            rt = getattr(e, "runtime_data", None)
            if rt is not None and hasattr(rt, "deveui") and hasattr(rt, "model"):
                out.append(rt)
        return out

    @callback
    def update(self, _now: Any = None) -> None:
        ts = time.time()
        self.tracker.roll(ts)
        meta: dict[str, dict[str, Any]] = {}
        elec_kw = 0.0
        for rt in self._runtimes():
            for m in device_meters(rt):
                self.tracker.observe(m["id"], m["res"], m["kind"], m["reading"])
                meta[m["id"]] = {"label": m["label"], "icon": m["icon"], "res": m["res"]}
                elec_kw += m.get("power_kw") or 0.0

        from .costs_calc import r_per_unit
        rpu_elec = r_per_unit("electricity", tariffs(self.entry).get("electricity"))
        day_start = self.cal.day_start(self.cal.local_date(ts))
        hours = max(0.25, (ts - day_start) / 3600.0)
        pre = self.tracker.report(tariffs(self.entry), meta, ts, currency(self.hass, self.entry))
        elec_rate = elec_kw * rpu_elec if rpu_elec else 0.0
        non_elec_today = pre["today"] - pre["by_resource_today"].get("electricity", 0.0)
        rate = round(elec_rate + non_elec_today / hours, 2)
        self.data = {**pre, "rate_per_h": rate}

        if self.store is not None:
            # shorter than the 60 s update interval, or each update resets the timer and nothing persists
            # until a clean shutdown (same pitfall as the retail / area trackers).
            self.store.async_delay_save(lambda: self.tracker.s, 20)
        async_dispatcher_send(self.hass, SIGNAL_COSTS.format(self.entry.entry_id))

    @callback
    def maybe_update(self) -> None:
        self.update()


class CostSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Running costs"
    _attr_icon = "mdi:cash-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, tracker: CostsTracker) -> None:
        self.hass, self.entry, self.tracker = hass, entry, tracker
        self._attr_device_info = hub_device(entry)
        self._attr_unique_id = f"{entry.entry_id}_costs"
        self._attr_native_unit_of_measurement = currency(hass, entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_COSTS.format(self.entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self):
        return self.tracker.data.get("today") if self.tracker.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"milesight_role": "costs", "site": self.entry.title, **(self.tracker.data or {})}


def has_costs(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """True once a tariff is set and at least one device can bill something — so the cards are worth showing."""
    if not any_tariff(entry):
        return False
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        rt = getattr(e, "runtime_data", None)
        if rt is not None and device_meters(rt):
            return True
    return False


async def async_setup_costs(hass: HomeAssistant, entry: ConfigEntry) -> tuple[CostsTracker, list]:
    from homeassistant.helpers.storage import Store

    tracker = CostsTracker(hass, entry)
    tracker.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.costs_{entry.entry_id}")
    saved = await tracker.store.async_load()
    if isinstance(saved, dict) and saved.get("meters") is not None:
        tracker.tracker = CostTracker(tracker.cal, saved)
    tracker.update()
    ent = CostSensor(hass, entry, tracker)
    entry.async_on_unload(async_track_time_interval(hass, tracker.update, timedelta(seconds=60)))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_FLEET, tracker.maybe_update))
    return tracker, [ent]
