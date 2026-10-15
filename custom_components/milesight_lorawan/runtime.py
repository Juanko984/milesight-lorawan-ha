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

from .analytics import BinaryEventTracker, Calendar, CounterTracker, DistanceTracker, MinMaxTracker, OccupancyTracker
from .const import (
    CONF_BATTERY_LOW,
    CONF_CONFIRMED_DOWNLINKS,
    CONF_DISPLAY_MAX_BYTES,
    CONF_RETRIES,
    DEFAULT_DISPLAY_MAX_BYTES,
    DEFAULT_RETRIES,
    SIGNAL_NOTIFY,
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
    CONF_OPEN_DAYS,
    CONF_OPEN_HOUR,
    DEFAULT_BATTERY_LOW,
    DEFAULT_CLOSE_HOUR,
    DEFAULT_CO2_LIMIT,
    DEFAULT_EMPTY_GRACE_MIN,
    DEFAULT_LEFT_OPEN_MIN,
    DEFAULT_MAX_GAP_MIN,
    DEFAULT_OPEN_DAYS,
    DEFAULT_OPEN_HOUR,
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
from .models import MODELS, Model, downlinks, entity_specs, meter_spec, output_for_key, setting_spec

_LOGGER = logging.getLogger(__name__)

# decoded keys that are not device state (lists / nested structures handled separately)
_NOT_RAW = ("history", "events", "wifi", "button_events", "template_1", "template_2", "update_content_result")
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
        self.distance: DistanceTracker | None = None
        self.counters: CounterTracker | None = None
        self.commands = PendingCommands()
        self.link = LinkStats()
        self.display: dict[str, Any] = {}           # DS3604: {"sent": {tpl: {block: text}}, "reported": {...}}
        self.attrs: dict[str, dict[str, Any]] = {}  # extra state attributes per entity key
        self._unsubs: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ setup
    def _opt(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.raw = data.get("raw", {})
        self.meta = data.get("meta", {})
        self.commands = PendingCommands(data["commands"]) if "commands" in data else PendingCommands.from_meta(self.meta)
        self.link = LinkStats(data.get("link"))
        self.display = data.get("display", {})
        trackers = data.get("trackers", {})
        f = self.model.features
        max_gap_s = float(self._opt(CONF_MAX_GAP_MIN, DEFAULT_MAX_GAP_MIN)) * 60
        self.max_gap_s = max_gap_s
        self.battery_low_pct = float(self._opt(CONF_BATTERY_LOW, DEFAULT_BATTERY_LOW))
        self._fleet_state: tuple | None = None

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
        if "at101" in f:
            self.distance = DistanceTracker(self.cal, trackers.get("distance"))
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
        if up.sf is not None:
            self.meta["spreading_factor"] = up.sf
        if up.frequency is not None:
            self.meta["frequency"] = round(up.frequency / 1e6, 3)
        if up.fcnt is not None:
            self.meta["frame_counter"] = up.fcnt
        self._handle_display(decoded)
        prev_seen = self.meta.get("last_seen")
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
        self._check_commands(up.raw.hex() if up.raw else "", decoded, ts)
        self._update_registry()

        for feature, tracker in self.binary.items():
            src = self.raw if feature in LATCHED_FEATURES else decoded
            tracker.update(ts, BINARY_FEATURES[feature][0](src, self.limits))
        if self.counters is not None:
            self.counters.update(ts, decoded)
        if self.distance is not None and "latitude" in decoded:
            self.distance.update(ts, decoded.get("latitude"), decoded.get("longitude"))
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
        """Entities that depend on the device's options (utility meter from a pulse counter)."""
        mtype = self._opt(CONF_METER_TYPE, "none")
        if mtype in ("water", "gas", "energy"):
            return [meter_spec(mtype, self._opt(CONF_METER_UNIT, {"water": "m³", "gas": "m³", "energy": "kWh"}[mtype]))]
        return []

    def _meter_value(self, v: dict[str, Any]) -> float | None:
        if self._opt(CONF_METER_TYPE, "none") not in ("water", "gas", "energy"):
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

    def _update_registry(self) -> None:
        """Keep firmware / hardware version on the device page up to date."""
        fw, hw = self.raw.get("firmware_version"), self.raw.get("hardware_version")
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
        self._publish(ts)

    # ---------------------------------------------------------------- values
    def _hhmm(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, self.cal.tz).strftime("%H:%M")

    def _publish(self, ts: float) -> None:
        v: dict[str, Any] = dict(self.raw)
        v.update({k: val for k, val in self.meta.items() if k not in ("config", "pending", "confirmed", "settings")
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
        v["online"] = (ts - last <= self.max_gap_s) if last else None       # unknown until the first uplink
        if isinstance(v.get("battery"), (int, float)):
            v["battery_low"] = v["battery"] < self.battery_low_pct
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
        height = float(self._opt(CONF_INSTALL_HEIGHT_MM, 0) or 0)
        if "em400" in self.model.features and height > 0 and isinstance(v.get("distance"), (int, float)):
            # distance = sensor to surface; full when the surface reaches the sensor
            v["fill_level"] = round(max(0.0, min(100.0, (height - v["distance"]) / height * 100)), 0)

        if "ct" in self.model.features:
            self._ct_values(v)
        if self.distance is not None:
            v.update(self.distance.values(ts))
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

    def _link_values(self, v: dict[str, Any], ts: float) -> None:
        """Signal quality per device and the command-confirmation state."""
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
        if self.distance is not None:
            trackers["distance"] = self.distance.s
        if self.counters is not None:
            trackers["counters"] = self.counters.s
        return {"raw": self.raw, "meta": self.meta, "trackers": trackers, "commands": self.commands.to_dict(),
                "link": self.link.to_dict(), "display": self.display}

    def diagnostics(self) -> dict[str, Any]:
        return {"model": self.model.key, "values": self.values, "state": self._data_to_save()}
