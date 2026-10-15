"""Per-device runtime: decodes uplinks, runs analytics, persists state."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .analytics import BinaryEventTracker, Calendar, MinMaxTracker, OccupancyTracker
from .const import (
    CONF_CLOSE_HOUR,
    CONF_CO2_LIMIT,
    CONF_INSTALL_HEIGHT_MM,
    CONF_MAINS_VOLTAGE,
    CONF_RUN_THRESHOLD_A,
    CONF_DEVEUI,
    CONF_EMPTY_GRACE_MIN,
    CONF_LEFT_OPEN_MIN,
    CONF_MAX_GAP_MIN,
    CONF_MODEL,
    CONF_OPEN_DAYS,
    CONF_OPEN_HOUR,
    DEFAULT_CLOSE_HOUR,
    DEFAULT_CO2_LIMIT,
    DEFAULT_EMPTY_GRACE_MIN,
    DEFAULT_LEFT_OPEN_MIN,
    DEFAULT_MAX_GAP_MIN,
    DEFAULT_OPEN_DAYS,
    DEFAULT_OPEN_HOUR,
    DEFAULT_RUN_THRESHOLD_A,
    DOMAIN,
    SIGNAL_UPDATE,
    SIGNAL_UPLINK,
    STORAGE_VERSION,
    TICK_SECONDS,
    WEEKDAYS,
)
from .decoders import Uplink
from .models import MODELS, Model

_LOGGER = logging.getLogger(__name__)

def _flag(v: Any) -> bool | None:
    return None if v is None else bool(v)


CT_CURRENT_KEYS = ("current", "current_1", "current_2", "current_3")


def _load_running(d: dict, lim: dict) -> bool | None:
    """CT range: the load counts as running while any channel is at or above the threshold."""
    amps = [d[k] for k in CT_CURRENT_KEYS if isinstance(d.get(k), (int, float))]
    return any(a >= lim["run_a"] for a in amps) if amps else None


# feature -> (extract(decoded, limits) -> bool | None, status text on, status text off)
BINARY_FEATURES: dict[str, tuple[Callable[[dict, dict], bool | None], str, str]] = {
    "door": (lambda d, _: _flag(d.get("magnet_status")), "Open since {t}", "Closed"),
    "leak": (lambda d, _: _flag(d.get("input_05")), "Leak since {t}", "Dry"),
    "input": (lambda d, _: _flag(d.get("input_05")), "High since {t}", "Low"),
    "co2high": (lambda d, lim: (d["co2"] >= lim["co2"]) if isinstance(d.get("co2"), (int, float)) else None,
                "Above limit since {t}", "OK"),
    "load": (_load_running, "Running since {t}", "Off"),
    "gas": (lambda d, _: _flag(d.get("gas_alarm")), "Gas detected since {t}", "Clear"),
    "smoke": (lambda d, _: _flag(d.get("smoke_alarm")), "Smoke detected since {t}", "Clear"),
    "vape": (lambda d, _: _flag(d.get("vaping_index_alarm_active")), "Vaping detected since {t}", "Clear"),
}
# alarm-style features: the state is latched in the stored values (devices only report changes)
LATCHED_FEATURES = {"vape", "smoke"}


# VS373 alarm type -> flag key in values
ALARM_FLAGS = {
    "fall": "alarm_fall", "motionless": "alarm_motionless", "out_of_bed": "alarm_out_of_bed",
    "dwell": "alarm_dwell", "lying_down": "alarm_lying_down",
    "bradynea": "alarm_breathing", "tachypnea": "alarm_breathing",
}


def _co2_text(co2: Any) -> str | None:
    if not isinstance(co2, (int, float)):
        return None
    if co2 < 800:
        return "Good"
    if co2 < 1200:
        return "Moderate"
    return "Poor"
def _odour_text(nh3: Any, h2s: Any) -> str | None:
    """Rough odour rating. Typical perception thresholds: NH3 ~ 1-5 ppm, H2S ~ 0.01-0.1 ppm."""
    if not isinstance(nh3, (int, float)) and not isinstance(h2s, (int, float)):
        return None
    nh3 = nh3 if isinstance(nh3, (int, float)) else 0
    h2s = h2s if isinstance(h2s, (int, float)) else 0
    if nh3 >= 5 or h2s >= 0.1:
        return "Strong"
    if nh3 >= 1 or h2s >= 0.02:
        return "Noticeable"
    return "Fresh"


MAX_CLOCK_SKEW_S = 600


def _heat_index(t: float, h: float) -> float:
    if t < 27 or h < 40:
        return t
    hi = (-8.784695 + 1.61139411 * t + 2.338549 * h - 0.14611605 * t * h
          - 0.012308094 * t * t - 0.016424828 * h * h + 0.002211732 * t * t * h
          + 0.00072546 * t * h * h - 0.000003582 * t * t * h * h)
    return round(hi, 1)


class DeviceRuntime:
    """Holds all state for one LoRaWAN device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.deveui: str = entry.data[CONF_DEVEUI]
        self.model: Model = MODELS[entry.options.get(CONF_MODEL, entry.data[CONF_MODEL])]
        self.cal = Calendar(dt_util.get_time_zone(hass.config.time_zone) or dt_util.UTC)
        self.store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{self.deveui}")
        self.raw: dict[str, Any] = {}
        self.meta: dict[str, Any] = {}
        self.values: dict[str, Any] = {}
        self.binary: dict[str, BinaryEventTracker] = {}
        self.minmax: MinMaxTracker | None = None
        self.occupancy: OccupancyTracker | None = None
        self._unsubs: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ setup
    def _opt(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.raw = data.get("raw", {})
        self.meta = data.get("meta", {})
        trackers = data.get("trackers", {})
        f = self.model.features
        max_gap_s = float(self._opt(CONF_MAX_GAP_MIN, DEFAULT_MAX_GAP_MIN)) * 60

        for feature in BINARY_FEATURES:
            if feature in f:
                self.binary[feature] = BinaryEventTracker(
                    self.cal, trackers.get(feature), max_gap_s=max_gap_s,
                    left_open_s=float(self._opt(CONF_LEFT_OPEN_MIN, DEFAULT_LEFT_OPEN_MIN)) * 60,
                )
        self.limits = {"co2": float(self._opt(CONF_CO2_LIMIT, DEFAULT_CO2_LIMIT)),
                       "run_a": float(self._opt(CONF_RUN_THRESHOLD_A, DEFAULT_RUN_THRESHOLD_A))}
        if self.model.minmax_fields:
            self.minmax = MinMaxTracker(self.cal, trackers.get("minmax"))
        if "occupancy" in f:
            days = self._opt(CONF_OPEN_DAYS, DEFAULT_OPEN_DAYS)
            self.occupancy = OccupancyTracker(
                self.cal, trackers.get("occupancy"),
                grace_s=float(self._opt(CONF_EMPTY_GRACE_MIN, DEFAULT_EMPTY_GRACE_MIN)) * 60,
                max_gap_s=max_gap_s,
                open_hour=int(self._opt(CONF_OPEN_HOUR, DEFAULT_OPEN_HOUR)),
                close_hour=int(self._opt(CONF_CLOSE_HOUR, DEFAULT_CLOSE_HOUR)),
                open_days=tuple(WEEKDAYS.index(d) for d in days if d in WEEKDAYS),
            )

    @callback
    def async_start(self) -> None:
        self._unsubs.append(async_dispatcher_connect(
            self.hass, SIGNAL_UPLINK.format(self.deveui), self.handle_uplink))
        self._unsubs.append(async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=TICK_SECONDS)))

        # Use the uplink that triggered discovery so values appear immediately.
        cached = None
        for hub in self.hass.data.get(DOMAIN, {}).get("hubs", {}).values():
            cached = hub.last_uplink.get(self.deveui) or cached
        if cached and (self.meta.get("last_seen") or 0) < self._uplink_ts(cached) - 1:
            self.handle_uplink(cached)
        else:
            self._tick(None)

    async def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        await self.store.async_save(self._data_to_save())

    # ---------------------------------------------------------------- uplinks
    @staticmethod
    def _uplink_ts(up: Uplink) -> float:
        now = time.time()
        if up.time is not None:
            ts = up.time.timestamp()
            if abs(ts - now) <= MAX_CLOCK_SKEW_S:
                return ts
        return now

    @callback
    def handle_uplink(self, up: Uplink) -> None:
        try:
            decoded = self.model.decoder(up.raw) if up.raw else (up.predecoded or {})
        except Exception:  # noqa: BLE001 - never let one bad payload break the device
            _LOGGER.exception("Failed to decode uplink from %s", self.deveui)
            return
        ts = self._uplink_ts(up)
        for k, v in self.model.defaults:
            self.raw.setdefault(k, v)
        self.raw.update({k: v for k, v in decoded.items() if k not in ("history", "events")})
        if "vs373" in self.model.features:
            self._handle_vs373(decoded, ts)
        self.meta.update({"rssi": up.rssi, "snr": up.snr, "last_seen": ts})

        for feature, tracker in self.binary.items():
            src = self.raw if feature in LATCHED_FEATURES else decoded
            tracker.update(ts, BINARY_FEATURES[feature][0](src, self.limits))
        if self.minmax is not None:
            self.minmax.update(ts, {k: decoded[k] for k in self.model.minmax_fields if k in decoded})
        if self.occupancy is not None and self.model.occupancy_fn is not None:
            count = self.model.occupancy_fn(decoded)
            if count is not None:
                self.occupancy.update(ts, count)

        self._publish(ts)

    def _handle_vs373(self, decoded: dict[str, Any], ts: float) -> None:
        """Keep alarm flags until the device reports them deactivated, and fire HA events."""
        for f in ALARM_FLAGS.values():
            self.raw.setdefault(f, False)
        if decoded.get("detection_status") == "fall":
            self.raw["alarm_fall"] = True
        for ev in decoded.get("events", []):
            atype, status = ev.get("alarm_type"), ev.get("alarm_status")
            flag = ALARM_FLAGS.get(atype)
            if flag and status in ("alarm_triggered", "alarm_deactivated", "alarm_ignored"):
                self.raw[flag] = status == "alarm_triggered"
            if status == "alarm_triggered":
                self.raw["last_alarm"] = "bradypnea" if atype == "bradynea" else atype
                self.raw["last_alarm_at"] = ts
            self.hass.bus.async_fire(f"{DOMAIN}_alarm", {
                "deveui": self.deveui, "device": self.entry.title, "model": self.model.key,
                "alarm_type": atype, "alarm_status": status, "region_id": ev.get("region_id"),
            })

    @callback
    def _tick(self, _now: datetime | None) -> None:
        ts = time.time()
        for tracker in self.binary.values():
            tracker.tick(ts)
        if self.occupancy is not None:
            self.occupancy.tick(ts)
        self._publish(ts)

    # ---------------------------------------------------------------- values
    def _hhmm(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, self.cal.tz).strftime("%H:%M")

    def _publish(self, ts: float) -> None:
        v: dict[str, Any] = dict(self.raw)
        v.update(self.meta)

        if self.minmax is not None:
            for f in self.model.minmax_fields:
                v[f"{f}_min_today"] = self.minmax.get(ts, "min", f)
                v[f"{f}_max_today"] = self.minmax.get(ts, "max", f)
        if isinstance(v.get("temperature"), (int, float)) and isinstance(v.get("humidity"), (int, float)):
            v["feels_like"] = _heat_index(v["temperature"], v["humidity"])
        if "co2" in v:
            v["co2_status"] = _co2_text(v["co2"])
        height = float(self._opt(CONF_INSTALL_HEIGHT_MM, 0) or 0)
        if "em400" in self.model.features and height > 0 and isinstance(v.get("distance"), (int, float)):
            # distance = sensor to surface; full when the surface reaches the sensor
            v["fill_level"] = round(max(0.0, min(100.0, (height - v["distance"]) / height * 100)), 0)

        if "ct" in self.model.features:
            self._ct_values(v)
        if isinstance(v.get("life_remain"), (int, float)):
            v["life_remain_days"] = round(v["life_remain"] / 86400)
        if isinstance(v.get("pm_sensor_working_time"), (int, float)):
            v["pm_sensor_working_time"] = round(v["pm_sensor_working_time"] / 3600, 1)
        if "gs301" in self.model.features:
            v["odour_level"] = _odour_text(v.get("nh3"), v.get("h2s"))

        for feature, tracker in self.binary.items():
            tv = tracker.values(ts)
            for k, val in tv.items():
                v[f"{feature}_{k}"] = val
            _, on_text, off_text = BINARY_FEATURES[feature]
            if tv["active"] is True:
                v[f"{feature}_status"] = on_text.format(t=self._hhmm(tv["since"])) if tv["since"] else on_text.split(" since")[0]
            elif tv["active"] is False:
                v[f"{feature}_status"] = off_text
            else:
                v[f"{feature}_status"] = "Waiting for data"

        if self.occupancy is not None:
            ov = self.occupancy.values(ts)
            for k, val in ov.items():
                v[f"occ_{k}"] = val
            if ov["occupied"]:
                if ov["vacancy_pending"]:
                    v["occ_status"] = f"Occupied since {self._hhmm(ov['occupied_since'])} (checking if empty)"
                else:
                    n = ov["people_count"]
                    since = f"Occupied since {self._hhmm(ov['occupied_since'])}"
                    v["occ_status"] = (f"{since} ({n} {'person' if n == 1 else 'people'})"
                                       if self.model.counting else since)
            else:
                v["occ_status"] = "Empty" if self.meta.get("last_seen") else "Waiting for data"

        self.values = v
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.deveui))
        self.store.async_delay_save(self._data_to_save, 30)

    def _ct_values(self, v: dict[str, Any]) -> None:
        volts = float(self._opt(CONF_MAINS_VOLTAGE, 0) or 0)
        chans = [k for k in CT_CURRENT_KEYS if isinstance(v.get(k), (int, float))]
        if "ct3" in self.model.features:
            chans = [k for k in chans if k != "current"]
            if chans:
                v["current_total"] = round(sum(v[k] for k in chans), 2)
        if volts > 0:
            for k in chans:
                v[k.replace("current", "apparent_power")] = round(v[k] * volts)
            if "current_total" in v:
                v["apparent_power"] = round(v["current_total"] * volts)

    def _data_to_save(self) -> dict[str, Any]:
        trackers: dict[str, Any] = {k: t.s for k, t in self.binary.items()}
        if self.minmax is not None:
            trackers["minmax"] = self.minmax.s
        if self.occupancy is not None:
            trackers["occupancy"] = self.occupancy.s
        return {"raw": self.raw, "meta": self.meta, "trackers": trackers}

    def diagnostics(self) -> dict[str, Any]:
        return {"model": self.model.key, "values": self.values, "state": self._data_to_save()}
