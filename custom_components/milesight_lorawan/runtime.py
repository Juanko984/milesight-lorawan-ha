"""Per-device runtime: decodes uplinks, runs analytics, persists state."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .analytics import BinaryEventTracker, Calendar, CounterTracker, DistanceTracker, MinMaxTracker, OccupancyTracker
from .const import (
    CONF_BATTERY_LOW,
    CONF_CHANNEL_MAP,
    CONF_CONFIRMED_DOWNLINKS,
    CONF_DISPLAY_MAX_BYTES,
    CONF_RETRIES,
    DEFAULT_DISPLAY_MAX_BYTES,
    DEFAULT_RETRIES,
    SIGNAL_NOTIFY,
    SIGNAL_ALERTS,
    CONF_METER_OFFSET,
    CONF_METER_PPU,
    CONF_METER_SOURCE,
    CONF_METER_TYPE,
    CONF_METER_UNIT,
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
    CONF_OFFLINE_AUTO,
    CONF_OFFLINE_FACTOR,
    CONF_OPEN_DAYS,
    CONF_OPEN_HOUR,
    DEFAULT_BATTERY_LOW,
    DEFAULT_CLOSE_HOUR,
    DEFAULT_CO2_LIMIT,
    DEFAULT_EMPTY_GRACE_MIN,
    DEFAULT_LEFT_OPEN_MIN,
    DEFAULT_MAX_GAP_MIN,
    DEFAULT_OFFLINE_AUTO,
    DEFAULT_OFFLINE_FACTOR,
    DEFAULT_OPEN_DAYS,
    DEFAULT_OPEN_HOUR,
    OFFLINE_CEIL_S,
    OFFLINE_FLOOR_S,
    OFFLINE_GAP_WINDOW,
    OFFLINE_MIN_SAMPLES,
    DEFAULT_RUN_THRESHOLD_A,
    DOMAIN,
    SIGNAL_EVENT,
    SIGNAL_FLEET,
    SIGNAL_UPDATE,
    SIGNAL_UPLINK,
    STORAGE_VERSION,
    TICK_SECONDS,
    WEEKDAYS,
)
from . import decoders as _decoders
from .decoders import (Uplink, ds3604_frames, encode_ds3604, encode_ds3604_content, encode_fields, encode_template,
                       encode_wt, encode_ws_switch)
from .link import LinkStats, PendingCommands, link_advice, link_margin, link_quality
from .alerts import device_alerts
from .channel_map import parse_channel_map, compass_point as _compass_point
from .models import (MODELS, Model, channel_specs, downlinks, entity_specs, meter_spec, output_for_key, pivot_specs,
                     pump_capable, pump_specs, setting_spec, tank_source, tank_specs)
from .pivot import PivotTracker, pivot_config
from . import purposes as _purposes
from .models import contact_specs, families, load_channels, load_specs, purpose_specs, temp_specs
from .usage import LoadTracker, TempWatch, Trend, bin_fill, water_level_cm
from . import setpoints as _setpoints
from .pump import PumpTracker, energy_from_ah, power_factor, pump_config, run_threshold
from .tank import TankTracker, level_mm, tank_config, volume_l

_LOGGER = logging.getLogger(__name__)

# decoded keys that are not device state (lists / nested structures handled separately)
_NOT_RAW = ("history", "events", "wifi", "button_events", "template_1", "template_2", "update_content_result",
            "modbus_channels_set", "modbus_channels_named", "modbus_channels_removed")
DS3604_BLOCKS = tuple(f"text_{n}" for n in range(1, 11)) + ("qrcode",)

def _flag(v: Any) -> bool | None:
    return None if v is None else bool(v)


CT_CURRENT_KEYS = ("current", "current_1", "current_2", "current_3")


def _hvac_running(d: dict, what: str) -> bool | None:
    """Thermostats: heating / cooling from the reported control status; radiator valves: valve open."""
    if d.get("system_status") is False:
        return False
    status = d.get("temperature_control_status")
    if isinstance(status, str):
        return what in status
    if what == "heat" and isinstance(d.get("valve_opening"), (int, float)):
        return d["valve_opening"] > 0
    return None


def _load_running(d: dict, lim: dict) -> bool | None:
    """CT range: the load counts as running while any channel is at or above the threshold."""
    amps = [d[k] for k in CT_CURRENT_KEYS if isinstance(d.get(k), (int, float))]
    return any(a >= lim["run_a"] for a in amps) if amps else None


# feature -> (extract(decoded, limits) -> bool | None, status text on, status text off)
BINARY_FEATURES: dict[str, tuple[Callable[[dict, dict], bool | None], str, str]] = {
    "door": (lambda d, _: _flag(d.get("magnet_status")), "Open since {t}", "Closed"),
    "leak": (lambda d, _: _flag(d.get("leak", d.get("input_05"))), "Leak since {t}", "Dry"),
    "input": (lambda d, _: _flag(d.get("input_05")), "High since {t}", "Low"),
    "co2high": (lambda d, lim: (d["co2"] >= lim["co2"]) if isinstance(d.get("co2"), (int, float)) else None,
                "Above limit since {t}", "OK"),
    "load": (_load_running, "Running since {t}", "Off"),
    "gas": (lambda d, _: _flag(d.get("gas_alarm")), "Gas detected since {t}", "Clear"),
    "smoke": (lambda d, _: _flag(d.get("smoke_alarm")), "Smoke detected since {t}", "Clear"),
    "moving": (lambda d, _: {"start": True, "moving": True, "stop": False}.get(d.get("motion_status")),
               "Moving since {t}", "Stopped"),
    "away": (lambda d, _: {"outside": True, "inside": False}.get(d.get("geofence_status")),
                 "Outside since {t}", "Inside"),
    "motion": (lambda d, _: _flag(d.get("pir")), "Motion since {t}", "Clear"),
    "heating": (lambda d, _: _hvac_running(d, "heat"), "Heating since {t}", "Idle"),
    "cooling": (lambda d, _: _hvac_running(d, "cool"), "Cooling since {t}", "Idle"),
    "on": (lambda d, _: _flag(d.get("switch_1")), "On since {t}", "Off"),
    "vape": (lambda d, _: _flag(d.get("vaping_index_alarm_active")), "Vaping detected since {t}", "Clear"),
}
# alarm-style features: the state is latched in the stored values (devices only report changes)
LATCHED_FEATURES = {"vape", "smoke", "on", "heating", "cooling"}


# VS373 alarm type -> flag key in values
ALARM_FLAGS = {
    "fall": "alarm_fall", "motionless": "alarm_motionless", "out_of_bed": "alarm_out_of_bed",
    "dwell": "alarm_dwell", "lying_down": "alarm_lying_down",
    "bradynea": "alarm_breathing", "tachypnea": "alarm_breathing",
}


def _nz(v: Any) -> float | None:
    """A number or None (ignores booleans and non-numeric values)."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _dur(seconds: float | None) -> str | None:
    """A compact, human duration: '45 s', '20 min', '1 h 30 min', '2 h'."""
    if not seconds or seconds <= 0:
        return None
    s = int(round(seconds))
    if s < 90:
        return f"{s} s"
    m = int(round(s / 60))
    if m < 90:
        return f"{m} min"
    h, rem = divmod(m, 60)
    return f"{h} h {rem} min" if rem else f"{h} h"


def _co2_text(co2: Any) -> str | None:
    if not isinstance(co2, (int, float)):
        return None
    if co2 < 800:
        return "Good"
    if co2 < 1200:
        return "Moderate"
    return "Poor"


# The properties an AM air-quality monitor can show, in the order they appear on the card. Each: the value key,
# label, unit, mdi icon, trend-line colour, and sensible default high / low limits (so a chip flags red / amber
# and the trend draws a threshold line even before a purpose sets one). CO₂'s high limit comes from the device.
_AIR_METRICS = (
    ("co2",         "CO₂",         "ppm",    "mdi:molecule-co2",   "#4aa3ff", None,  None),
    ("temperature", "Temperature", "°C",     "mdi:thermometer",    "#ff8a5c", None,  None),
    ("humidity",    "Humidity",    "%",      "mdi:water-percent",  "#4ab0c4", None,  None),
    ("pm2_5",       "PM2.5",       "µg/m³",  "mdi:blur",           "#c98a2b", 35.0,  None),
    ("pm10",        "PM10",        "µg/m³",  "mdi:blur-linear",    "#b2762a", 50.0,  None),
    ("tvoc_iaq",    "TVOC index",  "",       "mdi:air-filter",     "#8e7cc3", 3.0,   None),
    ("hcho",        "HCHO",        "mg/m³",  "mdi:flask-outline",  "#db4437", 0.1,   None),
    ("o3",          "Ozone",       "ppm",    "mdi:weather-hazy",   "#80cbc4", 0.1,   None),
    ("pressure",    "Pressure",    "hPa",    "mdi:gauge",          "#6fae6f", None,  None),
    ("light_level", "Light",       "",       "mdi:brightness-6",   "#ffca28", None,  None),
)
_AIR_FEATURES = frozenset({"co2", "tvoc", "pm", "pm25_only", "hcho", "o3", "pressure"})

# The Environment card (EM300-TH/MCS/SLD, EM320-TH, TS201/301/302, WS202/203, AM102/104 …): numeric properties
# that drive a trend when clicked, and binary states (door / leak / motion) shown as status chips.
_ENV_NUM = (   # key, label, unit, icon, trend colour
    ("temperature",   "Temperature",    "°C", "mdi:thermometer",   "#ff8a5c"),
    ("temperature_1", "Temp (probe 1)", "°C", "mdi:thermometer",   "#ff8a5c"),
    ("temperature_2", "Temp (probe 2)", "°C", "mdi:thermometer",   "#ffb07c"),
    ("humidity",      "Humidity",       "%",  "mdi:water-percent", "#4ab0c4"),
    ("light_level",   "Light",          "",   "mdi:brightness-6",  "#ffca28"),
    ("illumination",  "Light",          "lx", "mdi:brightness-6",  "#ffca28"),
)
_ENV_BIN = (   # feature, label, icon, on-text, off-text, tone when on
    ("door",   "Door",   "mdi:door",         "Open",   "Closed", "warning"),
    ("leak",   "Leak",   "mdi:water-alert",  "Leak",   "Dry",    "critical"),
    ("motion", "Motion", "mdi:motion-sensor", "Motion", "Clear",  "warning"),
)
# Device families that have their own cards (or aren't environmental) and so never show an Environment card.
_ENV_SKIP_PREFIX = ("UC", "VS", "GS", "CT", "DS", "WT", "TS")   # TS probes have their own Temperature-probe card

# GS odour / vape detectors (GS301 NH₃·H₂S, GS601 vape). Numeric chips drive a trend; odour / vape show as states.
_GAS_NUM = (   # key, label, unit, icon, colour
    ("vaping_index", "Vaping index", "",       "mdi:smoking-off",   "#db4437"),
    ("nh3",          "NH₃",          "ppm",    "mdi:scent",         "#8e7cc3"),
    ("h2s",          "H₂S",          "ppm",    "mdi:scent",         "#b2762a"),
    ("pm2_5",        "PM2.5",        "µg/m³",  "mdi:blur",          "#c98a2b"),
    ("tvoc",         "TVOC",         "µg/m³",  "mdi:air-filter",    "#8e7cc3"),
    ("temperature",  "Temperature",  "°C",     "mdi:thermometer",   "#ff8a5c"),
    ("humidity",     "Humidity",     "%",      "mdi:water-percent", "#4ab0c4"),
)


# UC I/O controllers (digital in/out, PT100, analog, counters, RS485) and UC valve controllers.
_UC_CONTROLLER = ("UC300", "UC501", "UC502", "UC11XX", "UC11-N1")
_UC_VALVE = ("UC511", "UC512", "UC521")
# EM500 single-reading sensors → the adaptive reading card. key, label, unit, icon, colour, kind (gauge | level).
_EM_READING = {
    "EM500-LGT":   ("illumination", "Light",         "lx",  "mdi:brightness-6",         "#ffca28", "gauge"),
    "EM500-PP":    ("pressure_kpa", "Pipe pressure", "kPa", "mdi:gauge",                "#4aa3ff", "gauge"),
    "EM500-PT100": ("temperature",  "Temperature",   "°C",  "mdi:thermometer",          "#ff8a5c", "gauge"),
    "EM500-UDL":   ("distance",     "Distance",      "mm",  "mdi:arrow-expand-vertical", "#6cb6d6", "level"),
    "EM500-SWL":   ("depth",        "Water level",   "cm",  "mdi:waves-arrow-up",        "#6cb6d6", "level"),
}
# RS485 Modbus templates → a friendly purpose label + icon for the controller card's "attached" strip.
_UC_RS485 = {
    "cwt_soil_thcph":   ("Soil probe",      "mdi:sprout",              "#36c08a"),
    "womaster_ws101ll": ("Liquid level",    "mdi:cup-water",           "#ffca28"),
    "ecowitt_ws90":     ("Weather station", "mdi:weather-partly-cloudy", "#4aa3ff"),
    "witmotion_wtvb01": ("Vibration",       "mdi:vibrate",             "#db4437"),
}


# WS scene buttons / panels: friendly labels for each press type and button key.
_EVENT_LABEL = {"short_press": "Short press", "double_press": "Double press", "long_press": "Long press",
                "press": "Press", "single_click": "Single click", "double_click": "Double click"}


def _button_label(key: str) -> str:
    m = re.fullmatch(r"button_(\d+)", key)
    if m:
        return f"Button {m[1]}"
    m = re.fullmatch(r"key_f(\d+)", key)
    if m:
        return f"F{m[1]}"
    return "Button"


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


def _spec_after_hours():
    from .models import EntitySpec
    return EntitySpec("after_hours_activity", "After-hours activity", platform="binary_sensor",
                      device_class="problem", icon="mdi:weather-night")


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
        self.distance: DistanceTracker | None = None
        self.counters: CounterTracker | None = None
        self.commands = PendingCommands()
        self.link = LinkStats()
        self.display: dict[str, Any] = {}           # DS3604: {"sent": {tpl: {block: text}}, "reported": {...}}
        self.attrs: dict[str, dict[str, Any]] = {}  # extra state attributes per entity key
        self.tank_src = tank_source(self.model.key)
        self.tank_cfg = tank_config(dict(entry.options)) if self.tank_src else None
        self.tank: TankTracker | None = None
        self.pump: PumpTracker | None = None
        self.pump_cfg = None
        self.pivot: PivotTracker | None = None
        self.pivot_cfg = pivot_config(dict(entry.options)) if "at101" in self.model.features else None
        opts = {**entry.data, **entry.options}
        self.families = families(self.model.key)
        p = _purposes.get(opts.get("purpose"))
        self.purpose = p if p is not None and p.families & self.families else None
        self.pcfg: dict[str, Any] = _purposes.settings(self.purpose.key if self.purpose else None, dict(entry.options))
        self.loads: dict[str, tuple[LoadTracker, dict, str | None, Any]] = {}  # prefix -> (tracker, cfg, purpose, channel)
        self.tempw: TempWatch | None = None
        self.trend: Trend | None = None
        self.channels, self.channel_errors = (parse_channel_map(entry.options.get(CONF_CHANNEL_MAP, ""))
                                              if self.model.dynamic else ({}, []))
        self._alert_sig: Any = None
        self._unsubs: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ setup
    def _opt(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    # ---------------------------------------------------- offline / reporting cadence
    def _learn_interval(self, prev_seen: float | None, ts: float) -> None:
        """Keep a rolling window of the gaps between uplinks, so the device's real reporting cadence
        can be measured (Milesight sensors never send their configured interval in the payload)."""
        if not prev_seen:
            return
        gap = ts - prev_seen
        # drop bursts / near-duplicates (< 20 s) and anything over a day (a real outage, not the cadence);
        # the median shrugs off the occasional outlier that slips through.
        if 20 <= gap <= OFFLINE_CEIL_S:
            gaps = self.meta.setdefault("_gaps", [])
            gaps.append(round(gap))
            if len(gaps) > OFFLINE_GAP_WINDOW:
                del gaps[:-OFFLINE_GAP_WINDOW]

    def _report_interval_s(self) -> tuple[float | None, str]:
        """The device's reporting interval in seconds, and where it came from: the measured median once
        enough uplinks are in, else the interval we commanded, else Milesight's factory default."""
        import statistics
        gaps = self.meta.get("_gaps") or []
        if len(gaps) >= OFFLINE_MIN_SAMPLES:
            return float(statistics.median(gaps)), "measured"
        spec = downlinks(self.model.key).get("report_interval") or {}
        unit_s = 60 if spec.get("unit") == "min" else 1
        commanded = self.meta.get("config", {}).get("report_interval")
        if commanded:
            return float(commanded) * unit_s, "configured"
        if spec:
            from .commissioning import default_interval
            return float(default_interval(spec.get("unit", "s"))) * unit_s, "default"
        return None, "none"

    def _offline_threshold_s(self) -> tuple[float, float | None, str]:
        """(offline_after_s, interval_s, source). Auto = factor × reporting interval, clamped to a sane
        band; otherwise the manual 'offline time' (max_gap) the user set."""
        interval, source = self._report_interval_s()
        if not self._offline_auto or interval is None:
            return self.max_gap_s, interval, ("manual" if not self._offline_auto else source)
        return min(OFFLINE_CEIL_S, max(OFFLINE_FLOOR_S, self._offline_factor * interval)), interval, source

    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.raw = data.get("raw", {})
        self.meta = data.get("meta", {})
        self.commands = PendingCommands(data["commands"]) if "commands" in data else PendingCommands.from_meta(self.meta)
        self.link = LinkStats(data.get("link"))
        self.display = data.get("display", {})
        trackers = data.get("trackers", {})
        from .battery import BatteryForecast
        self.battery_fc = BatteryForecast(trackers.get("battery_fc"))
        f = self.model.features
        max_gap_s = float(self._opt(CONF_MAX_GAP_MIN, DEFAULT_MAX_GAP_MIN)) * 60
        self.max_gap_s = max_gap_s
        # Offline detection derives its own timeout from the device's reporting cadence (auto), falling back
        # to the manual "offline time" (max_gap) when auto is off or the cadence isn't known yet.
        self._offline_auto = bool(self._opt(CONF_OFFLINE_AUTO, DEFAULT_OFFLINE_AUTO))
        self._offline_factor = max(2, int(self._opt(CONF_OFFLINE_FACTOR, DEFAULT_OFFLINE_FACTOR)))
        self.battery_low_pct = float(self._opt(CONF_BATTERY_LOW, DEFAULT_BATTERY_LOW))
        self._fleet_state: tuple | None = None

        left_open = self.pcfg.get("left_open_min") if "contact" in self._pfam else None
        for feature in BINARY_FEATURES:
            if feature in f or (feature == "door" and "ts_contact" in f and "contact" in self._pfam):
                self.binary[feature] = BinaryEventTracker(
                    self.cal, trackers.get(feature), max_gap_s=max_gap_s,
                    left_open_s=float(left_open if left_open is not None
                                      else self._opt(CONF_LEFT_OPEN_MIN, DEFAULT_LEFT_OPEN_MIN)) * 60,
                )
        self.limits = {"co2": float(self.pcfg.get("co2_limit") or self._opt(CONF_CO2_LIMIT, DEFAULT_CO2_LIMIT)),
                       "run_a": run_threshold(dict(self.entry.options))}
        if self.model.minmax_fields:
            self.minmax = MinMaxTracker(self.cal, trackers.get("minmax"))
        if self.tank_cfg is not None and self.tank_cfg.enabled:
            self.tank = TankTracker(trackers.get("tank"))
            self.tank.check_config(self.tank_cfg)
        else:
            self.tank_cfg = None
        if "at101" in f:
            self.distance = DistanceTracker(self.cal, trackers.get("distance"))
        self._load_purposes(trackers)
        if pump_capable(self.model.key):
            cfg = pump_config(dict(self.entry.options), self.limits["run_a"])
            if self._pkey == "pump" and not cfg.enabled:
                from dataclasses import replace
                cfg = replace(cfg, enabled=True)
            if cfg.enabled:
                self.pump_cfg, self.pump = cfg, PumpTracker(trackers.get("pump"))
        if self.pivot_cfg is not None and self.pivot_cfg.enabled:
            st = trackers.get("pivot")
            if st and st.get("centre") != [self.pivot_cfg.lat, self.pivot_cfg.lon]:
                st = None                                   # centre moved: start again
            self.pivot = PivotTracker(st)
        else:
            self.pivot_cfg = None
        if self.model.counters:
            self.counters = CounterTracker(self.cal, self.model.counters, trackers.get("counters"))
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
        self._unsubs.append(async_dispatcher_connect(
            self.hass, SIGNAL_NOTIFY.format(self.deveui), self.handle_notification))
        self._unsubs.append(async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=TICK_SECONDS)))

        # Use the uplink that triggered discovery so values appear immediately.
        cached = None
        for hub in self.hass.data.get(DOMAIN, {}).get("hubs", {}).values():
            cached = hub.last_uplink.get(self.deveui) or cached
        if self.meta.get("walk_test"):
            self._schedule_walk_end(60)         # a walk test was running when Home Assistant stopped: give MQTT a minute
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
        ts = self._uplink_ts(up)
        if self.link.is_duplicate(up.fcnt, ts):          # same frame via a second gateway / server
            self.link.update(self._day(ts), ts, None, up.gateways)
            self._publish(ts)
            return
        try:
            decoded = self.model.decoder(up.raw) if up.raw else (up.predecoded or {})
        except Exception:  # noqa: BLE001 - never let one bad payload break the device
            _LOGGER.exception("Failed to decode uplink from %s", self.deveui)
            return
        self.link.update(self._day(ts), ts, up.fcnt, up.gateways)
        # for Download diagnostics: what the device really sent (keys starting with _ are not entities)
        self.meta["_last_payload"] = up.raw.hex() if up.raw else None
        self.meta["_last_fport"] = up.fport
        if up.sf is not None:
            self.meta["spreading_factor"] = up.sf
        if up.frequency is not None:
            self.meta["frequency"] = round(up.frequency / 1e6, 3)
        if up.fcnt is not None:
            self.meta["frame_counter"] = up.fcnt
        ns = up.extra.get("network_server")
        if ns and ns != self.meta.get("network_server"):
            self.meta["network_server"] = ns
            self._network_changed()
        self._handle_display(decoded)
        prev_seen = self.meta.get("last_seen")
        self._learn_interval(prev_seen, ts)
        if up.raw:
            self._handle_history(up.raw)
        if prev_seen and ts - prev_seen > self.max_gap_s and self._opt("auto_backfill", True):
            self.hass.async_create_task(self._safe_fetch(prev_seen, ts))
        for k, v in self.model.defaults:
            self.raw.setdefault(k, v)
        self.raw.update({k: v for k, v in decoded.items() if k not in _NOT_RAW})
        for key, event_type in decoded.get("button_events", []):
            self._fire_button(key, event_type)
        if "vs373" in self.model.features:
            self._handle_vs373(decoded, ts)
        self.meta.update({"rssi": up.rssi, "snr": up.snr, "last_seen": ts})
        self._battery_reading(ts, decoded)
        self._check_commands(up.raw.hex() if up.raw else "", decoded, ts)
        self._update_registry()

        for feature, tracker in self.binary.items():
            src = self.raw if feature in LATCHED_FEATURES else decoded
            tracker.update(ts, BINARY_FEATURES[feature][0](src, self.limits))
        if self.counters is not None:
            self.counters.update(ts, decoded)
        if self.tank is not None:
            self._tank_reading(ts, decoded)
        if self.loads or self.tempw is not None or self.purpose is not None:
            self._purpose_reading(ts, decoded)
        if self.distance is not None and "latitude" in decoded:
            self.distance.update(ts, decoded.get("latitude"), decoded.get("longitude"))
        if self.pivot is not None and "latitude" in decoded:
            self._pivot_events(self.pivot.update(self.pivot_cfg, ts, decoded.get("latitude"),
                                                 decoded.get("longitude")))
        if self.pump is not None:
            amps = self._pump_amps(decoded)
            if amps is not None or self._pump_energy(decoded) is not None:
                for ev in self.pump.update(self.pump_cfg, ts, amps, self._day(ts), self._pump_energy(self.raw),
                                           self._pump_water()):
                    self.hass.bus.async_fire(f"{DOMAIN}_pump", {"deveui": self.deveui, "device": self.entry.title,
                                                               "area": self.entry.data.get("area"), **ev})
        if self.minmax is not None:
            self.minmax.update(ts, {k: decoded[k] for k in self.model.minmax_fields if k in decoded})
        if self.occupancy is not None and self.model.occupancy_fn is not None:
            count = self.model.occupancy_fn(decoded)
            if count is not None:
                self.occupancy.update(ts, count)

        self._publish(ts)

    # ----------------------------------------------------------- DS3604
    def _handle_display(self, decoded: dict[str, Any]) -> None:
        if "ds3604" not in self.model.features:
            return
        for t in (1, 2):
            if isinstance(decoded.get(f"template_{t}"), dict):
                self.display.setdefault("reported", {}).setdefault(str(t), {}).update(decoded[f"template_{t}"])
        for r in decoded.get("update_content_result") or []:
            if r.get("result") != "success":
                self.meta["display_error"] = f"{r.get('block_name') or r.get('block_id')}: {r.get('result')}"

    def display_text(self, template: int, block: str) -> str | None:
        """What the display shows (reported by the device) or, failing that, what was last sent."""
        for src in ("reported", "sent"):
            v = self.display.get(src, {}).get(str(template), {}).get(block)
            if v is not None:
                return v
        return None

    async def async_display(self, template: int = 1, blocks: dict[str, str] | None = None, *, show: bool = False,
                            refresh: bool = False, beep: bool = False, only_changed: bool = False) -> int:
        """Send text / QR-code content to a DS3604 (packed into as few downlinks as fit). Returns downlinks sent.
        only_changed: skip blocks that already show this text, and the template switch if it is already shown."""
        if "ds3604" not in self.model.features:
            raise ValueError(f"{self.model.key} has no display")
        blocks = {k: str(v) for k, v in (blocks or {}).items() if v is not None}
        unknown = set(blocks) - set(DS3604_BLOCKS)
        if unknown:
            raise ValueError(f"unknown display block(s): {', '.join(sorted(unknown))}")
        if only_changed:
            blocks = {k: v for k, v in blocks.items() if self.display_text(template, k) != v}
            show = show and self.raw.get("current_template_id") != template
            if not blocks and not show and not refresh and not beep:
                return 0
        frames: list[tuple[bytes, list | None, str]] = []
        for b in DS3604_BLOCKS:
            if b in blocks:
                frames.append((encode_ds3604_content(template, b, str(blocks[b])), [[template, DS3604_BLOCKS.index(b)]],
                               b))
        if show:
            frames.append((encode_ds3604("template", template), None, "template"))
        if refresh:
            frames.append((encode_ds3604("refresh"), None, "refresh"))
        if beep:
            frames.append((encode_ds3604("beep"), None, "beep"))
        if not frames:
            return 0
        limit = int(self._opt(CONF_DISPLAY_MAX_BYTES, DEFAULT_DISPLAY_MAX_BYTES))
        packets = ds3604_frames([f[0] for f in frames], limit)
        # map each packet back to the frames in it, for confirmation tracking
        i = 0
        for n, packet in enumerate(packets, 1):
            size, results, names = 0, [], []
            while i < len(frames) and size + len(frames[i][0]) <= len(packet):
                size += len(frames[i][0])
                results += frames[i][1] or []
                names.append(frames[i][2])
                i += 1
            await self._downlink(packet)
            label = f"display {', '.join(names)}"
            state = {"current_template_id": template} if "template" in names and not results else None
            self._remember(label, packet, None, results=results or None, state=state,
                           echo=False, blocks=[[template, b] for b in names if b in DS3604_BLOCKS])
        sent = self.display.setdefault("sent", {}).setdefault(str(template), {})
        reported = self.display.setdefault("reported", {}).setdefault(str(template), {})
        for b, v in blocks.items():
            sent[b] = v
            reported.pop(b, None)                       # until the display reports again, show what was sent
        if show:
            self.raw["current_template_id"] = template
        self._publish(time.time())
        return len(packets)

    async def async_display_command(self, cmd: str) -> None:
        """refresh | beep | report_display (ask the display to send its current content)."""
        payload = encode_ds3604(cmd)
        await self._downlink(payload)
        self._remember(f"display {cmd.replace('_', ' ')}", payload, None, echo=False)
        self._publish(time.time())

    # ------------------------------------------------------ stored history
    def _handle_history(self, raw: bytes) -> None:
        hist = downlinks(self.model.key).get("history")
        fn = getattr(_decoders, hist["history_fn"], None) if hist else None
        if fn is None:
            return
        try:
            records = fn(raw)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not parse history from %s", self.deveui, exc_info=True)
            return
        if not records:
            return
        self.meta["history_records"] = self.meta.get("history_records", 0) + len(records)
        measures = {s.key: s.unit for s in entity_specs(self.model.key)
                    if s.platform == "sensor" and s.state_class == "measurement"}
        self.hass.async_create_task(self._import_history(records, measures))

    async def _import_history(self, records, measures) -> None:
        from .backfill import async_import
        try:
            added = await async_import(self.hass, self.deveui, records, measures)
        except Exception:  # noqa: BLE001 - never break uplink handling
            _LOGGER.warning("Could not import stored data from %s", self.deveui, exc_info=True)
            return
        self.meta["last_backfill"] = (f"{len(records)} stored records, {added} hour(s) filled "
                                      f"({datetime.now(self.cal.tz).strftime('%d %b %H:%M')})")
        self._publish(time.time())

    def extra_specs(self) -> list:
        """Entities that depend on the device's options (utility meter, tank contents, named controller channels)."""
        specs = []
        mtype = self._meter_type()
        if mtype in ("water", "gas", "energy", "rain"):
            specs.append(meter_spec(mtype, self._opt(CONF_METER_UNIT,
                                                     {"water": "m³", "gas": "m³", "energy": "kWh", "rain": "mm"}[mtype])))
        specs += self.purpose_extra_specs()
        from .models import EntitySpec
        for option in _setpoints.device_values(self):
            sp = _setpoints.DEVICE[option]
            specs.append(EntitySpec(_setpoints.key(option), sp.name, platform="number", unit=sp.unit, icon=sp.icon))
        if self.tank_cfg is not None:
            specs += tank_specs(self.tank_cfg.density > 0, self.tank_cfg.low_pct > 0, self.tank_cfg.drop_pct > 0)
        if self.pump is not None:
            specs += pump_specs(bool(self._opt("pump_water_entity", None)))
        if self.pivot is not None:
            specs += pivot_specs()
        specs += channel_specs(self.channels)
        if self._vibration_applied() is not None:      # a WitMotion WTVB01-485 template → an ISO 10816 verdict sensor
            specs.append(EntitySpec("vibration", "Vibration", unit="mm/s", icon="mdi:vibrate", precision=1))
        if self._weather_applied() is not None:         # an Ecowitt WS90 template → a weather-station sensor
            specs.append(EntitySpec("weather", "Weather", unit="°C", device_class="temperature",
                                    icon="mdi:weather-partly-cloudy", precision=1))
        if self._applied_template("cwt_soil_thcph") is not None:      # a CWT 7-in-1 → a soil sensor
            specs.append(EntitySpec("soil", "Soil", unit="%", icon="mdi:sprout", precision=0))
        if self._applied_template("womaster_ws101ll") is not None:    # a WoMaster WS101LL → a liquid-level sensor
            specs.append(EntitySpec("liquid_level", "Liquid level", unit="mm", device_class="distance", icon="mdi:cup-water"))
        if self._air_applies():      # an AM air-quality monitor → one card with a chip per property + a trend line
            specs.append(EntitySpec("air_monitor", "Air quality", icon="mdi:air-filter"))
        if self._env_applies():      # a multi-property env sensor → an Environment card (temp/humidity/door/leak/motion)
            specs.append(EntitySpec("env_monitor", "Environment", icon="mdi:home-thermometer"))
        if self._energy_applies():   # a CT current-transformer clamp → an Energy card (phase currents + power)
            specs.append(EntitySpec("energy_monitor", "Energy", icon="mdi:flash"))
        if self._gas_applies():      # a GS odour / vape detector → a Gas & vape card
            specs.append(EntitySpec("gas_monitor", "Gas & vape", icon="mdi:scent"))
        if self.occupancy is not None and self.model.key.startswith("VS") and not self._counter_applies() \
                and self.model.key != "VS321":   # VS occupancy (not VS321) → Spaces + per-device Occupancy card
            specs.append(EntitySpec("space", "Space", icon="mdi:seat"))
        if self.model.key == "VS321":    # VS321 room sensor → the AM-style Workplace card
            specs.append(EntitySpec("workplace", "Workplace", icon="mdi:office-building-marker"))
        if self._counter_applies():  # a VS people counter → the People counter card
            specs.append(EntitySpec("people_counter", "People counter", unit="people", icon="mdi:account-group"))
        if "vs373" in self.model.features:   # VS373 radar fall detection → the Fall / safety card
            specs.append(EntitySpec("fall_monitor", "Fall detection", icon="mdi:account-alert"))
        if (getattr(self.model, "gangs", 0) or 0) >= 1 and self.model.control:   # a WS558 / switch → the Light card
            specs.append(EntitySpec("switch_panel", "Switch panel", icon="mdi:light-switch"))
        if "ws302" in self.model.features:   # a WS302 sound sensor → the Sound / water-flow card
            specs.append(EntitySpec("sound_monitor", "Sound", unit="dB", icon="mdi:volume-high", precision=1))
        if self._controller_applies():   # a UC I/O controller → the Controller card (inputs / outputs / analog)
            specs.append(EntitySpec("controller", "Controller", icon="mdi:developer-board"))
        if self._valve_applies():        # a UC valve controller → the Valve card
            specs.append(EntitySpec("valve_controller", "Valves", icon="mdi:pipe-valve"))
        if self._em_reading_applies():   # an EM500 single-reading sensor → the adaptive EM500 reading card
            specs.append(EntitySpec("em_reading", "Reading", icon="mdi:gauge"))
        if self.model.key == "EM500-SMTC":   # native soil probe → the shared Soil card (trimmed to its readings)
            specs.append(EntitySpec("soil", "Soil", unit="%", icon="mdi:sprout", precision=0))
        if self._temp_probe_applies():   # a TS temperature probe → the Temperature-probe card
            specs.append(EntitySpec("temp_probe", "Temperature probe", unit="°C", device_class="temperature",
                                    icon="mdi:thermometer", precision=1))
        if self._scene_applies():        # a WS button / scene panel → the Scene-buttons card
            specs.append(EntitySpec("scene_panel", "Scene panel", kind="text", icon="mdi:gesture-tap-button"))
        if "ds3604" in self.model.features:   # a DS3604 e-ink display → the Display composer card
            specs.append(EntitySpec("display", "Display", icon="mdi:monitor-dashboard"))
        if self._tracker_applies():      # an AT101 GNSS / Wi-Fi tracker → the Asset-tracker card
            specs.append(EntitySpec("asset_tracker", "Asset tracker", kind="text", icon="mdi:map-marker-radius"))
        if self._supplies_applies():     # a WS201 consumables dispenser → the Supplies card
            specs.append(EntitySpec("supplies", "Supplies", kind="text", icon="mdi:paper-roll"))
        if self.fixed_location() is not None:
            specs.append(EntitySpec("fixed_location", "Location", platform="device_tracker", icon="mdi:map-marker"))
        return specs

    def _applied_template(self, key: str) -> dict | None:
        for a in self.entry.options.get("channel_templates", []):
            if a.get("template") == key:
                return a
        return None

    def _template_values(self, applied: dict, v: dict) -> dict:
        """Register key → current channel value for an applied Modbus template.

        The value is scaled the same way its named channel entity is (via the channel map), so the role
        sensors read true units (soil moisture 100 %, not the raw 1000) rather than the raw register. The
        register keys come from the applied record; records written by an older build may not carry them, so
        we fall back to the template's own register order (the channels it would have written, in order)."""
        first = applied.get("first", 1)
        keys = applied.get("keys")
        if not keys:                                        # record from a build before keys were stored
            from . import modbus_templates as _mt
            t = _mt.TEMPLATES.get(applied.get("template"))
            n = (applied.get("last", first) or first) - first + 1
            keys = [r.key for r in t.regs if r.key in t.defaults()][:n] if t is not None else []
        out: dict = {}
        for i, k in enumerate(keys):
            ck = f"modbus_chn_{first + i}"
            raw = v.get(ck)
            ch = self.channels.get(ck)
            out[k] = ch.apply(raw) if (ch is not None and raw is not None) else raw
        return out

    def _vibration_applied(self) -> dict | None:
        """The applied WitMotion WTVB01-485 Modbus template on this controller, if any (has first channel + keys)."""
        return self._applied_template("witmotion_wtvb01")

    def _weather_applied(self) -> dict | None:
        """The applied Ecowitt WS90 Modbus template on this controller, if any."""
        return self._applied_template("ecowitt_ws90")

    def _soil_assess(self, v: dict) -> dict | None:
        """CWT 7-in-1 (THCPH-S) channel values → the soil card's readings, each tagged high / low / ok."""
        applied = self._applied_template("cwt_soil_thcph")
        if applied is None:
            return None
        from . import soil_calc as _sc
        val = self._template_values(applied, v)
        keys = ("moisture", "temperature", "ec", "ph", "nitrogen", "phosphorus", "potassium", "salinity", "tds")
        readings = {k: _nz(val.get(k)) for k in keys}
        st = {k: _sc.status(k, readings[k]) for k in keys if k != "temperature"}
        return {
            "milesight_role": "soil", "device": self.entry.title,
            "area": self.entry.data.get("area") or self.entry.options.get("area"), "model": "THCPH-S",
            **readings, "status": st, "moisture_label": _sc.moisture_label(readings["moisture"]),
            "ph_label": _sc.ph_label(readings["ph"]),
            "severity": {"high": "warning", "low": "warning", "ok": "ok"}[_sc.worst(list(st.values()))],
            "last_seen": self.meta.get("last_seen"),
        }

    def _level_assess(self, v: dict, ts: float) -> dict | None:
        """WoMaster WS101LL channel values → a liquid-level reading (mm, % of range, trend)."""
        applied = self._applied_template("womaster_ws101ll")
        if applied is None:
            return None
        val = self._template_values(applied, v)
        level, full = _nz(val.get("level")), _nz(val.get("full"))
        decimals = _nz(val.get("decimals"))
        scale = 10 ** int(decimals) if decimals else 1          # WS101LL reports the value × 10^decimals
        lvl = level / scale if level is not None else None
        rng = full / scale if full is not None else None
        pct = round(lvl / rng * 100, 1) if lvl is not None and rng else None
        rate = trend = None
        if lvl is not None:
            hist = self.meta.setdefault("_lvl_h", [])
            hist.append([round(ts), round(lvl, 1)])
            while len(hist) > 1 and hist[0][0] < ts - 3600:     # 1-hour window
                del hist[0]
            dt = ts - hist[0][0]
            if dt >= 300:
                rate = round((lvl - hist[0][1]) / (dt / 3600), 1)
                trend = "rising" if rate > 2 else "falling" if rate < -2 else "steady"
        return {
            "milesight_role": "liquid_level", "device": self.entry.title,
            "area": self.entry.data.get("area") or self.entry.options.get("area"), "model": "WS101LL",
            "level_mm": None if lvl is None else round(lvl), "range_mm": None if rng is None else round(rng),
            "pct": pct, "rate_mm_h": rate, "trend": trend or "steady", "last_seen": self.meta.get("last_seen"),
        }

    def _air_applies(self) -> bool:
        """An AM-range air-quality monitor (AM103/107, AM307/308, AM319 …) – not the temp/humidity-only AM102/104."""
        return self.model.key.startswith("AM") and bool(self.model.features & _AIR_FEATURES)

    def _air_monitor(self, v: dict) -> dict | None:
        """The AM device's live properties as one role sensor: a metric per reading, each with its entity id (so the
        card can draw its trend), unit, icon, colour and high/low limit. CO₂ is the headline; the card lets you click
        any metric to drive the trend line."""
        if not self._air_applies():
            return None
        resolve = self._entity_id_resolver()
        metrics = []
        for key, label, unit, icon, colour, hi, lo in _AIR_METRICS:
            val = _nz(v.get(key))
            if val is None:
                continue
            if key == "co2":
                hi = self.limits.get("co2")                 # the device's own CO₂ limit
            status = "high" if (hi is not None and val >= hi) else "low" if (lo is not None and val <= lo) else "ok"
            eid = resolve(key)
            metrics.append({"key": key, "label": label, "unit": unit, "icon": icon, "color": colour,
                            "value": round(val, 3), "entity_id": eid, "status": status,
                            "limit_high": hi, "limit_low": lo})
        if len(metrics) < 2:
            return None
        primary = next((m for m in metrics if m["key"] == "co2"), metrics[0])
        return {
            "milesight_role": "air_monitor", "device": self.entry.title,
            "area": self.entry.data.get("area") or self.entry.options.get("area"), "model": self.model.key,
            "metrics": metrics, "primary": primary["key"], "air_quality": _co2_text(v.get("co2")),
            "last_seen": self.meta.get("last_seen"),
        }

    def _entity_id_resolver(self):
        """A function value-key → this device's HA sensor entity id (for the air / env cards' trends). Resilient:
        returns None for any key when the entity registry isn't available (so a card still shows current values)."""
        try:
            from homeassistant.helpers import entity_registry as er
            reg = er.async_get(self.hass)
        except Exception:  # noqa: BLE001
            reg = None

        def resolve(key: str, domain: str = "sensor"):
            if reg is None:
                return None
            try:
                return reg.async_get_entity_id(domain, DOMAIN, f"{self.deveui}_{key}")
            except Exception:  # noqa: BLE001
                return None
        return resolve

    def _env_props(self) -> set:
        """Which environmental properties this model exposes, from its features / entities (temp, humidity, door,
        leak, motion, light). Used to decide whether it earns an Environment card (needs at least two)."""
        from .models import entity_specs
        f = self.model.features
        keys = {s.key for s in entity_specs(self.model.key)}
        props = set()
        if {"temperature", "temperature_1"} & keys:
            props.add("temp")
        if {"humidity", "humidity_1"} & keys:
            props.add("humidity")
        if f & {"door", "ts_contact"}:
            props.add("door")
        if "leak" in f:
            props.add("leak")
        if (f & {"motion", "pir"}) or self.model.occupancy_fn is not None:
            props.add("motion")
        if {"light_level", "illumination"} & keys or (f & {"am10x_light", "ws202", "light"}):
            props.add("light")
        return props

    def _env_applies(self) -> bool:
        """A multi-property environmental sensor (temp / humidity / door / leak / motion / light) that isn't a UC
        controller, an AM air monitor, a thermostat or a people / odour device – those have their own cards."""
        if self.model.key.startswith(_ENV_SKIP_PREFIX) or self.model.climate or self._air_applies():
            return False
        if self.model.occupancy_fn is not None and self.model.counting:    # a people counter, not an env sensor
            return False
        if len(self._env_props()) < 2:
            return False
        from .models import entity_specs
        keys = {s.key for s in entity_specs(self.model.key)}
        numeric = keys & {"temperature", "temperature_1", "humidity", "humidity_1", "light_level", "illumination"}
        # needs a real reading (a numeric value, or a door / leak contact) – a pure PIR + daylight sensor (WS202),
        # whose only signals are motion and bright/dim, isn't an environment monitor (those are its own binary sensors)
        return bool(numeric) or bool(self._env_props() & {"door", "leak"})

    def _env_monitor(self, v: dict) -> dict | None:
        """The device's live properties as one role sensor: numeric metrics (each with its entity id so the card can
        trend it) plus door / leak / motion status. Temperature is the headline; the card trends whichever you pick."""
        if not self._env_applies():
            return None
        resolve = self._entity_id_resolver()
        metrics, seen = [], set()
        for key, label, unit, icon, colour in _ENV_NUM:
            val = _nz(v.get(key))
            if val is None or label in seen:               # one Light chip, whichever key the model uses
                continue
            seen.add(label)
            eid = resolve(key)
            metrics.append({"key": key, "label": label, "unit": unit, "icon": icon, "color": colour,
                            "value": round(val, 2), "entity_id": eid})
        states = []
        for feat, label, icon, on_t, off_t, tone in _ENV_BIN:
            active = since = None
            if feat == "motion":
                if v.get("motion_active") is not None or "motion" in self.binary:
                    active, since = v.get("motion_active"), v.get("motion_since")
                elif self.occupancy is not None:
                    active, since = v.get("occ_occupied"), v.get("occ_occupied_since")
                else:
                    continue
            elif (feat in self.binary) or (feat == "door" and "door" in self.binary):
                active, since = v.get(f"{feat}_active"), v.get(f"{feat}_since")
            else:
                continue
            on = active is True
            states.append({"key": feat, "label": label, "icon": icon, "active": active,
                           "text": on_t if on else off_t if active is False else "—",
                           "tone": (tone if on else "ok") if active is not None else "unknown", "since": since})
        if len(metrics) + len(states) < 2:
            return None
        primary = next((m for m in metrics if m["key"].startswith("temperature")), metrics[0] if metrics else None)
        return {
            "milesight_role": "env_monitor", "device": self.entry.title,
            "area": self.entry.data.get("area") or self.entry.options.get("area"), "model": self.model.key,
            "metrics": metrics, "states": states, "primary": primary["key"] if primary else None,
            "last_seen": self.meta.get("last_seen"),
        }

    def _energy_applies(self) -> bool:
        """A CT current-transformer clamp (CT101/103 single, CT303/305/310 three-phase). Not the 12-circuit CTH01."""
        return "ct" in self.model.features

    def _energy_monitor(self, v: dict) -> dict | None:
        """A CT clamp's live power as one role sensor: the phase currents as clickable/trendable metrics, plus total
        current, estimated power, energy and phase imbalance. Single-channel clamps have one current metric."""
        if not self._energy_applies():
            return None
        resolve = self._entity_id_resolver()
        three = "ct3" in self.model.features
        metrics = []
        if three:
            for n in (1, 2, 3):
                cur = _nz(v.get(f"current_{n}"))
                metrics.append({"key": f"current_{n}", "label": f"L{n}", "unit": "A", "color": "#4aa3ff",
                                "value": None if cur is None else round(cur, 2), "entity_id": resolve(f"current_{n}")})
            ph = [m["value"] for m in metrics if m["value"] is not None]
            imb = None
            if len(ph) == 3:
                mean = sum(ph) / 3
                imb = round((max(ph) - min(ph)) / mean * 100, 0) if mean >= 2 else 0.0
            summary = {"total_current": _nz(v.get("current_total")), "power": _nz(v.get("power")),
                       "imbalance": imb, "imbalance_status": "high" if (imb is not None and imb > 10) else "ok"}
        else:
            cur = _nz(v.get("current"))
            metrics.append({"key": "current", "label": "Current", "unit": "A", "color": "#4aa3ff",
                            "value": None if cur is None else round(cur, 2), "entity_id": resolve("current")})
            summary = {"power": _nz(v.get("power")), "energy": _nz(v.get("energy"))}
        if not any(m["value"] is not None for m in metrics):     # nothing measured yet
            return None
        primary = next((m for m in metrics if m["value"] is not None), metrics[0])
        return {
            "milesight_role": "energy_monitor", "device": self.entry.title,
            "area": self.entry.data.get("area") or self.entry.options.get("area"), "model": self.model.key,
            "three_phase": three, "metrics": metrics, "summary": summary,
            "primary": primary["key"], "last_seen": self.meta.get("last_seen"),
        }

    def _area(self):
        return self.entry.data.get("area") or self.entry.options.get("area")

    # ---------------------------------------------------------------- GS gas / vape
    def _gas_applies(self) -> bool:
        return bool(self.model.features & {"gs301", "gs601", "vape"})

    def _gas_monitor(self, v: dict) -> dict | None:
        """GS301 odour (NH₃ / H₂S) or GS601 vape as one role sensor: numeric chips + odour / vape status."""
        if not self._gas_applies():
            return None
        resolve = self._entity_id_resolver()
        metrics = []
        for key, label, unit, icon, colour in _GAS_NUM:
            val = _nz(v.get(key))
            if val is None:
                continue
            metrics.append({"key": key, "label": label, "unit": unit, "icon": icon, "color": colour,
                            "value": round(val, 3), "entity_id": resolve(key)})
        states = []
        if isinstance(v.get("odour_level"), str):
            lv = v["odour_level"]
            tone = "critical" if lv.lower() in ("high", "strong", "severe") else "warning" if lv.lower() in ("moderate", "medium") else "ok"
            states.append({"key": "odour", "label": "Odour", "icon": "mdi:scent", "text": lv, "tone": tone, "since": None})
        if "vape" in self.model.features or "gs601" in self.model.features:
            on = v.get("vaping_index_alarm_active") is True or v.get("vape_active") is True
            states.append({"key": "vape", "label": "Vape", "icon": "mdi:smoking-off",
                           "text": "Detected" if on else "Clear", "tone": "critical" if on else "ok",
                           "since": v.get("vape_since")})
        if len(metrics) + len(states) < 2:
            return None
        primary = next((m for m in metrics if m["key"] in ("vaping_index", "nh3")), metrics[0] if metrics else None)
        return {
            "milesight_role": "gas_monitor", "device": self.entry.title, "area": self._area(),
            "model": self.model.key, "metrics": metrics, "states": states,
            "primary": primary["key"] if primary else None, "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- VS occupancy / space
    def _occ_times(self, v: dict, ts: float) -> tuple:
        """Current occupied-for / empty-for seconds (empty-for tracked here, since the device only reports state)."""
        occupied = v.get("occ_occupied")
        occ_s = _nz(v.get("occ_occupied_duration_s")) if occupied else None
        if occupied:
            self.meta.pop("_occ_free_since", None)
            empty_s = None
        else:
            since = self.meta.setdefault("_occ_free_since", round(ts))
            empty_s = max(0.0, ts - since) if occupied is False else None
        return occ_s, empty_s

    def _space(self, v: dict, ts: float) -> dict | None:
        """One VS occupancy / people sensor as a 'space': busy / free, people count, how long it's been occupied /
        empty, sessions and peak today, utilisation and (VS370) light. Scoped to the VS range; VS321 has its own card."""
        if self.occupancy is None or not self.model.key.startswith("VS") or self._counter_applies() \
                or self.model.key == "VS321":
            return None
        occupied = v.get("occ_occupied")
        if occupied is None and v.get("occ_status") is None:
            return None
        occ_s, empty_s = self._occ_times(v, ts)
        return {
            "milesight_role": "space", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "occupied": occupied, "status": v.get("occ_status"),
            "people": v.get("occ_people_count") if self.model.counting else None,
            "counting": bool(self.model.counting), "since": v.get("occ_occupied_since"),
            "occupied_s": None if occ_s is None else round(occ_s), "empty_s": None if empty_s is None else round(empty_s),
            "utilisation": _nz(v.get("occ_utilisation_today_pct")), "sessions": v.get("occ_sessions_today"),
            "peak": v.get("occ_peak_today"), "used_today_s": _nz(v.get("occ_occupied_today_s")),
            "longest_s": _nz(v.get("occ_longest_session_today_s")), "light": _nz(v.get("illuminance")),
            "last_seen": self.meta.get("last_seen"),
        }

    def _workplace(self, v: dict, ts: float) -> dict | None:
        """VS321 room / workplace sensor – reuses the AM chip-and-trend card: temperature / humidity / light /
        utilisation chips drive the trend, with an occupancy headline (people count, occupied-since) and regions."""
        if self.model.key != "VS321":
            return None
        resolve = self._entity_id_resolver()
        occ_s, empty_s = self._occ_times(v, ts)
        catalog = (("temperature", "Temperature", "°C", "mdi:thermometer", "#ff8a5c"),
                   ("humidity", "Humidity", "%", "mdi:water-percent", "#4ab0c4"),
                   ("illuminance", "Light", "lx", "mdi:brightness-6", "#ffca28"))
        metrics = []
        for key, label, unit, icon, colour in catalog:
            val = _nz(v.get(key))
            if val is None:
                continue
            metrics.append({"key": key, "label": label, "unit": unit, "icon": icon, "color": colour,
                            "value": round(val, 2), "entity_id": resolve(key)})
        util = _nz(v.get("occ_utilisation_today_pct"))
        if util is not None:
            metrics.append({"key": "utilisation", "label": "Utilisation", "unit": "%", "icon": "mdi:chart-box",
                            "color": "#4aa3ff", "value": round(util), "entity_id": None})
        regions = [v.get(f"region_{n}") for n in range(1, 11)]
        seats = [bool(r) for r in regions if r is not None]
        if not metrics:
            return None
        primary = next((m for m in metrics if m["key"] == "temperature"), metrics[0])
        return {
            "milesight_role": "workplace", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "metrics": metrics, "primary": primary["key"],
            "occupied": v.get("occ_occupied"), "people": v.get("occ_people_count"),
            "since": v.get("occ_occupied_since"), "occupied_s": None if occ_s is None else round(occ_s),
            "empty_s": None if empty_s is None else round(empty_s),
            "seats_used": sum(1 for s in seats if s), "seats_total": len(seats) or (v.get("occ_region_count") or 0),
            "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- UC controllers (I/O + valves)
    def _uc_label(self, key: str, fallback: str) -> str:
        """Custom per-channel label from device settings (entry.options['uc_labels']), else the generic name."""
        lbl = (self.entry.options.get("uc_labels") or {}).get(key)
        return lbl.strip() if isinstance(lbl, str) and lbl.strip() else fallback

    def _uc_rs485(self) -> list[dict]:
        """The RS485 purposes attached to this controller (named templates first, then a count of plain channels)."""
        out: list[dict] = []
        applied = self.entry.options.get("channel_templates", []) or []
        seen = set()
        for a in applied:
            tmpl = a.get("template")
            if tmpl in _UC_RS485 and tmpl not in seen:
                seen.add(tmpl)
                label, icon, colour = _UC_RS485[tmpl]
                out.append({"label": label, "icon": icon, "color": colour, "template": tmpl})
        extra = len(self.channels) - sum(1 for a in applied if a.get("template") in _UC_RS485)
        if extra > 0:
            out.append({"label": f"{extra} Modbus channel{'s' if extra != 1 else ''}", "icon": "mdi:lan",
                        "color": "#8a93a2", "template": None})
        return out

    def _controller_applies(self) -> bool:
        return self.model.key in _UC_CONTROLLER

    def _controller(self, v: dict) -> dict | None:
        """A UC I/O controller as one role sensor: digital inputs (status), relay outputs (toggles, with their switch
        entity id), PT100 / analog readings (chips that drive the trend) and pulse counters, plus attached RS485."""
        if not self._controller_applies():
            return None
        resolve = self._entity_id_resolver()
        inputs, outputs, metrics, counters = [], [], [], []
        for n in range(1, 9):
            key = f"gpio_input_{n}"
            if key in v:
                inputs.append({"key": key, "label": self._uc_label(key, f"DI{n}"), "name": f"DI{n}",
                               "on": bool(v.get(key))})
        for n in range(1, 5):
            key = f"gpio_output_{n}"
            if key in v:
                outputs.append({"key": key, "label": self._uc_label(key, f"DO{n}"), "name": f"DO{n}",
                                "on": bool(v.get(key)), "entity_id": resolve(key, "switch")})
        # trendable analog chips: PT100 (°C), ADC current (mA), ADV voltage (V), UC50x analog inputs (mA / V)
        for n in (1, 2):
            pk = f"pt100_{n}"
            if _nz(v.get(pk)) is not None:
                metrics.append({"key": pk, "label": self._uc_label(pk, f"PT100-{n}"), "name": f"PT100-{n}",
                                "unit": "°C", "icon": "mdi:thermometer", "color": "#ff8a5c",
                                "value": round(_nz(v.get(pk)), 2), "entity_id": resolve(pk)})
        for n in (1, 2):
            ak = f"adc_{n}"
            if _nz(v.get(ak)) is not None:
                metrics.append({"key": ak, "label": self._uc_label(ak, f"AI{n}"), "name": f"AI{n} (mA)",
                                "unit": "mA", "icon": "mdi:sine-wave", "color": "#4aa3ff",
                                "value": round(_nz(v.get(ak)), 2), "entity_id": resolve(ak)})
            vk = f"adv_{n}"
            if _nz(v.get(vk)) is not None:
                metrics.append({"key": vk, "label": self._uc_label(vk, f"AV{n}"), "name": f"AV{n} (V)",
                                "unit": "V", "icon": "mdi:flash", "color": "#ffca28",
                                "value": round(_nz(v.get(vk)), 2), "entity_id": resolve(vk)})
            ik = f"analog_input_{n}"
            if _nz(v.get(ik)) is not None:
                unit = "V" if v.get(f"{ik}_type") == "voltage" else "mA"
                metrics.append({"key": ik, "label": self._uc_label(ik, f"AI{n}"), "name": f"AI{n} ({unit})",
                                "unit": unit, "icon": "mdi:sine-wave", "color": "#4aa3ff",
                                "value": round(_nz(v.get(ik)), 2), "entity_id": resolve(ik)})
        for key in ("pulse_count", "gpio_counter_1", "gpio_counter_2", "gpio_counter_3", "gpio_counter_4", "gpio_counter"):
            if _nz(v.get(key)) is not None:
                n = key.rsplit("_", 1)[-1]
                generic = "Pulses" if not n.isdigit() else f"Counter {n}"
                counters.append({"key": key, "label": self._uc_label(key, generic), "name": generic,
                                 "value": int(_nz(v.get(key)))})
        if not (inputs or outputs or metrics or counters):
            return None
        primary = next((m for m in metrics if m.get("entity_id")), metrics[0] if metrics else None)
        return {
            "milesight_role": "controller", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "inputs": inputs, "outputs": outputs, "metrics": metrics, "counters": counters,
            "primary": primary["key"] if primary else None, "rs485": self._uc_rs485(),
            "battery": _nz(v.get("battery")), "last_seen": self.meta.get("last_seen"),
        }

    def _valve_applies(self) -> bool:
        return self.model.key in _UC_VALVE

    def _valve_controller(self, v: dict) -> dict | None:
        """A UC valve controller as one role sensor: per-valve open / closed (solenoid, UC511/512) or % opening
        (motorised UC521) with the entity to control it, the run's pulse/flow count and pipe pressure(s)."""
        if not self._valve_applies():
            return None
        resolve = self._entity_id_resolver()
        motorised = self.model.key == "UC521"
        valves = []
        for n in (1, 2):
            if motorised:
                ok = _nz(v.get(f"valve_{n}_opening"))
                if ok is None and v.get(f"valve_{n}_type") is None:
                    continue
                valves.append({
                    "key": f"valve_{n}_opening", "label": self._uc_label(f"valve_{n}", f"Valve {n}"), "name": f"Valve {n}",
                    "kind": "opening", "opening": None if ok is None else round(ok),
                    "open": (ok or 0) > 0, "direction": v.get(f"valve_{n}_direction"),
                    "vtype": (v.get(f"valve_{n}_type") or "").replace("_", " ") or None,
                    "pulse": _nz(v.get(f"valve_{n}_pulse")), "duration": _nz(v.get(f"valve_{n}_opening_duration")),
                    "entity_id": resolve(f"valve_{n}_opening", "number"),
                })
            else:
                st = v.get(f"valve_{n}")
                if st is None and v.get(f"valve_{n}_pulse") is None and v.get(f"valve_{n}_result") is None:
                    continue
                valves.append({
                    "key": f"valve_{n}", "label": self._uc_label(f"valve_{n}", f"Valve {n}"), "name": f"Valve {n}",
                    "kind": "switch", "open": None if st is None else bool(st), "result": v.get(f"valve_{n}_result"),
                    "pulse": _nz(v.get(f"valve_{n}_pulse")), "pressure": _nz(v.get("pressure")),
                    "entity_id": resolve(f"valve_{n}", "switch"),
                })
        if not valves:
            return None
        pressures = []
        for key, label in (("pressure", "Pressure"), ("pressure_1", "Pipe 1"), ("pressure_2", "Pipe 2")):
            val = _nz(v.get(key))
            if val is not None:
                pressures.append({"key": key, "label": label, "value": round(val), "unit": "kPa",
                                  "alarm": bool(v.get(f"{key}_alarm_active")),
                                  "status": v.get(f"{key}_alarm_status")})
        return {
            "milesight_role": "valve_controller", "device": self.entry.title, "area": self._area(),
            "model": self.model.key, "motorised": motorised, "valves": valves, "pressures": pressures,
            "battery": _nz(v.get("battery")), "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- EM500 single-reading sensors + native soil
    def _em_reading_applies(self) -> bool:
        return self.model.key in _EM_READING

    def _em_reading(self, v: dict) -> dict | None:
        """An EM500 single-value sensor (light / pipe pressure / PT100 temp / UDL / SWL) as one role: the reading with
        its trend entity, today's min / max, and either a gauge fraction or a level % of the sensor's range."""
        cfg = _EM_READING.get(self.model.key)
        if cfg is None:
            return None
        key, label, unit, icon, colour, kind = cfg
        value = _nz(v.get(key))
        if value is None:
            return None
        lo_t, hi_t = _nz(v.get(f"{key}_min_today")), _nz(v.get(f"{key}_max_today"))
        rmin, rmax = _nz(v.get("range_min")), _nz(v.get("range_max"))
        role = {
            "milesight_role": "em_reading", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "kind": kind, "label": label, "unit": unit, "icon": icon, "color": colour,
            "value": round(value, 2), "entity_id": self._entity_id_resolver()(key),
            "min_today": None if lo_t is None else round(lo_t, 2), "max_today": None if hi_t is None else round(hi_t, 2),
            "battery": _nz(v.get("battery")), "sensor_error": v.get("sensor_error"),
            "last_seen": self.meta.get("last_seen"),
        }
        if kind == "level":
            span = (rmax - rmin) if (rmax is not None and rmin is not None) else rmax
            if self.model.key == "EM500-UDL" and rmax is not None:     # distance to surface → water column from the bottom
                col = max(0.0, rmax - value)
                role.update(fill_value=round(col), fill_unit=unit, headroom=round(value),
                            pct=round(col / span * 100, 1) if span else None, range_max=rmax, range_min=rmin)
            elif self.model.key == "EM500-SWL" and rmax is not None:   # submersible depth is the water column itself
                role.update(fill_value=round(value), fill_unit=unit,
                            pct=round(value / span * 100, 1) if span else None, range_max=rmax, range_min=rmin)
            else:
                role.update(pct=None, range_max=rmax, range_min=rmin)  # no range configured → show the raw reading
        else:
            gmin = rmin if rmin is not None else (lo_t if (lo_t is not None and lo_t < 0) else 0.0)
            gmax = rmax if rmax is not None else (hi_t * 1.1 if (hi_t and hi_t > 0) else max(value * 1.4, 1.0))
            if gmax <= gmin:
                gmax = gmin + 1
            role.update(gmin=round(gmin, 2), gmax=round(gmax, 2),
                        pct=round(max(0.0, min(100.0, (value - gmin) / (gmax - gmin) * 100)), 1))
        return role

    def _em_soil(self, v: dict) -> dict | None:
        """EM500-SMTC native soil probe (moisture / temperature / EC) on the shared Soil card. Only the three readings
        it measures are set; the card hides the pH / NPK / salinity sections it doesn't."""
        if self.model.key != "EM500-SMTC":
            return None
        from . import soil_calc as _sc
        moisture, temperature, ec = _nz(v.get("moisture")), _nz(v.get("temperature")), _nz(v.get("electricity"))
        if moisture is None and temperature is None and ec is None:
            return None
        st = {"moisture": _sc.status("moisture", moisture), "ec": _sc.status("ec", ec)}
        return {
            "milesight_role": "soil", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "moisture": moisture, "temperature": temperature, "ec": ec,
            "ph": None, "nitrogen": None, "phosphorus": None, "potassium": None, "salinity": None, "tds": None,
            "status": st, "moisture_label": _sc.moisture_label(moisture),
            "severity": {"high": "warning", "low": "warning", "ok": "ok"}[_sc.worst(list(st.values()))],
            "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- TS temperature probes
    def _temp_probe_applies(self) -> bool:
        return bool(self.model.features & {"ts", "ts60x"})

    @staticmethod
    def _probe_badge(val, lo, hi, act, status):
        """(tone, text) for a probe: configured cold-chain limits first (with the number), else the device's own
        threshold / mutation alarm flags. tone is high | low | mutation | ok | None."""
        def _f(x):
            return (f"{x:.1f}".rstrip("0").rstrip(".")) if isinstance(x, float) else str(x)
        if val is not None and hi is not None and val > hi:
            return "high", f"Above {_f(hi)} °C"
        if val is not None and lo is not None and val < lo:
            return "low", f"Below {_f(lo)} °C"
        if hi is not None or lo is not None:
            return "ok", "In range"
        s = (status or "").lower()
        if act is True:
            if "above" in s:
                return "high", "Above threshold"
            if "below" in s:
                return "low", "Below threshold"
            if "mutation" in s:
                return "mutation", "Rapid change"
            if any(w in s for w in ("between", "outside", "exceed", "tolerance")):
                return "high", s.replace("_", " ").replace(" alarm", "").strip().capitalize()
            return "high", "Alarm"
        if act is False:
            return "ok", "In range"
        if "mutation" in s:
            return "mutation", "Rapid change"
        return None, None

    def _temp_probe(self, v: dict) -> dict | None:
        """A TS temperature probe as one role: each probe's temperature with its alarm badge (configured cold-chain
        limits or the device's own threshold alarm), today's min/max and a trend entity; plus humidity, the
        door/contact and any cold-chain tilt / light alarms."""
        if not self._temp_probe_applies():
            return None
        resolve = self._entity_id_resolver()
        lo, hi = _nz(self.pcfg.get("temp_low")), _nz(self.pcfg.get("temp_high"))
        probes = []
        for suffix, label in (("", ""), ("_1", "Probe 1"), ("_2", "Probe 2")):
            tkey = f"temperature{suffix}"
            if tkey not in v:
                continue
            val = _nz(v.get(tkey))
            tone, text = self._probe_badge(val, lo, hi, v.get(f"{tkey}_alarm_active"), v.get(f"{tkey}_alarm_status"))
            contact = None
            mkey = f"magnet_status{suffix}"
            if mkey in v:
                contact = bool(v.get(mkey))
            probes.append({
                "key": tkey, "label": label, "value": None if val is None else round(val, 1), "unit": "°C",
                "entity_id": resolve(tkey), "tone": tone, "badge": text,
                "low": lo, "high": hi, "mutation": _nz(v.get(f"{tkey}_mutation")),
                "min_today": _nz(v.get(f"{tkey}_min_today")), "max_today": _nz(v.get(f"{tkey}_max_today")),
                "sensor_status": v.get(f"{tkey}_sensor_status"), "contact": contact,
            })
        if not probes:
            return None
        door = v.get("door_active")
        if door is None and "magnet_status" in v:
            door = bool(v.get("magnet_status"))
        extra = []
        for feat, name, icon in (("tilt", "Tilt", "mdi:angle-acute"), ("light", "Light", "mdi:white-balance-sunny")):
            act = v.get(f"{feat}_alarm_active")
            if act is not None or v.get(f"{feat}_alarm_status"):
                extra.append({"label": name, "icon": icon, "active": bool(act),
                              "status": (v.get(f"{feat}_alarm_status") or "").replace("_", " ")})
        alarm = any(p["tone"] in ("high", "low", "mutation") for p in probes) or any(e["active"] for e in extra)
        return {
            "milesight_role": "temp_probe", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "probes": probes, "humidity": _nz(v.get("humidity")), "door": door, "extra": extra, "alarm": alarm,
            "battery": _nz(v.get("battery")), "sensor_error": v.get("sensor_error"),
            "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- WS scene buttons / panels
    def _scene_applies(self) -> bool:
        return bool(self.model.buttons) and "ds3604" not in self.model.features

    def _scene_panel(self, v: dict) -> dict | None:
        """A WS button / scene panel (WS101 single button, WS136 / WS156 six-key panels) as one role: each button's
        last press (type + when) and today's press count, so the triggers are visible on a dashboard."""
        if not self._scene_applies():
            return None
        resolve = self._entity_id_resolver()
        rec = self.meta.get("_btn", {})
        today = time.strftime("%Y%m%d", time.localtime())
        buttons = []
        for key in self.model.buttons:
            r = rec.get(key) or {}
            buttons.append({
                "key": key, "label": _button_label(key),
                "last_type": r.get("type"), "last_label": _EVENT_LABEL.get(r.get("type"), r.get("type")),
                "last_at": r.get("at"), "count_today": r.get("count", 0) if r.get("day") == today else 0,
                "entity_id": resolve(key, "event"),
            })
        last = max((b["last_at"] for b in buttons if b["last_at"]), default=None)
        recent = max((b for b in buttons if b["last_at"]), key=lambda b: b["last_at"], default=None)
        summary = (f"{recent['label']} · {recent['last_label']}" if recent else "No presses yet")
        return {
            "milesight_role": "scene_panel", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "events": [_EVENT_LABEL.get(e, e) for e in self.model.event_types], "buttons": buttons,
            "last_press": last, "summary": summary, "battery": _nz(v.get("battery")),
            "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- DS3604 e-ink display
    def _display(self, v: dict) -> dict | None:
        """A DS3604 e-ink display as one role for the composer card: the text / QR content of both templates (what the
        device reports, else what was last sent), which template is shown, and the entity ids to drive it."""
        if "ds3604" not in self.model.features:
            return None
        resolve = self._entity_id_resolver()
        templates = {}
        for t in (1, 2):
            blocks = [{"n": n, "key": f"text_{n}", "text": self.display_text(t, f"text_{n}")} for n in range(1, 11)]
            templates[str(t)] = {"blocks": blocks, "qr": self.display_text(t, "qrcode")}
        return {
            "milesight_role": "display", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "templates": templates, "active": _nz(v.get("current_template_id")) or 1,
            "error": self.meta.get("display_error"),
            "template_entity_id": resolve("display_template", "select"),
            "battery": _nz(v.get("battery")), "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- AT101 asset tracker
    def _tracker_applies(self) -> bool:
        return "at101" in self.model.features

    def _asset_tracker(self, v: dict) -> dict | None:
        """An AT101 GNSS / Wi-Fi tracker as one role: last position, moving / stopped, geofence, distance travelled
        (today / week / month), temperature and tamper / tilt — for the map-based tracker card."""
        if not self._tracker_applies():
            return None
        resolve = self._entity_id_resolver()
        lat, lon = _nz(v.get("latitude")), _nz(v.get("longitude"))
        motion = v.get("motion_status")
        geof = v.get("geofence_status")
        tamper, tilt = v.get("tamper"), v.get("tilted")
        temp_alarm = bool(v.get("temperature_alarm_active"))
        wifi_aps = v.get("wifi_ap_count")
        wifi_only = lat is None and bool(wifi_aps)
        alarm = bool(tamper) or geof == "outside" or temp_alarm
        return {
            "milesight_role": "asset_tracker", "device": self.entry.title, "area": self._area(),
            "model": self.model.key, "lat": lat, "lon": lon,
            "moving": motion in ("start", "moving"),
            "motion_label": "Moving" if motion in ("start", "moving") else "Stopped" if motion == "stop" else "—",
            "geofence": geof if geof in ("inside", "outside") else None,
            "tamper": None if tamper is None else bool(tamper),
            "tilt": None if tilt is None else bool(tilt),
            "temperature": _nz(v.get("temperature")), "temp_alarm": temp_alarm,
            "wifi_aps": wifi_aps, "wifi_only": wifi_only,
            "distance_today": _nz(v.get("distance_today_km")), "distance_week": _nz(v.get("distance_week_km")),
            "distance_month": _nz(v.get("distance_month_km")),
            "location_entity_id": resolve("location", "device_tracker"),
            "alarm": alarm, "battery": _nz(v.get("battery")), "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- WS201 consumable supplies
    def _supplies_applies(self) -> bool:
        return "ws201" in self.model.features

    def _supplies(self, v: dict, ts: float) -> dict | None:
        """A WS201 consumables dispenser (tissue / soap / paper towels) as one role: % remaining, low / out status,
        a days-to-empty estimate from the drain rate, and when it was last refilled."""
        if not self._supplies_applies():
            return None
        rem = _nz(v.get("remaining"))
        if rem is None:
            return None
        hist = self.meta.setdefault("_sup", [])
        if hist and rem - hist[-1][1] >= 15:        # a jump up = a refill: note it and start the rate afresh
            self.meta["_sup_refill"] = round(ts)
            hist.clear()
        hist.append([round(ts), round(rem, 1)])
        while len(hist) > 1 and hist[0][0] < ts - 14 * 86400:
            hist.pop(0)
        rate = days_left = None
        if len(hist) >= 2:
            dt, drop = hist[-1][0] - hist[0][0], hist[0][1] - hist[-1][1]
            if dt >= 3600 and drop > 0:
                rate = drop / (dt / 86400)          # % per day
                if rate > 0.1:
                    days_left = rem / rate
        status = "out" if rem <= 5 else "low" if rem <= 20 else "ok"
        return {
            "milesight_role": "supplies", "device": self.entry.title, "area": self._area(), "model": self.model.key,
            "remaining": round(rem), "status": status,
            "rate": round(rate, 1) if rate else None, "days_left": round(days_left) if days_left else None,
            "refilled_at": self.meta.get("_sup_refill"), "battery": _nz(v.get("battery")),
            "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- WS558 switch / light panel
    def _switch_panel(self, v: dict) -> dict | None:
        """A multi-gang switch (WS558 lights, smart sockets, wall switches): the channels and their on/off state, so
        the Light card can toggle them. Resolves each gang's switch entity id for the card's service calls."""
        gangs = getattr(self.model, "gangs", 0) or 0
        if gangs < 1 or not self.model.control:
            return None
        try:
            from homeassistant.helpers import entity_registry as er
            reg = er.async_get(self.hass)
        except Exception:  # noqa: BLE001
            reg = None
        channels = []
        for n in range(1, gangs + 1):
            key = f"switch_{n}" if gangs > 1 else "switch_1"
            eid = None
            if reg is not None:
                try:
                    eid = reg.async_get_entity_id("switch", DOMAIN, f"{self.deveui}_{key}")
                except Exception:  # noqa: BLE001
                    eid = None
            channels.append({"channel": n, "key": key, "entity_id": eid, "on": v.get(key)})
        return {
            "milesight_role": "switch_panel", "device": self.entry.title, "area": self._area(),
            "model": self.model.key, "gangs": gangs, "channels": channels,
            "power": _nz(v.get("power")), "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- WS302 sound level / water-flow
    def _sound_assess(self, v: dict, ts: float) -> dict | None:
        """WS302 sound: current / LAeq / max dB, a learned quiet baseline, and continuous-flow detection. If the
        level stays a margin above baseline for longer than the set time, it flags 'left running' (tap / cistern)."""
        if "ws302" not in self.model.features:
            return None
        level = _nz(v.get("sound_level"))
        laeq = _nz(v.get("sound_level_eq"))
        smax = _nz(v.get("sound_level_max"))
        now_db = laeq if laeq is not None else level            # LAeq is the better "is it continuous" measure
        if now_db is None:
            return None
        opts = self.entry.options
        margin = float(opts.get("sound_margin") or 8)
        minutes = float(opts.get("sound_minutes") or 5)
        manual = _nz(opts.get("sound_baseline"))
        # learn the quiet baseline: keep a rolling window of recent readings, take a low percentile
        hist = self.meta.setdefault("_snd", [])
        hist.append([round(ts), round(now_db, 1)])
        while len(hist) > 1 and hist[0][0] < ts - 6 * 3600:      # 6-hour learning window
            del hist[0]
        learned = None
        if hist:
            vals = sorted(x[1] for x in hist)
            learned = vals[max(0, int(len(vals) * 0.15) - 1)]    # ~15th percentile = the quiet floor
        baseline = manual if manual is not None else learned
        threshold = round(baseline + margin, 1) if baseline is not None else None
        flowing = threshold is not None and now_db >= threshold
        since = self.meta.get("_snd_flow_since")
        if flowing:
            if since is None:
                since = self.meta["_snd_flow_since"] = round(ts)
        else:
            since = self.meta["_snd_flow_since"] = None
        dur = (ts - since) if since else 0
        alert = bool(since and dur >= minutes * 60)
        return {
            "milesight_role": "sound_monitor", "device": self.entry.title, "area": self._area(),
            "model": self.model.key, "level": now_db, "current": level, "laeq": laeq, "max": smax,
            "baseline": None if baseline is None else round(baseline, 1), "threshold": threshold,
            "margin": margin, "minutes": minutes, "manual_baseline": manual is not None,
            "flowing": flowing, "flow_since": since, "flow_s": round(dur), "alert": alert,
            "weighting": v.get("sound_weighting"), "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- VS people counter
    def _counter_applies(self) -> bool:
        """A VS people counter (passage / entrance): VS132/133/135, VS350/351/360, VS121. Not the occupancy VS321."""
        return "peoplecount" in self.model.features or self.model.key == "VS121"

    def _people_counter(self, v: dict) -> dict | None:
        if not self._counter_applies():
            return None
        inn, out = _nz(v.get("people_in_today")), _nz(v.get("people_out_today"))
        inside = _nz(v.get("people_count_all"))
        if inside is None:
            inside = _nz(v.get("people_net_today"))
        if inn is None and out is None and inside is None:
            return None
        cap = _nz(self.entry.options.get("capacity")) or None
        resolve = self._entity_id_resolver()
        trend_key = "people_count_all" if v.get("people_count_all") is not None else "people_in_today"
        return {
            "milesight_role": "people_counter", "device": self.entry.title, "area": self._area(),
            "model": self.model.key, "inside": None if inside is None else int(inside),
            "in_today": None if inn is None else int(inn), "out_today": None if out is None else int(out),
            "net": None if (inn is None or out is None) else int(inn - out),
            "capacity": None if not cap else int(cap), "over": bool(cap and inside is not None and inside > cap),
            "trend_key": trend_key, "trend_entity_id": resolve(trend_key),
            "in_entity_id": resolve("people_in_today"), "out_entity_id": resolve("people_out_today"),
            "last_seen": self.meta.get("last_seen"),
        }

    # ---------------------------------------------------------------- VS373 fall detection
    def _fall_monitor(self, v: dict) -> dict | None:
        if "vs373" not in self.model.features:
            return None
        det = v.get("detection_status")
        alarms = [(t, v.get(f)) for t, f in (("fall", "alarm_fall"), ("motionless", "alarm_motionless"),
                                             ("dwell", "alarm_dwell"), ("breathing", "alarm_breathing"),
                                             ("out of bed", "alarm_out_of_bed"))]
        active = [t for t, on in alarms if on is True]
        state = ("fall" if "fall" in active or det == "fall" else det or ("alarm" if active else "normal"))
        labels = {"fall": "Fall detected", "in_bed": "In bed", "out_of_bed": "Out of bed", "vacant": "Vacant",
                  "normal": "Normal", "unavailable": "No data"}
        tone = "critical" if (state == "fall" or "motionless" in active or "breathing" in active) \
            else "warning" if (state == "out_of_bed" or active) else "ok"
        return {
            "milesight_role": "fall_monitor", "device": self.entry.title, "area": self._area(),
            "model": self.model.key, "state": state, "state_label": labels.get(state, str(state).replace("_", " ")),
            "tone": tone, "respiration": _nz(v.get("respiratory_rate")), "respiration_status": v.get("respiratory_status"),
            "dwell_s": _nz(v.get("dwell_time_max")) or _nz(v.get("dwell_time_avg")),
            "occupied": det not in ("vacant", None), "alarms": active,
            "last_alarm": v.get("last_alarm"), "last_alarm_at": v.get("last_alarm_at"),
            "last_seen": self.meta.get("last_seen"),
        }

    def _weather_assess(self, v: dict, ts: float) -> dict | None:
        """Turn the WS90 channel values into the weather card's attributes (condition, wind, rain, pressure trend)."""
        applied = self._weather_applied()
        if applied is None:
            return None
        from . import weather_calc as _wc
        val = self._template_values(applied, v)
        temp, hum = _nz(val.get("temperature")), _nz(val.get("humidity"))
        pressure, rain, uvi = _nz(val.get("pressure")), _nz(val.get("rain")), _nz(val.get("uvi"))
        gust, wdir = _nz(val.get("gust")), _nz(val.get("wind_direction"))
        counter = _nz(val.get("rain_counter"))
        # 3-hour pressure change, from a small rolling history kept on the device
        delta3h = None
        if pressure is not None:
            hist = self.meta.setdefault("_wx_p", [])
            hist.append([round(ts), round(pressure, 1)])
            cutoff = ts - 3.6 * 3600
            while len(hist) > 1 and hist[0][0] < cutoff:
                del hist[0]
            old = next((p for t, p in hist if t <= ts - 3 * 3600), hist[0][1])
            delta3h = round(pressure - old, 1)
        # rain since local midnight, from the lifetime counter
        rain_today = None
        if counter is not None:
            day = self._day(ts)
            r = self.meta.get("_wx_rain")
            if not r or r.get("day") != day or _nz(r.get("base")) is None or counter < r["base"]:
                self.meta["_wx_rain"] = {"day": day, "base": counter}
            rain_today = round(max(0.0, counter - self.meta["_wx_rain"]["base"]), 1)
        trend, forecast, p_sev = _wc.pressure_trend(delta3h)
        uv_label, uv_sev = _wc.uv_risk(uvi)
        feels = _heat_index(temp, hum) if temp is not None and hum is not None else temp
        return {
            "milesight_role": "weather", "device": self.entry.title,
            "area": self.entry.data.get("area") or self.entry.options.get("area"), "model": "WS90",
            "temperature": temp, "humidity": hum, "feels_like": None if feels is None else round(feels, 1),
            "condition": _wc.condition(rain, uvi, val.get("light")),
            "wind_speed": _nz(val.get("wind_speed")), "gust": gust, "wind_unit": "km/h",
            "wind_direction": wdir, "wind_compass": _wc.compass(wdir), "wind_severity": _wc.wind_severity(gust),
            "rain": rain, "rain_today": rain_today, "rain_total": counter,
            "pressure": pressure, "pressure_trend": trend, "forecast": forecast, "pressure_severity": p_sev,
            "uvi": uvi, "uv_risk": uv_label, "uv_severity": uv_sev, "light": _nz(val.get("light")),
            "last_seen": self.meta.get("last_seen"),
        }

    def _vibration_assess(self, v: dict) -> dict | None:
        """ISO 10816 verdict from the WTVB01 channel values currently in the values dict (keyed by register)."""
        applied = self._vibration_applied()
        if applied is None:
            return None
        from . import vibration_calc as _vc
        val = self._template_values(applied, v)
        machine_class = "large" if self._pkey == "vibration_large" else "small"
        res = _vc.assess({"x": val.get("vx"), "y": val.get("vy"), "z": val.get("vz")}, machine_class)
        axes = ("x", "y", "z")
        res.update({
            "milesight_role": "vibration", "device": self.entry.title,
            "area": self.entry.data.get("area") or self.entry.options.get("area"), "model": "WTVB01-485",
            "velocity": {a: val.get("v" + a) for a in axes},
            "displacement": {a: val.get("d" + a) for a in axes},
            "frequency": {a: val.get("hz" + a) for a in axes},
            "temperature": val.get("temp"),
            "last_seen": self.meta.get("last_seen"),
        })
        return res

    def fixed_location(self) -> tuple[float, float] | None:
        """Where the device is mounted (captured on the phone in the commissioning panel, or set in its options)."""
        loc = self.entry.options.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not (lat == 0 and lon == 0):
            return float(lat), float(lon)
        return None

    # ------------------------------------------------------------- purposes
    @property
    def _pkey(self) -> str | None:
        return self.purpose.key if self.purpose else None

    @property
    def _pfam(self) -> frozenset[str]:
        """Families the purpose applies to on this device."""
        return (self.purpose.families & self.families) if self.purpose else frozenset()

    def _load_purposes(self, trackers: dict) -> None:
        if "load" in self._pfam and self._pkey in _purposes.LOAD_ANALYTICS:
            self.loads["load_"] = (LoadTracker(trackers.get("load_")), self.pcfg, self._pkey, None)
        for n, key in _purposes.channel_purposes(dict(self.entry.options), load_channels(self.model.key)).items():
            if key in _purposes.LOAD_ANALYTICS or key == "pump":
                self.loads[f"load{n}_"] = (LoadTracker(trackers.get(f"load{n}_")), _purposes.settings(key, {}), key, n)
        if "temperature" in self._pfam and (any(isinstance(self.pcfg.get(k), (int, float))
                                                for k in ("temp_low", "temp_high")) or self.pcfg.get("temp_rise_day")):
            self.tempw = TempWatch(trackers.get("tempwatch"))
        if self._pkey in ("bin", "flood", "rain_gauge"):
            self.trend = Trend(trackers.get("trend"))

    def _meter_type(self) -> str:
        mt = self._opt(CONF_METER_TYPE, "none")
        if mt in (None, "", "none") and self.purpose is not None and self.purpose.meter and "pulse" in self._pfam:
            return self.purpose.meter
        return mt

    def _work_hours(self, ts: float) -> bool:
        days = self._opt(CONF_OPEN_DAYS, DEFAULT_OPEN_DAYS)
        return _purposes.in_hours(datetime.fromtimestamp(ts, self.cal.tz),
                                  int(self._opt(CONF_OPEN_HOUR, DEFAULT_OPEN_HOUR)),
                                  int(self._opt(CONF_CLOSE_HOUR, DEFAULT_CLOSE_HOUR)),
                                  tuple(WEEKDAYS.index(d) for d in days if d in WEEKDAYS))

    def _day_start(self, ts: float) -> float:
        return datetime.fromtimestamp(ts, self.cal.tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def _temp_value(self, src: dict[str, Any]) -> float | None:
        for k in ("temperature", "temperature_1"):
            if isinstance(src.get(k), (int, float)):
                return float(src[k])
        return None

    def _load_running_for(self, src: dict[str, Any], channel: int | None) -> bool | None:
        if channel is not None:
            a = src.get(f"current_{channel}")
            return a >= self.limits["run_a"] if isinstance(a, (int, float)) else None
        if "socket" in self.model.features and isinstance(src.get("power"), (int, float)):
            return src["power"] >= float(self.pcfg.get("run_w") or 10)
        return _load_running(src, self.limits)

    def _present(self, decoded: dict[str, Any]) -> bool | None:
        if self.model.occupancy_fn is not None:
            n = self.model.occupancy_fn(decoded)
            if n is not None:
                return n > 0
        if "pir" in decoded:
            return _flag(decoded.get("pir"))
        if "motion" in self.model.features:
            return BINARY_FEATURES["motion"][0](decoded, self.limits)
        if isinstance(decoded.get("people_in"), (int, float)):
            return decoded["people_in"] > 0
        return None

    def _purpose_reading(self, ts: float, decoded: dict[str, Any]) -> None:
        """Per-uplink purpose analytics (load trackers, temperature watch, trends, visits, after hours)."""
        day, start, work = self._day(ts), self._day_start(ts), self._work_hours(ts)
        base = {"deveui": self.deveui, "device": self.entry.title, "area": self.entry.data.get("area")}
        for prefix, (tr, cfg, key, ch) in self.loads.items():
            for ev in tr.update(ts, self._load_running_for(decoded, ch), day, start, work):
                if ev["type"] == "after_hours":
                    self.hass.bus.async_fire(f"{DOMAIN}_load", {**base, **ev, "purpose": key, "channel": ch})
        t = self._temp_value(decoded)
        if self.tempw is not None and t is not None:
            door = self.binary.get("door")
            for ev in self.tempw.update(ts, t, day, self.pcfg, door_open=bool(door and door.s.get("active"))):
                self.hass.bus.async_fire(f"{DOMAIN}_temperature", {**base, **ev, "purpose": self._pkey})
        if self.trend is not None:
            if self._pkey == "bin":
                self.trend.add(ts, bin_fill(decoded.get("distance"), float(self.pcfg.get("bin_depth_mm") or 0)))
            elif self._pkey == "flood":
                self.trend.add(ts, water_level_cm(decoded.get("distance"),
                                                  float(self.pcfg.get("empty_distance_mm") or 0)))
            else:
                self.trend.add(ts, self._meter_value(self.raw))
        if self._pkey == "mains":
            amps = [decoded[k] for k in CT_CURRENT_KEYS if isinstance(decoded.get(k), (int, float))]
            if amps:
                n = self.meta.get("_zero_n", 0) + 1 if max(amps) < 0.1 else 0
                self.meta["_zero_n"] = n
        if self._pkey == "toilet":
            if isinstance(decoded.get("people_in"), (int, float)):      # people counters: everyone who came in
                self.meta["visits"] = self.meta.get("visits", 0) + int(decoded["people_in"])
            else:
                present = self._present(decoded)
                if present and self.meta.get("_present") is False:
                    self.meta["visits"] = self.meta.get("visits", 0) + 1
                if present is not None:
                    self.meta["_present"] = present
        if self.purpose is not None and self.pcfg.get("after_hours") and self._pfam & {"contact", "motion"}:
            active = (_flag(decoded.get("magnet_status")) if "contact" in self._pfam else self._present(decoded))
            if work:
                self.meta.pop("after_hours_at", None)
            elif active and not self.meta.get("after_hours_at"):
                self.meta["after_hours_at"] = ts
                self.hass.bus.async_fire(f"{DOMAIN}_after_hours", {**base, "purpose": self._pkey})

    def _purpose_values(self, v: dict[str, Any], ts: float) -> None:
        p, label = self.purpose, (self.purpose.label if self.purpose else None)
        v["purpose"] = label
        v["temperature_now"] = self._temp_value(v) if self.tempw is not None else None
        if p is None and not self.loads:
            return
        if p is not None:
            v["purpose_group"], v["purpose_severity"] = p.group, p.severity
        if self._pkey == "water_trough" and "door" in self.binary:   # float switch: contact open = trough empty
            empty = v.get("door_active")
            v["is_trough"] = True
            self.attrs["door_active"] = {"milesight_role": "water_trough", "device": self.entry.title,
                                         "area": self.entry.data.get("area"), "empty": empty,
                                         "since": v.get("door_since"), "empty_confirmed": bool(v.get("door_left_open"))}
        if self._pkey == "electric_fence" and "door" in self.binary:  # energizer monitor: contact open = fence fault
            v["is_fence"] = True
            self.attrs["door_active"] = {"milesight_role": "electric_fence", "device": self.entry.title,
                                         "area": self.entry.data.get("area"), "fault": v.get("door_active"),
                                         "since": v.get("door_since"), "fault_confirmed": bool(v.get("door_left_open"))}
        for prefix, (tr, cfg, key, ch) in self.loads.items():
            v.update(tr.values(ts, cfg, prefix))
            pl = _purposes.get(key)
            v[f"{prefix}label"] = ((pl.noun or pl.label) if pl else "Load") + (f" {ch}" if ch is not None else "")
            v[f"{prefix}group"] = pl.group if pl else None
            self.attrs[f"{prefix}run_today_h"] = {
                "milesight_role": "load", "device": self.entry.title, "area": self.entry.data.get("area"),
                "purpose": key, "purpose_label": pl.label if pl else None, "channel": ch,
                "group": pl.group if pl else None, "running": v.get(f"{prefix}running"),
                "duty_today": v.get(f"{prefix}duty_today"), "duty_24h": v.get(f"{prefix}duty_24h"),
                "starts_today": v.get(f"{prefix}starts_today"), "after_hours": v.get(f"{prefix}after_hours"),
                "ran_too_long": v.get(f"{prefix}ran_too_long"), "not_running": v.get(f"{prefix}not_running"),
                "service_due": v.get(f"{prefix}service_due")}
        if self.tempw is not None:
            v.update(self.tempw.values(ts, self.pcfg))
            self.attrs["temp_out_today"] = {
                "milesight_role": "cold_chain" if p and p.group == "cold_chain" else "temperature_watch",
                "device": self.entry.title, "area": self.entry.data.get("area"), "purpose": p.key if p else None,
                "purpose_label": label, "temperature": self._temp_value(v), "low": self.pcfg.get("temp_low"),
                "high": self.pcfg.get("temp_high"), "delay_min": self.pcfg.get("temp_delay_min"),
                "alarm": v.get("temp_alarm"), "excursions_today": v.get("temp_excursions_today"),
                "min_today": self.tempw.s["min"], "max_today": self.tempw.s["max"],
                "door_open": v.get("door_active"), "log": self.tempw.s["log"][-31:]}
            if p is not None and p.group == "cold_chain":
                v["temp_in_range_7d"] = self._in_range_7d(ts, v.get("temp_out_today"))
                acts = [x for x in self.meta.get("_service_log", []) if x.get("kind") == "corrective_action"]
                v["corrective_action"] = acts[-1]["text"] if acts else ""
                self.attrs["corrective_action"] = {"milesight_role": "corrective_action", "device": self.entry.title,
                                                   "actions": acts[-10:]}
                self.attrs["temp_out_today"]["in_range_7d"] = v["temp_in_range_7d"]
            self.attrs["temp_alarm"] = {"since": (self.tempw.s["alarm"] or {}).get("since"),
                                        "peak": (self.tempw.s["alarm"] or {}).get("peak")}
            # expose the alarm band on the temperature entity itself, so a gauge can draw green/amber/red zones
            band = {"alarm_low": self.pcfg.get("temp_low"), "alarm_high": self.pcfg.get("temp_high"),
                    "ms_limit_low": self.pcfg.get("temp_low"), "ms_limit_high": self.pcfg.get("temp_high"),
                    "min_today": self.tempw.s["min"], "max_today": self.tempw.s["max"]}
            band = {k: val for k, val in band.items() if val is not None}
            band["ms_trend"] = "cold_chain" if (p and p.group == "cold_chain") else "temperature"
            for _tk in ("temperature", "temperature_1"):
                if band:
                    self.attrs[_tk] = {**(self.attrs.get(_tk) or {}), **band}
        if self._pkey == "mains":
            v["mains_outage"] = self.meta.get("_zero_n", 0) >= 2
            self.attrs["mains_outage"] = {"milesight_role": "mains", "device": self.entry.title,
                                          "area": self.entry.data.get("area")}
            if "ct3" in self.model.features:
                ph = [v.get(f"current_{n}") for n in (1, 2, 3)]
                if all(isinstance(x, (int, float)) for x in ph):
                    mean = sum(ph) / 3
                    imb = round((max(ph) - min(ph)) / mean * 100, 0) if mean >= 2 else None
                    v["phase_imbalance"] = imb
                    v["phase_imbalance_high"] = bool(imb is not None and imb > 25)
                    self.attrs["mains_outage"].update(phase_imbalance=imb, currents=ph)
            if isinstance(v.get("current_total"), (int, float)):      # total site load (sum of phases)
                self.attrs["mains_outage"]["current_total"] = v["current_total"]
            if isinstance(v.get("power"), (int, float)):              # total kW, when the mains voltage is set
                self.attrs["mains_outage"]["power_w"] = v["power"]
        if self._pkey == "bin":
            fill = bin_fill(v.get("distance"), float(self.pcfg.get("bin_depth_mm") or 0))
            rate = self.trend.rate_per_h(ts, 24) if self.trend else None
            v["bin_fill"] = fill
            v["bin_full"] = bool(fill is not None and fill >= float(self.pcfg.get("full_pct") or 80))
            v["bin_fill_per_day"] = round(rate * 24, 0) if rate is not None and rate > 0 else (0 if rate is not None else None)
            v["bin_full_in"] = (round(max(0.0, float(self.pcfg.get("full_pct") or 80) - fill) / (rate * 24), 1)
                                if fill is not None and rate and rate > 0 else None)
        if self._pkey == "flood":
            lvl = water_level_cm(v.get("distance"), float(self.pcfg.get("empty_distance_mm") or 0))
            rate = self.trend.rate_per_h(ts, 1) if self.trend else None
            danger = float(self.pcfg.get("flood_danger_cm") or 0)
            v["water_level"] = lvl
            v["water_rise_rate"] = round(rate, 1) if rate is not None else None
            v["water_rising"] = bool(rate is not None and rate >= float(self.pcfg.get("rise_cm_h") or 10))
            v["water_danger"] = bool(lvl is not None and danger > 0 and lvl >= danger)
            self.attrs["water_level"] = {"milesight_role": "flood", "device": self.entry.title,
                                         "area": self.entry.data.get("area"), "level_cm": lvl,
                                         "rate_cm_h": v["water_rise_rate"], "rising": v["water_rising"],
                                         "danger": v["water_danger"], "danger_cm": danger or None,
                                         "empty_distance_mm": float(self.pcfg.get("empty_distance_mm") or 0) or None}
        if self._pkey == "rain_gauge" and isinstance(v.get("meter_reading"), (int, float)):
            mm = v["meter_reading"]
            day = self._day(ts)
            if self.meta.get("_rain_day") != day:
                self.meta["_rain_day"], self.meta["_rain_start"] = day, mm
            v["rain_today"] = round(max(0.0, mm - self.meta["_rain_start"]), 1)
            ch = self.trend.change(ts, 24) if self.trend else None
            v["rain_24h"] = round(max(0.0, ch), 1) if ch is not None else None
            self.attrs["rain_today"] = {"milesight_role": "rain_gauge", "device": self.entry.title,
                                        "rain_24h": v["rain_24h"]}
        if self._pkey == "toilet":
            n = self.meta.get("visits", 0)
            v["visits_since_clean"] = n
            v["clean_due"] = n >= int(self.pcfg.get("clean_visits") or 50)
        if self._pkey in ("panic", "service"):
            at = self.meta.get(f"{self._pkey}_at")
            v[f"{self._pkey}_active"] = bool(at and ts - at < float(self.pcfg.get("latch_min") or 30) * 60)
            self.attrs[f"{self._pkey}_active"] = {"pressed_at": datetime.fromtimestamp(at, self.cal.tz).isoformat(
                timespec="seconds") if at else None}
        if self.purpose is not None and self.pcfg.get("after_hours") and self._pfam & {"contact", "motion"}:
            at = self.meta.get("after_hours_at")
            if at and self._work_hours(ts):
                self.meta.pop("after_hours_at", None)
                at = None
            v["after_hours_activity"] = bool(at)
            self.attrs["after_hours_activity"] = {"at": datetime.fromtimestamp(at, self.cal.tz).isoformat(
                timespec="minutes") if at else None}
        if self._pkey in _purposes.SOIL_PURPOSES and isinstance(v.get("moisture"), (int, float)):
            self.attrs.setdefault("moisture", {})["milesight_role"] = "soil"

    def purpose_extra_specs(self) -> list:
        specs: list = []
        p = self.purpose
        if self.families & {"contact"} and "ts_contact" in self.model.features and "contact" in self._pfam:
            specs += contact_specs(p.door_noun, p.contact_class)
        for prefix, (tr, cfg, key, ch) in self.loads.items():
            pl = _purposes.get(key)
            title = (pl.noun or pl.label) if pl else "Load"
            if ch is not None:
                title = f"{title} (channel {ch})"
            specs += load_specs(prefix, title, cfg, mains=(key == "mains" and ch is None),
                                running=ch is not None or "load" not in self.model.features)
        if self.tempw is not None:
            specs += temp_specs(self.pcfg)
            if p is not None and p.group == "cold_chain":
                from .models import EntitySpec
                specs += [EntitySpec("temp_in_range_7d", "Time in range 7 days", unit="%", state_class="measurement",
                                     icon="mdi:shield-check-outline", precision=2),
                          EntitySpec("corrective_action", "Log corrective action", platform="text",
                                     icon="mdi:clipboard-edit-outline")]
        if p is not None:
            specs += purpose_specs(p.key, self.pcfg)
            if self.pcfg.get("after_hours") and self._pfam & {"contact", "motion"}:
                specs.append(_spec_after_hours())
        return specs

    def adjust_spec(self, spec):
        """How an entity looks for the device's purpose (Window instead of Door, a fridge icon …)."""
        p = self.purpose
        if p is None:
            return spec
        from dataclasses import replace
        k = spec.key
        if k.startswith("door_") and "contact" in self._pfam:
            name = spec.name.replace("Door", p.door_noun, 1)
            dc = p.contact_class if k == "door_active" and p.contact_class else spec.device_class
            return replace(spec, name=name, device_class=dc, icon=p.icon if k == "door_status" and p.icon else spec.icon)
        if k == "magnet_status" and "contact" in self._pfam:
            return replace(spec, name=p.door_noun, device_class=p.contact_class or spec.device_class)
        if k.startswith("load_") and "load" in self._pfam and p.noun and spec.name.startswith("Load"):
            return replace(spec, name=spec.name.replace("Load", p.noun, 1),
                           icon=p.icon if k == "load_status" and p.icon else spec.icon)
        if k in ("temperature", "temperature_1") and "temperature" in self._pfam and p.icon:
            return replace(spec, icon=p.icon)
        return spec

    def load_serviced(self, prefix: str) -> None:
        if prefix not in self.loads:
            raise ValueError("no service interval set")
        self.loads[prefix][0].serviced()
        self._publish(time.time())

    def purpose_clear(self, what: str) -> None:
        if what == "cleaned":
            self.meta["visits"] = 0
        else:
            self.meta.pop(f"{what}_at", None)
        self._publish(time.time())

    # ------------------------------------------------------------- pumps & pivots
    @staticmethod
    def _pump_amps(src: dict[str, Any]) -> float | None:
        """Pump current: the sum of the phases on a 3-channel clamp, else the single channel."""
        phases = [src[k] for k in ("current_1", "current_2", "current_3") if isinstance(src.get(k), (int, float))]
        if phases:
            return round(sum(phases), 3)
        v = src.get("current")
        return float(v) if isinstance(v, (int, float)) else None

    @staticmethod
    def _pump_energy(src: dict[str, Any]) -> float | None:
        if isinstance(src.get("energy"), (int, float)):
            return float(src["energy"])
        parts = [src[k] for k in ("energy_1", "energy_2", "energy_3") if isinstance(src.get(k), (int, float))]
        return round(sum(parts), 3) if parts else None

    def _pump_water(self) -> float | None:
        """The water meter entity chosen in the pump options, in m³ (L, gal and ft³ converted)."""
        eid = self._opt("pump_water_entity", None)
        st = self.hass.states.get(eid) if eid else None
        if st is None:
            return None
        try:
            val = float(st.state)
        except (TypeError, ValueError):
            return None
        unit = (st.attributes.get("unit_of_measurement") or "m³").strip()
        return val * {"L": 0.001, "l": 0.001, "gal": 0.00378541, "ft³": 0.0283168, "CCF": 2.83168}.get(unit, 1.0)

    def _pivot_events(self, events: list[dict[str, Any]]) -> None:
        for ev in events:
            self.hass.bus.async_fire(f"{DOMAIN}_pivot", {"deveui": self.deveui, "device": self.entry.title,
                                                        "area": self.entry.data.get("area"), **ev})

    def pivot_stopped(self) -> None:
        """'Pivot stopped' button: the round was ended on purpose (clears the stall alarm)."""
        if self.pivot is None:
            raise ValueError("no pivot centre configured")
        self.pivot.stop()
        self._publish(time.time())

    # ------------------------------------------------------------- tanks
    def _tank_litres(self, src: dict[str, Any]) -> tuple[float | None, float | None]:
        key = "depth" if self.tank_src == "depth" else "distance"
        lvl = level_mm(self.tank_cfg, self.tank_src, src.get(key))
        return lvl, (volume_l(self.tank_cfg, lvl) if lvl is not None else None)

    def _tank_reading(self, ts: float, decoded: dict[str, Any]) -> None:
        _, litres = self._tank_litres(decoded)
        if litres is None:
            return
        for ev in self.tank.update(self.tank_cfg, ts, litres):
            self.hass.bus.async_fire(f"{DOMAIN}_tank", {"deveui": self.deveui, "device": self.entry.title,
                                                         "area": self.entry.data.get("area"), **ev})

    def tank_refilled(self) -> None:
        """'Tank refilled' button: start the usage trend afresh and clear a sudden-drop alarm."""
        if self.tank is None:
            raise ValueError("no tank configured")
        self.tank.mark_refilled(time.time(), self._tank_litres(self.raw)[1])
        self._publish(time.time())

    def tank_clear_alarm(self) -> None:
        if self.tank is None:
            raise ValueError("no tank configured")
        self.tank.clear_alarm(time.time())
        self._publish(time.time())

    def _meter_value(self, v: dict[str, Any]) -> float | None:
        if self._meter_type() not in ("water", "gas", "energy", "rain"):
            return None
        src = self._opt(CONF_METER_SOURCE, "") or next(
            (k for k in ("pulse_count", "gpio_counter_1", "gpio_counter") if isinstance(v.get(k), (int, float))), None)
        pulses = v.get(src) if src else None
        if not isinstance(pulses, (int, float)):
            return None
        ppu = float(self._opt(CONF_METER_PPU, 1) or 1)
        return round(float(self._opt(CONF_METER_OFFSET, 0) or 0) + pulses / ppu, 3)

    async def async_fetch_history(self, start: float | None = None, end: float | None = None) -> None:
        """Ask the device to resend what it stored between start and end (default: last 24 hours)."""
        hist = downlinks(self.model.key).get("history") or {}
        end = end or time.time()
        start = start or end - 24 * 3600
        if hist.get("fetch"):
            payload = encode_fields(hist["fetch"], {"start": int(start), "end": int(end)})
        elif hist.get("fetch_since"):
            payload = encode_fields(hist["fetch_since"], {"start": int(start)})
        else:
            raise ValueError(f"{self.model.key} cannot resend stored data")
        await self._downlink(payload)
        self._remember("fetch_stored_data", payload, None, echo=False)
        self._publish(time.time())

    async def _safe_fetch(self, start: float, end: float) -> None:
        if not (downlinks(self.model.key).get("history") or {}).keys() & {"fetch", "fetch_since"}:
            return
        try:
            await self.async_fetch_history(start, end)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Automatic history fetch for %s failed", self.deveui, exc_info=True)

    # ------------------------------------------------------------ settings
    def _setting_values(self, setting: str, spec: dict) -> dict[str, Any]:
        vals = dict(self.meta.setdefault("settings", {}).get(setting, {}))
        for f in spec.get("fields", []):
            n = f["name"]
            if n.startswith("_") or "const" in f or "from" in f or n in vals:
                continue
            if "map" in f:
                vals[n] = "disable" if "disable" in f["map"] else next(iter(f["map"]))
            elif n == "max":
                vals[n] = f.get("max", 0)
            else:
                vals[n] = f.get("min", 0) if f.get("min", 0) > 0 or n == "min" else 0
        return vals

    async def async_setting(self, setting: str, field: str | None, value: Any) -> None:
        """On/off settings (field None, value bool) or one field of a multi-field setting."""
        if setting in ("history_enable", "history_retransmit"):
            spec = (downlinks(self.model.key).get("history") or {}).get(setting.removeprefix("history_"))
        else:
            spec = setting_spec(self.model.key, setting)
        if spec is None:
            raise ValueError(f"{self.model.key} has no setting {setting}")
        if field is None:
            payload = encode_template(spec["on" if value else "off"])
            await self._downlink(payload)
            self.meta.setdefault("settings", {})[setting] = bool(value)
        else:
            vals = self._setting_values(setting, spec)
            vals[field] = value
            payload = encode_fields(spec, vals)
            await self._downlink(payload)
            self.meta.setdefault("settings", {})[setting] = vals
        self._remember(setting, payload, None)
        self._publish(time.time())

    # ------------------------------------------------- command confirmation
    def _day(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, self.cal.tz).date().isoformat()

    def _remember(self, name: str, payload: bytes, value: Any, *, state: dict | None = None,
                  results: list | None = None, prev: dict | None = None, fport: int | None = None,
                  echo: bool = True, blocks: list | None = None) -> None:
        """Track a sent command until the device answers it (see link.PendingCommands)."""
        self.commands.add(name, payload, fport, time.time(), value=value, state=state, results=results, prev=prev,
                          confirmed=bool(self._opt(CONF_CONFIRMED_DOWNLINKS, False)), echo=echo, blocks=blocks)
        self.meta["last_command"] = f"{name.replace('_', ' ')}: pending"

    def _check_commands(self, raw_hex: str, decoded: dict[str, Any], ts: float) -> None:
        resend, done = self.commands.on_uplink(raw_hex, decoded, ts, int(self._opt(CONF_RETRIES, DEFAULT_RETRIES)))
        for item in resend:
            self.meta["last_command"] = f"{item['name'].replace('_', ' ')}: retrying ({item['attempts']})"
            self.hass.async_create_task(self._resend(item))
        for item in done:
            self._command_finished(item)

    async def _resend(self, item: dict[str, Any]) -> None:
        try:
            await self._downlink(bytes.fromhex(item["hex"]), item.get("fport"))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not resend %s to %s", item["name"], self.deveui, exc_info=True)

    def _command_finished(self, item: dict[str, Any]) -> None:
        name, status = item["name"], item["status"]
        if status in ("confirmed", "delivered") and item.get("value") is not None:
            self.meta.setdefault("config", {})[name] = item["value"]
            self.meta.setdefault("confirmed", {})[name] = True
        if status == "failed" and item.get("prev"):
            self.raw.update(item["prev"])                # undo the optimistic state
        if status == "failed" and item.get("blocks"):     # DS3604: the display does not show what was sent
            for tpl, block in item["blocks"]:
                self.display.get("sent", {}).get(str(tpl), {}).pop(block, None)
        tries = f" after {item['attempts']} attempts" if item["attempts"] > 1 else ""
        self.meta["last_command"] = f"{name.replace('_', ' ')}: {status}{tries}"
        self.hass.bus.async_fire(f"{DOMAIN}_command", {
            "deveui": self.deveui, "device": self.entry.title, "model": self.model.key, "command": name,
            "status": status, "attempts": item["attempts"], "detail": item.get("detail")})

    @callback
    def handle_notification(self, note: dict[str, Any]) -> None:
        """ACK / join / error notifications from the network server."""
        ts = time.time()
        kind = note.get("kind")
        if kind == "ack":
            self.meta["last_ack"] = "acknowledged" if note.get("acknowledged") else "not acknowledged"
            for item in self.commands.on_ack(bool(note.get("acknowledged")), ts):
                self._command_finished(item)
        elif kind == "join":
            self.meta["last_join"] = ts
            self.link.last_fcnt = None                   # frame counters restart after a join
            self.hass.bus.async_fire(f"{DOMAIN}_device_joined", {
                "deveui": self.deveui, "device": self.entry.title, "model": self.model.key})
        elif kind == "error":
            self.meta["last_network_error"] = note.get("error")
        self._publish(ts)

    # ------------------------------------------------------------ maintenance
    def _in_range_7d(self, ts: float, out_today: Any) -> float | None:
        """% of the last 7 days (6 logged days + today so far) the temperature was inside the allowed range."""
        log = self.tempw.s["log"][-6:]
        today_s = ts - self._day_start(ts)
        total_min = len(log) * 1440 + today_s / 60
        if total_min < 60:
            return None
        out = sum(d.get("out_min") or 0 for d in log) + (out_today or 0)
        return round(max(0.0, 100 - out / total_min * 100), 2)

    def log_service(self, kind: str, text: str, by: str | None = None, ts: float | None = None) -> None:
        """Service history of this device (battery replaced, firmware, settings profile, notes)."""
        log = self.meta.setdefault("_service_log", [])
        log.append({"at": ts or time.time(), "kind": kind, "text": text, "by": by})
        del log[:-50]
        self.store.async_delay_save(self._data_to_save, 5)

    def battery_replaced(self, by: str | None = None) -> None:
        """Batteries replaced by hand: restart the forecast and note it."""
        from .battery import BatteryForecast
        self.battery_fc = BatteryForecast({"replaced": self.battery_fc.replaced + [time.time()]})
        self.log_service("battery_replaced", "Battery replaced", by)
        self._publish(time.time())

    def _battery_reading(self, ts: float, decoded: dict[str, Any]) -> None:
        from .battery import pct_from_voltage
        pct = decoded.get("battery")
        if not isinstance(pct, (int, float)) and isinstance(decoded.get("battery_voltage"), (int, float)):
            pct = pct_from_voltage(decoded["battery_voltage"])
        if not isinstance(pct, (int, float)) or isinstance(pct, bool) or getattr(self, "battery_fc", None) is None:
            return
        day = datetime.fromtimestamp(ts, self.cal.tz).date().toordinal()
        if self.battery_fc.add(day, float(pct), ts):
            self.log_service("battery_replaced", f"Battery replaced (level jumped to {pct:g} %)", ts=ts)

    def _battery_values(self, v: dict[str, Any], ts: float) -> None:
        if getattr(self, "battery_fc", None) is None or not self.battery_fc.days:
            return
        from datetime import date as _date
        today = datetime.fromtimestamp(ts, self.cal.tz).date()
        per_day = self.battery_fc.days[-2][2] if len(self.battery_fc.days) > 1 else None
        fc = self.battery_fc.forecast(today.toordinal(), self.battery_low_pct, per_day)
        v["battery_days_left"] = fc["days_left"]
        when = None
        if fc["replace_on"] is not None:
            d = _date.fromordinal(fc["replace_on"])
            when = datetime(d.year, d.month, d.day, 12, tzinfo=self.cal.tz).timestamp()
        v["battery_replace_by"] = when
        last = fc.get("last_replaced")
        info = {"method": fc["method"], "reason": fc["reason"], "percent_per_month": fc["pct_per_month"],
                "days_of_history": fc["samples"], "low_at_percent": self.battery_low_pct,
                "last_replaced": datetime.fromtimestamp(last, self.cal.tz).date().isoformat() if last else None}
        self.attrs["battery_replace_by"] = info
        self.attrs["battery_days_left"] = info

    def _update_registry(self) -> None:
        """Keep firmware / hardware version on the device page up to date."""
        fw, hw = self.raw.get("firmware_version"), self.raw.get("hardware_version")
        if fw and self.meta.get("_fw_seen") and fw != self.meta["_fw_seen"]:
            self.log_service("firmware", f"Firmware {self.meta['_fw_seen']} → {fw}")
        if fw:
            self.meta["_fw_seen"] = fw
        if [fw, hw] == self.meta.get("_registry_versions") or not (fw or hw):
            return
        try:
            from homeassistant.helpers import device_registry as dr
            reg = dr.async_get(self.hass)
            device = reg.async_get_device(identifiers={(DOMAIN, self.deveui)})
            if device is not None:
                reg.async_update_device(device.id, sw_version=fw or device.sw_version, hw_version=hw or device.hw_version)
                self.meta["_registry_versions"] = [fw, hw]
        except Exception:  # noqa: BLE001 - registry not available (tests) or device not created yet
            return

    def _fire_button(self, key: str, event_type: str) -> None:
        ts = time.time()
        rec = self.meta.setdefault("_btn", {})
        day = time.strftime("%Y%m%d", time.localtime(ts))
        prev = rec.get(key) or {}
        rec[key] = {"type": event_type, "at": ts,
                    "count": (prev.get("count", 0) + 1) if prev.get("day") == day else 1, "day": day}
        if self._pkey in ("panic", "service"):
            self.meta[f"{self._pkey}_at"] = time.time()
            self.hass.bus.async_fire(f"{DOMAIN}_{self._pkey}", {"deveui": self.deveui, "device": self.entry.title,
                                                               "area": self.entry.data.get("area"),
                                                               "button": key, "event_type": event_type})
        async_dispatcher_send(self.hass, SIGNAL_EVENT.format(self.deveui), key, event_type)
        self.hass.bus.async_fire(f"{DOMAIN}_button", {
            "deveui": self.deveui, "device": self.entry.title, "model": self.model.key,
            "button": key, "event_type": event_type,
        })

    # --------------------------------------------------------------- control
    async def async_set_switch(self, key: str, on: bool) -> None:
        """Send a switch / socket command and show the new state until the device confirms it."""
        if not self.model.control:
            raise ValueError(f"{self.model.key} cannot be controlled")
        channel = int(key.rsplit("_", 1)[1])
        payload = encode_ws_switch(self.model.control, channel, on)
        await self._downlink(payload)
        self._remember(key, payload, None, state={key: on}, prev={key: self.raw.get(key)})
        self.raw[key] = on
        self._publish(time.time())

    async def async_climate(self, action: str, value: Any, **kw: Any) -> None:
        """Send a thermostat command (target / mode / power / fan) and show it until the device confirms."""
        kind = self.model.climate
        if not kind:
            raise ValueError(f"{self.model.key} has no thermostat control")
        if kind == "wt201v2" and action in ("mode", "power") and kw.get("target") is None:
            kw["target"] = self.values.get("target_temperature") or 21
        payload = encode_wt(kind, action, value, **kw)
        await self._downlink(payload)
        self._remember(f"thermostat_{action}", payload, None,
                       state={"target_temperature": value} if action == "target" else None)
        if action == "target":
            mode = kw.get("mode")
            if kind == "wt303":
                self.raw["cooling_target_temperature" if mode == "cool" else "heating_target_temperature"] = value
            self.raw["target_temperature"] = value
        elif action == "mode":
            self.raw["mode" if kind == "wt30x" else "temperature_control_mode"] = value
            self.raw["climate_on"] = True
            if "system_status" in self.raw:
                self.raw["system_status"] = True
        elif action == "power":
            self.raw["climate_on"] = bool(value)
            if "system_status" in self.raw:
                self.raw["system_status"] = bool(value)
        elif action == "fan":
            self.raw["fan_speed" if kind == "wt30x" else "fan_mode"] = value
        self._publish(time.time())

    async def _downlink(self, payload: bytes, fport: int | None = None) -> None:
        hubs = list(self.hass.data.get(DOMAIN, {}).get("hubs", {}).values())
        hub = next((h for h in hubs if self.deveui in h.last_uplink), hubs[0] if hubs else None)
        if hub is None:
            raise RuntimeError("No Milesight gateway configured")
        if fport is None:
            fport = downlinks(self.model.key).get("fport", 85)
        await hub.async_send_downlink(self.deveui, payload, fport,
                                      confirmed=bool(self._opt(CONF_CONFIRMED_DOWNLINKS, False)))

    async def async_send_raw(self, payload: bytes, fport: int | None = None) -> None:
        await self._downlink(payload, fport)

    async def async_modbus_push(self, commands: list, serial: bytes | None = None, fast_minutes: float = 0,
                                label: str = "") -> int:
        """Program Modbus channels on a UC100: the commands packed into downlinks (each tracked until the device
        echoes it). fast_minutes: report every minute meanwhile, so the queued downlinks go out sooner."""
        import asyncio
        from .modbus_config import FPORT, pack
        if serial:
            commands = [("modbus_serial_port", serial)] + list(commands)
        frames = pack(commands)
        for n, frame in enumerate(frames):
            await self._downlink(b"".join(cmd for _, cmd in frame), FPORT)
            for name, cmd in frame:
                self._remember(name, cmd, None, fport=FPORT)
            if n < len(frames) - 1:
                await asyncio.sleep(0.5)          # keep the gateway queue in order
        self.meta["modbus_push"] = {"label": label, "commands": len(commands), "downlinks": len(frames),
                                    "at": time.time()}
        if fast_minutes and "prefix" in (downlinks(self.model.key).get("report_interval") or {}):
            try:
                await self.async_walk_test(fast_minutes)
            except Exception:  # noqa: BLE001 - the channels are queued anyway
                _LOGGER.debug("Fast reporting not started for %s", self.deveui, exc_info=True)
        self._publish(time.time())
        await self.store.async_save(self._data_to_save())
        return len(frames)

    # ------------------------------------------------------- commissioning
    async def async_walk_test(self, minutes: float = 30) -> dict[str, Any]:
        """Fast reporting (every minute) for a walk test; the old interval comes back after `minutes`."""
        from .commissioning import default_interval, fast_interval
        spec = downlinks(self.model.key).get("report_interval")
        if not spec or "prefix" not in spec:
            raise ValueError(f"{self.model.key} cannot change its reporting interval – press its button to "
                             "make it report instead")
        fast, unit = fast_interval(spec)
        wt = self.meta.get("walk_test") or {}
        restore = wt.get("restore") or self.meta.get("config", {}).get("report_interval") or default_interval(unit)
        if restore == fast:                     # a test that never ended: don't make 1 minute the normal interval
            restore = default_interval(unit)
        await self.async_command("report_interval", fast)
        self.meta["walk_test"] = {"restore": restore, "fast": fast, "unit": unit, "until": time.time() + minutes * 60}
        self._schedule_walk_end()
        self._publish(time.time())
        return dict(self.meta["walk_test"])

    def _schedule_walk_end(self, min_delay: float = 1) -> None:
        from homeassistant.helpers.event import async_call_later
        if getattr(self, "_walk_unsub", None):
            self._walk_unsub()
        wt = self.meta.get("walk_test")
        if not wt:
            return

        async def _end(_now) -> None:
            self._walk_unsub = None
            try:
                await self.async_end_walk_test()
            except Exception:  # noqa: BLE001 - e.g. MQTT not up yet after a restart: try again in 5 minutes
                _LOGGER.warning("Could not restore the reporting interval of %s – retrying in 5 minutes",
                                self.deveui, exc_info=True)
                if self.meta.get("walk_test"):
                    self.meta["walk_test"]["until"] = time.time() + 300
                    self._schedule_walk_end()
        self._walk_unsub = async_call_later(self.hass, max(min_delay, wt["until"] - time.time()), _end)
        if not getattr(self, "_walk_cleanup", False):
            self._walk_cleanup = True
            self._unsubs.append(lambda: self._walk_unsub() if getattr(self, "_walk_unsub", None) else None)

    async def async_end_walk_test(self) -> int | None:
        wt = self.meta.get("walk_test")
        if getattr(self, "_walk_unsub", None):
            self._walk_unsub()
            self._walk_unsub = None
        if not wt:
            return None
        await self.async_command("report_interval", wt["restore"])      # raises → the test stays recorded
        self.meta.pop("walk_test", None)
        self._publish(time.time())
        return wt["restore"]

    def save_commissioning(self, result: dict[str, Any]) -> None:
        tests = list(self.meta.get("commissioning") or [])
        tests.append(result)
        self.meta["commissioning"] = tests[-10:]
        self._publish(time.time())

    async def async_command(self, name: str, value: float | None = None) -> None:
        """reboot | sync_time | report_status | report_interval | collection_interval (value in the spec's unit)."""
        dl = downlinks(self.model.key)
        if name == "sync_time" and "sync_time" not in dl and "set_time" in dl:
            name, value = "set_time", int(time.time())
        spec = dl.get(name)
        if spec is None:
            raise ValueError(f"{self.model.key} does not support {name}")
        payload = encode_template(spec, value)
        await self._downlink(payload)
        if value is not None and name.endswith("_interval"):
            self.meta.setdefault("config", {})[name] = value
            self.meta.setdefault("confirmed", {})[name] = False
        self._remember(name, payload, value if name.endswith("_interval") else None,
                       echo=name.endswith("_interval"))
        self._publish(time.time())

    async def async_set_label(self, key: str, value: str) -> None:
        """Store a custom name for a UC channel in the entry's options (the entry reloads and the cards pick it up)."""
        labels = dict(self.entry.options.get("uc_labels") or {})
        value = (value or "").strip()
        if value:
            labels[key] = value
        else:
            labels.pop(key, None)
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, "uc_labels": labels})

    async def async_output(self, key: str, action: str, value: float | None = None) -> None:
        """action: on | off | set (value) | on_for / off_for / open_for (value = duration) | open_until_pulses."""
        out = output_for_key(self.model.key, key)
        if out is None or action not in out:
            raise ValueError(f"{self.model.key}: {key} does not support {action}")
        payload = encode_template(out[action], value)
        await self._downlink(payload)
        prev = {key: self.raw.get(key)}
        if action in ("on", "off") and "set" in out:
            expect: Any = 100 if action == "on" else 0
        elif action == "set":
            expect = value
        else:
            expect = action not in ("off", "off_for")
        self._remember(f"{key} {action}", payload, None, state={key: expect}, prev=prev)
        if action in ("on", "off") and "set" in out:
            self.raw[key] = 100 if action == "on" else 0
        elif action in ("on", "off", "on_for", "open_for", "open_until_pulses"):
            self.raw[key] = action != "off"
        elif action == "off_for":
            self.raw[key] = False
        elif action == "set":
            self.raw[key] = value
        self._publish(time.time())

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
        if self.pivot is not None:
            self._pivot_events(self.pivot.check(self.pivot_cfg, ts))
        self._publish(ts)

    # ---------------------------------------------------------------- values
    def _hhmm(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, self.cal.tz).strftime("%H:%M")

    def _publish(self, ts: float) -> None:
        v: dict[str, Any] = dict(self.raw)
        v.update({k: val for k, val in self.meta.items() if k not in ("config", "pending", "confirmed", "settings", "walk_test", "commissioning")
                  and not k.startswith("_")})
        for k, val in self.meta.get("config", {}).items():
            v[f"cfg_{k}"] = val
        for k, val in self.meta.get("settings", {}).items():
            if isinstance(val, dict):
                for fk, fv in val.items():
                    v[f"set_{k}__{fk}"] = fv
            else:
                v[f"set_{k}"] = val

        self._link_values(v, ts)
        last = self.meta.get("last_seen")
        offline_s, interval_s, src = self._offline_threshold_s()
        v["online"] = (ts - last <= offline_s) if last else None            # unknown until the first uplink
        self.attrs["online"] = {
            "reports_every": _dur(interval_s), "offline_after": _dur(offline_s),
            "interval_source": {"measured": "measured from uplinks", "configured": "set via Home Assistant",
                                "default": "model default", "manual": "manual setting",
                                "none": "unknown"}.get(src, src),
            "interval_s": round(interval_s) if interval_s else None, "offline_after_s": round(offline_s),
            "reports_seen": len(self.meta.get("_gaps") or []) + (1 if last else 0),
        }
        if isinstance(v.get("battery"), (int, float)):
            v["battery_low"] = v["battery"] < self.battery_low_pct
        self._battery_values(v, ts)
        vib = self._vibration_assess(v)
        if vib is not None:
            v["vibration"] = vib["worst_value"]        # the worst-axis velocity; attrs carry the full verdict
            self.attrs["vibration"] = vib
            if vib.get("zone") in ("C", "D"):          # ISO 10816 unsatisfactory / unacceptable → an alert
                v["vib_alert"] = {"zone": vib["zone"], "verdict": vib.get("verdict"), "severity": vib.get("severity"),
                                  "value": vib.get("worst_value"), "axis": vib.get("worst_axis")}
        wx = self._weather_assess(v, ts)
        if wx is not None:
            v["weather"] = wx["temperature"]           # state = temperature; attrs carry the full conditions
            self.attrs["weather"] = wx
            if wx.get("wind_severity") in ("warning", "critical"):
                v["wx_wind"] = {"severity": wx["wind_severity"], "gust": wx.get("gust"), "unit": wx.get("wind_unit", "km/h")}
            if wx.get("pressure_severity") == "warning" or wx.get("forecast") == "stormy":
                v["wx_storm"] = {"trend": wx.get("pressure_trend"), "forecast": wx.get("forecast")}
        soil = self._soil_assess(v)
        if soil is not None:
            v["soil"] = soil["moisture"]               # state = moisture; attrs carry the full readings + status
            self.attrs["soil"] = soil
            _st = soil.get("status", {})               # alert only on the agronomic headliners (not every N/P/K reading)
            _sb = [{"key": k, "kind": _st.get(k), "value": soil.get(k)}
                   for k in ("moisture", "ph", "ec", "salinity") if _st.get(k) in ("high", "low")]
            if _sb:
                v["soil_breaches"] = _sb
        lvl = self._level_assess(v, ts)
        if lvl is not None:
            v["liquid_level"] = lvl["level_mm"]
            self.attrs["liquid_level"] = lvl
        if self.fixed_location() is not None:
            v["fixed_location"] = "fixed"
        fleet = (v["online"], v.get("battery_low"))
        if fleet != self._fleet_state:
            if self._fleet_state is not None and None not in (fleet[0], self._fleet_state[0]) \
                    and fleet[0] != self._fleet_state[0]:
                self.hass.bus.async_fire(f"{DOMAIN}_device_{'online' if fleet[0] else 'offline'}", {
                    "deveui": self.deveui, "device": self.entry.title, "model": self.model.key})
            self._fleet_state = fleet
            async_dispatcher_send(self.hass, SIGNAL_FLEET)
        if self.minmax is not None:
            for f in self.model.minmax_fields:
                v[f"{f}_min_today"] = self.minmax.get(ts, "min", f)
                v[f"{f}_max_today"] = self.minmax.get(ts, "max", f)
        if isinstance(v.get("temperature"), (int, float)) and isinstance(v.get("humidity"), (int, float)):
            v["feels_like"] = _heat_index(v["temperature"], v["humidity"])
        if "co2" in v:
            v["co2_status"] = _co2_text(v["co2"])
            co2_lim = self.limits.get("co2")        # tag CO₂ for the trendline grid; expose its limit to flash on
            self.attrs["co2"] = {**(self.attrs.get("co2") or {}), "ms_trend": "air",
                                 **({"ms_limit_high": co2_lim} if co2_lim else {})}
        air = self._air_monitor(v)                  # AM air-quality monitor: all properties on one card + a trend
        if air is not None:
            pm = next((m for m in air["metrics"] if m["key"] == air["primary"]), None)
            v["air_monitor"] = pm["value"] if pm else None
            self.attrs["air_monitor"] = air
            _ab = [{"label": m["label"], "value": m["value"], "unit": m["unit"], "limit": m["limit_high"]}
                   for m in air["metrics"] if m.get("status") == "high"]
            if _ab:
                v["air_breaches"] = _ab
        env = self._env_monitor(v)                  # multi-property environmental sensor: properties + door/leak/motion
        if env is not None:
            pm = next((m for m in env["metrics"] if m["key"] == env["primary"]), None)
            if pm is not None:
                v["env_monitor"] = pm["value"]
            else:                                   # no numeric reading (e.g. door + motion): headline the status
                active = next((s for s in env["states"] if s.get("active")), None)
                v["env_monitor"] = active["text"] if active else "Clear"
            self.attrs["env_monitor"] = env
        energy = self._energy_monitor(v)            # CT clamp: phase currents + total / power / imbalance
        if energy is not None:
            pm = next((m for m in energy["metrics"] if m["key"] == energy["primary"]), None)
            v["energy_monitor"] = pm["value"] if pm else None
            self.attrs["energy_monitor"] = energy
        gas = self._gas_monitor(v)                  # GS odour / vape detector: chips + odour / vape status
        if gas is not None:
            pm = next((m for m in gas["metrics"] if m["key"] == gas["primary"]), None)
            v["gas_monitor"] = pm["value"] if pm else None
            self.attrs["gas_monitor"] = gas
        if self.occupancy is not None:              # occupancy values must be in `v` before the space / workplace cards read them
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
        space = self._space(v, ts)                  # VS occupancy / people sensor → the Spaces + Occupancy cards
        if space is not None:
            v["space"] = space["occupied"]
            self.attrs["space"] = space
        work = self._workplace(v, ts)               # VS321 room sensor → the Workplace card (AM-style)
        if work is not None:
            pm = next((m for m in work["metrics"] if m["key"] == work["primary"]), None)
            v["workplace"] = pm["value"] if pm else None
            self.attrs["workplace"] = work
        em = self._em_reading(v)                    # EM500 single-reading sensor → the adaptive reading card
        if em is not None:
            v["em_reading"] = em["value"]
            self.attrs["em_reading"] = em
        em_soil = self._em_soil(v)                  # EM500-SMTC native soil probe → the shared Soil card
        if em_soil is not None:
            v["soil"] = em_soil["moisture"]
            self.attrs["soil"] = em_soil
        probe = self._temp_probe(v)                 # TS temperature probe → the Temperature-probe card
        if probe is not None:
            v["temp_probe"] = probe["probes"][0]["value"]
            self.attrs["temp_probe"] = probe
            breaches = [{"label": p["label"] or "Temperature", "tone": p["tone"], "value": p["value"], "badge": p["badge"]}
                        for p in probe["probes"] if p["tone"] in ("high", "low", "mutation")]
            if breaches:
                v["temp_breaches"] = breaches
            if any(e.get("active") and e.get("label") == "Tilt" for e in probe.get("extra", [])):
                v["probe_tilt"] = True
        scene = self._scene_panel(v)                # WS button / scene panel → the Scene-buttons card
        if scene is not None:
            v["scene_panel"] = scene["summary"]
            self.attrs["scene_panel"] = scene
        disp = self._display(v)                     # DS3604 e-ink display → the Display composer card
        if disp is not None:
            v["display"] = disp["active"]
            self.attrs["display"] = disp
        track = self._asset_tracker(v)              # AT101 GNSS / Wi-Fi tracker → the Asset-tracker card
        if track is not None:
            v["asset_tracker"] = track["motion_label"]
            self.attrs["asset_tracker"] = track
            if track["geofence"] == "outside":
                v["geofence_breach"] = True
            if track["tamper"]:                     # AT101 tamper is its own key (not the bool tamper_status WS/GS use)
                v["tracker_tamper"] = True
        supply = self._supplies(v, ts)              # WS201 consumables dispenser → the Supplies card
        if supply is not None:
            v["supplies"] = {"ok": "In stock", "low": "Low", "out": "Replace"}[supply["status"]]
            self.attrs["supplies"] = supply
            if supply["status"] == "out":
                v["supply_out"] = supply["remaining"]
            elif supply["status"] == "low":
                v["supply_low"] = supply["remaining"]
        ctrl = self._controller(v)                  # UC I/O controller → the Controller card
        if ctrl is not None:
            pm = next((m for m in ctrl["metrics"] if m["key"] == ctrl["primary"]), None)
            v["controller"] = pm["value"] if pm else (len(ctrl["outputs"]) or None)
            self.attrs["controller"] = ctrl
            for ch in ctrl["inputs"] + ctrl["outputs"] + ctrl["metrics"] + ctrl["counters"]:
                v[f"label_{ch['key']}"] = self._uc_label(ch["key"], "")
        valves = self._valve_controller(v)          # UC valve controller → the Valve card
        if valves is not None:
            v["valve_controller"] = sum(1 for vv in valves["valves"] if vv.get("open"))
            self.attrs["valve_controller"] = valves
            for vv in valves["valves"]:
                v[f"label_{vv['key'].removesuffix('_opening')}"] = self._uc_label(
                    vv["key"].removesuffix("_opening"), "")
        counter = self._people_counter(v)           # VS people counter → the People counter card
        if counter is not None:
            v["people_counter"] = counter["inside"]
            self.attrs["people_counter"] = counter
            if counter["over"]:
                v["capacity_alert"] = {"inside": counter["inside"], "capacity": counter["capacity"]}
        fall = self._fall_monitor(v)                # VS373 radar fall detection → the Fall / safety card
        if fall is not None:
            v["fall_monitor"] = fall["state"]
            self.attrs["fall_monitor"] = fall
        panel = self._switch_panel(v)               # WS558 / switch: channels + state for the Light card
        if panel is not None:
            v["switch_panel"] = sum(1 for c in panel["channels"] if c["on"] is True)
            self.attrs["switch_panel"] = panel
        snd = self._sound_assess(v, ts)             # WS302 sound: level, baseline, continuous-flow detection
        if snd is not None:
            v["sound_monitor"] = snd["level"]
            self.attrs["sound_monitor"] = snd
            if snd["flowing"]:                      # flag for the "water left running" alert
                v["sound_flow"] = {"db": snd["level"], "minutes": round(snd["flow_s"] / 60, 1),
                                   "alert": snd["alert"], "limit_min": snd["minutes"]}
        height = float(self._opt(CONF_INSTALL_HEIGHT_MM, 0) or 0)
        if "em400" in self.model.features and height > 0 and isinstance(v.get("distance"), (int, float)):
            # distance = sensor to surface; full when the surface reaches the sensor
            v["fill_level"] = round(max(0.0, min(100.0, (height - v["distance"]) / height * 100)), 0)

        for key, ch in self.channels.items():
            if key in v:
                v[key] = ch.apply(v[key])
                if ch.compass and isinstance(v[key], (int, float)):
                    v[f"{key}_compass"] = _compass_point(v[key])
        if self.tank is not None:
            lvl, litres = self._tank_litres(v)
            v["tank_level"] = lvl
            v.update(self.tank.values(self.tank_cfg, ts, litres))
            is_silo = self.tank_cfg.is_silo            # grain/feed → Farm; water/fuel/other → Water
            self.attrs["tank_volume"] = {"milesight_role": "tank", "device": self.entry.title,
                                         "area": self.entry.data.get("area"), "capacity_l": v["tank_capacity"],
                                         "shape": self.tank_cfg.shape, "fill": v["tank_fill"],
                                         "contents": self.tank_cfg.contents, "is_silo": is_silo,
                                         "usage_per_day": v["tank_usage_per_day"], "days_left": v["tank_days_left"],
                                         "low": v["tank_low"], "sudden_drop": v["tank_sudden_drop"],
                                         "free_l": v.get("tank_free"), "mass_t": v.get("tank_mass"),
                                         "empty_at": v.get("tank_empty_at"), "last_refill": v.get("tank_last_refill"),
                                         "last_refill_added_l": v.get("tank_last_refill_added"),
                                         "drop_amount_l": v.get("tank_drop_amount"),
                                         "low_pct": self.tank_cfg.low_pct}
            self.attrs["tank_last_refill"] = {"added_l": v.get("tank_last_refill_added")}
            self.attrs["tank_sudden_drop"] = {"amount_l": v.get("tank_drop_amount"),
                                              "window_min": self.tank_cfg.drop_minutes}
            # tag tank fill for the trendline grid (silo → its own grid on Farm); expose the low-level limit to flash
            self.attrs["tank_fill"] = {**(self.attrs.get("tank_fill") or {}), "ms_trend": "silo" if is_silo else "tank",
                                       **({"ms_limit_low": self.tank_cfg.low_pct} if self.tank_cfg.low_pct > 0 else {})}
        if "ct" in self.model.features:
            self._ct_values(v)
        if self.distance is not None:
            v.update(self.distance.values(ts))
        if self.pump is not None:
            v.update(self.pump.values(self.pump_cfg, ts, self._pump_energy(v), self._pump_water()))
            self.attrs["pump_run_hours"] = {"milesight_role": "pump", "device": self.entry.title,
                                            "area": self.entry.data.get("area"), "running": v["pump_running"],
                                            "starts_last_hour": v["pump_starts_last_hour"],
                                            "dry_run": v["pump_dry_run"], "overload": v["pump_overload"],
                                            "short_cycling": v["pump_short_cycling"],
                                            "normal_current": v["pump_normal_current"],
                                            "current": self._pump_amps(v)}
            self.attrs["pump_starts_last_hour"] = {"limit": self.pump_cfg.max_starts_hour}
            normal = v["pump_normal_current"]
            self.attrs["pump_dry_run"] = {"below_a": round(normal * self.pump_cfg.dry_pct / 100, 2) if normal else None}
            self.attrs["pump_overload"] = {"above_a": round(normal * self.pump_cfg.overload_pct / 100, 2)
                                           if normal else None}
        if self.pivot is not None:
            v.update(self.pivot.values(self.pivot_cfg, ts))
            self.attrs["pivot_progress"] = {"milesight_role": "pivot", "device": self.entry.title,
                                            "area": self.entry.data.get("area"), "angle": v["pivot_angle"],
                                            "status": v["pivot_status"], "speed": v["pivot_speed"],
                                            "finish_in_h": v["pivot_finish_in"], "direction": v["pivot_direction"],
                                            "sector": self.pivot_cfg.sector,
                                            "centre": [self.pivot_cfg.lat, self.pivot_cfg.lon]}
            # the pivot centre on the map card (any entity with latitude / longitude attributes is drawn)
            self.attrs["pivot_radius"] = {"latitude": self.pivot_cfg.lat, "longitude": self.pivot_cfg.lon,
                                          "role": "pivot centre"}
        meter = self._meter_value(v)
        if meter is not None:
            v["meter_reading"] = meter
        if self.counters is not None:
            v.update(self.counters.values(ts))
            if "people_in_today" in v and "people_out_today" in v:
                v["people_net_today"] = max(0, v["people_in_today"] - v["people_out_today"])
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

        self._purpose_values(v, ts)
        for option, val in _setpoints.device_values(self).items():
            v[_setpoints.key(option)] = val
        self.values = v
        sig = tuple(sorted(device_alerts(self.entry.title, self.deveui, v)))
        if sig != self._alert_sig:
            self._alert_sig = sig
            async_dispatcher_send(self.hass, SIGNAL_ALERTS)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.deveui))
        self.store.async_delay_save(self._data_to_save, 30)

    def _network_changed(self) -> None:
        """The device now reaches Home Assistant another way: refresh its connection label shortly."""
        try:
            from . import _schedule_sync
            _schedule_sync(self.hass)
        except Exception:  # noqa: BLE001 - labels are a convenience
            pass

    def _link_values(self, v: dict[str, Any], ts: float) -> None:
        """Signal quality per device and the command-confirmation state."""
        from .const import DOWNLINK_CHIRPSTACK
        from .models import NETWORK_SERVERS, network_of
        hubs = list(self.hass.data.get(DOMAIN, {}).get("hubs", {}).values())
        ns = network_of(self.meta.get("network_server"), dict(self.entry.data),
                        bool(hubs) and all(getattr(h, "downlink_format", None) == DOWNLINK_CHIRPSTACK for h in hubs))
        v["network_server"] = NETWORK_SERVERS[ns][0]
        self.attrs["network_server"] = {"network_server": ns}
        rssi, snr, sf = v.get("rssi"), v.get("snr"), self.meta.get("spreading_factor")
        heard = self.link.heard_by(ts, 24 * 3600)
        loss = self.link.loss() if self.link.day == self._day(ts) else None
        q = link_quality(rssi, snr, sf)
        v["signal_quality"] = q
        v["link_margin"] = link_margin(snr, sf)
        v["packet_loss_today"] = loss
        v["uplinks_today"] = self.link.received if self.link.day == self._day(ts) else 0
        if heard:
            v["gateway"] = heard[0]["name"]
            v["gateways_heard"] = len(heard)
        self.attrs["gateway"] = {"gateways": [{k: g.get(k) for k in ("name", "id", "rssi", "snr")} |
                                              {"last_heard": datetime.fromtimestamp(g["last_heard"], self.cal.tz)
                                               .isoformat(timespec="seconds")} for g in heard]}
        self.attrs["signal_quality"] = {"advice": link_advice(q, sf, loss, len(heard)), "spreading_factor": sf,
                                        "commissioning": (self.meta.get("commissioning") or [None])[-1],
                                        "walk_test_until": (datetime.fromtimestamp(self.meta["walk_test"]["until"],
                                                                                   self.cal.tz).isoformat(timespec="minutes")
                                                            if self.meta.get("walk_test") else None),
                                        "link_margin_db": v["link_margin"],
                                        "packet_loss_yesterday": self.link.loss_yesterday}
        last = self.commands.last
        v["command_status"] = last["status"] if last else None
        self.attrs["command_status"] = {"command": last["command"] if last else None,
                                        "attempts": last["attempts"] if last else None,
                                        "detail": last.get("detail") if last else None,
                                        "waiting": self.commands.summary(),
                                        "device_confirms_settings": self.commands.echoes}
        self.attrs["last_command"] = self.attrs["command_status"]
        if "ds3604" in self.model.features:
            for t in (1, 2):
                for b in DS3604_BLOCKS:
                    v[f"display_t{t}_{b}"] = self.display_text(t, b)

    def _ct_values(self, v: dict[str, Any]) -> None:
        volts = float(self._opt(CONF_MAINS_VOLTAGE, 0) or 0)
        chans = [k for k in CT_CURRENT_KEYS if isinstance(v.get(k), (int, float))]
        if "ct3" in self.model.features:
            chans = [k for k in chans if k != "current"]
            if chans:
                v["current_total"] = round(sum(v[k] for k in chans), 2)
        if volts > 0:
            pf = power_factor(dict(self.entry.options))
            for k in chans:                         # real power estimate: I × V × power factor (W); apparent: I × V
                v[k.replace("current", "apparent_power")] = round(v[k] * volts)
                v[k.replace("current", "power")] = round(v[k] * volts * pf)
            if "current_total" in v:
                v["apparent_power"] = round(v["current_total"] * volts)
                v["power"] = round(v["current_total"] * volts * pf)
            # no energy counter on the clamp: energy = cumulative current (Ah) × voltage × power factor
            for sfx in ("", "_1", "_2", "_3"):
                ah = v.get(f"total_current{sfx}")
                if isinstance(ah, (int, float)) and not isinstance(ah, bool) and f"energy{sfx}" not in self.raw:
                    v[f"energy{sfx}"] = energy_from_ah(ah, volts, pf)

    def _data_to_save(self) -> dict[str, Any]:
        trackers: dict[str, Any] = {k: t.s for k, t in self.binary.items()}
        if self.minmax is not None:
            trackers["minmax"] = self.minmax.s
        if self.occupancy is not None:
            trackers["occupancy"] = self.occupancy.s
        if self.distance is not None:
            trackers["distance"] = self.distance.s
        if self.counters is not None:
            trackers["counters"] = self.counters.s
        if self.tank is not None:
            trackers["tank"] = self.tank.s
        if self.pump is not None:
            trackers["pump"] = self.pump.s
        for prefix, (tr, *_rest) in self.loads.items():
            trackers[prefix] = tr.s
        if self.tempw is not None:
            trackers["tempwatch"] = self.tempw.s
        if self.trend is not None:
            trackers["trend"] = self.trend.to_dict()
        if getattr(self, "battery_fc", None) is not None and (self.battery_fc.days or self.battery_fc.replaced):
            trackers["battery_fc"] = self.battery_fc.to_dict()
        if self.pivot is not None:
            trackers["pivot"] = {**self.pivot.s, "centre": [self.pivot_cfg.lat, self.pivot_cfg.lon]}
        return {"raw": self.raw, "meta": self.meta, "trackers": trackers, "commands": self.commands.to_dict(),
                "link": self.link.to_dict(), "display": self.display}

    def diagnostics(self) -> dict[str, Any]:
        return {"model": self.model.key, "values": self.values, "state": self._data_to_save()}
