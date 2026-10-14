"""Device model registry and entity specifications (pure Python)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .decoders import (
    decode_am300,
    decode_em300,
    decode_em500,
    decode_em500_smtc,
    decode_ts60x,
    decode_ts101,
    decode_ts201,
    decode_ts301,
    decode_ts301_v1,
    decode_ts302,
    decode_ts302_v1,
    ts60x_parses_completely,
    decode_vs121,
    decode_vs321,
    decode_vs373,
    decode_vs_occupancy,
)


@dataclass(frozen=True)
class EntitySpec:
    """Describes one Home Assistant entity, independent of HA classes."""

    key: str                       # key in the runtime values dict
    name: str
    platform: str = "sensor"       # "sensor" | "binary_sensor"
    kind: str = "plain"            # plain | duration (s -> min) | timestamp (epoch) | text | label ("in_bed" -> "In bed")
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    diagnostic: bool = False
    enabled_default: bool = True
    precision: int | None = None


@dataclass(frozen=True)
class Model:
    key: str
    label: str
    decoder: Callable[[bytes], dict]
    features: frozenset[str] = field(default_factory=frozenset)
    beta: bool = False
    minmax_fields: tuple[str, ...] = ("temperature", "humidity")
    # occupancy: decoded payload -> people count (or 1/0 for presence sensors); None = not in this uplink
    occupancy_fn: Callable[[dict], int | None] | None = None
    counting: bool = True          # True = real people count, False = presence only
    defaults: tuple[tuple[str, object], ...] = ()   # values assumed until the device reports otherwise


_EM = frozenset({"env", "battery"})
_TS_DEF = (("temperature_alarm_active", False), ("humidity_alarm_active", False))
_TS2_DEF = (("temperature_1_alarm_active", False), ("temperature_2_alarm_active", False),
            ("humidity_1_alarm_active", False), ("humidity_2_alarm_active", False))
_TS60_DEF = _TS_DEF + (("tilt_alarm_active", False), ("light_alarm_active", False), ("battery_low_alarm", False))


def _count(d: dict) -> int | None:
    v = d.get("people_count_all")
    return v if isinstance(v, int) else None


def _presence(d: dict) -> int | None:
    return d["occupancy"] if "occupancy" in d else None


def _vs373_presence(d: dict) -> int | None:
    s = d.get("detection_status")
    return None if s in (None, "unknown") else int(s != "vacant")

_AM_MINMAX = ("temperature", "humidity", "co2", "pm2_5")
_AM_BASE = {"env", "pir", "light", "co2", "co2high", "tvoc", "pressure"}

MODELS: dict[str, Model] = {
    "VS121": Model("VS121", "VS121 AI people counter", decode_vs121, frozenset({"occupancy"}),
                   minmax_fields=(), occupancy_fn=_count),
    "VS321": Model("VS321", "VS321 AI occupancy & people counting (with temperature/humidity)", decode_vs321,
                   frozenset({"occupancy", "env", "battery", "illuminance", "regions10"}), occupancy_fn=_count),
    "VS340": Model("VS340", "VS340 desk/seat occupancy (PIR)", decode_vs_occupancy,
                   frozenset({"occupancy", "battery"}), minmax_fields=(), occupancy_fn=_presence, counting=False),
    "VS341": Model("VS341", "VS341 desk/seat occupancy (thermopile)", decode_vs_occupancy,
                   frozenset({"occupancy", "battery"}), minmax_fields=(), occupancy_fn=_presence, counting=False),
    "VS370": Model("VS370", "VS370 radar occupancy (with light level)", decode_vs_occupancy,
                   frozenset({"occupancy", "battery", "illuminance"}), minmax_fields=(), occupancy_fn=_presence,
                   counting=False),
    "EM500-CO2": Model("EM500-CO2", "EM500-CO2 CO2, temperature, humidity & pressure", decode_em500,
                       frozenset({"env", "battery", "co2", "co2high", "pressure"}),
                       minmax_fields=("temperature", "humidity", "co2")),
    "EM500-LGT": Model("EM500-LGT", "EM500-LGT light (lux)", decode_em500,
                       frozenset({"battery", "illumination"}), minmax_fields=("illumination",)),
    "EM500-PP": Model("EM500-PP", "EM500-PP pipe pressure", decode_em500,
                      frozenset({"battery", "pipe_pressure"}), minmax_fields=("pressure_kpa",)),
    "EM500-PT100": Model("EM500-PT100", "EM500-PT100 temperature probe", decode_em500,
                         frozenset({"battery", "temp_only", "sensor_error"}), minmax_fields=("temperature",)),
    "EM500-SMTC": Model("EM500-SMTC", "EM500-SMTC soil moisture, temperature & EC", decode_em500_smtc,
                        frozenset({"battery", "soil", "sensor_error"}),
                        minmax_fields=("temperature", "moisture", "electricity")),
    "EM500-SWL": Model("EM500-SWL", "EM500-SWL submersible water level", decode_em500,
                       frozenset({"battery", "depth", "sensor_error"}), minmax_fields=("depth",)),
    "EM500-UDL": Model("EM500-UDL", "EM500-UDL ultrasonic distance / level", decode_em500,
                       frozenset({"battery", "distance"}), minmax_fields=("distance",)),
    "TS101": Model("TS101", "TS101 insertion temperature", decode_ts101,
                   frozenset({"battery", "ts", "ts_temp"}), minmax_fields=("temperature",), defaults=_TS_DEF),
    "TS201": Model("TS201", "TS201 / TS201 v2 temperature (& humidity) probe", decode_ts201,
                   frozenset({"battery", "ts", "ts_temp", "ts_hum", "sensor_error"}), minmax_fields=("temperature", "humidity"), defaults=_TS_DEF),
    "TS301": Model("TS301", "TS301 temperature / contact probe (current firmware)", decode_ts301,
                   frozenset({"battery", "ts", "ts_temp", "ts_hum", "ts_contact", "sensor_error"}),
                   minmax_fields=("temperature", "humidity"), defaults=_TS_DEF),
    "TS301-V1": Model("TS301-V1", "TS301 temperature / contact probe (older firmware)", decode_ts301_v1,
                      frozenset({"battery", "ts", "ts_temp", "ts_contact"}), minmax_fields=("temperature",), defaults=_TS_DEF),
    "TS302": Model("TS302", "TS302 dual-probe temperature / contact (current firmware)", decode_ts302,
                   frozenset({"battery", "ts", "ts_dual", "ts_hum", "ts_contact", "sensor_error"}),
                   minmax_fields=("temperature_1", "temperature_2"), defaults=_TS2_DEF),
    "TS302-V1": Model("TS302-V1", "TS302 dual-probe temperature / contact (older firmware)", decode_ts302_v1,
                      frozenset({"battery", "ts", "ts_dual", "ts_contact"}), minmax_fields=("temperature_1", "temperature_2"), defaults=_TS2_DEF),
    "TS601": Model("TS601", "TS601 cold-chain temperature sensor", decode_ts60x,
                   frozenset({"battery", "ts60x", "sensor_error"}), minmax_fields=("temperature", "humidity"), defaults=_TS60_DEF),
    "TS602": Model("TS602", "TS602 cold-chain temperature & humidity sensor (display)", decode_ts60x,
                   frozenset({"battery", "ts60x", "sensor_error"}), minmax_fields=("temperature", "humidity"), defaults=_TS60_DEF),
    "VS373": Model("VS373", "VS373 radar fall detection", decode_vs373,
                   frozenset({"occupancy", "vs373"}), minmax_fields=(), occupancy_fn=_vs373_presence, counting=False),
    "EM300-TH": Model("EM300-TH", "EM300-TH temperature & humidity", decode_em300, _EM),
    "EM300-MCS": Model("EM300-MCS", "EM300-MCS magnetic contact (door/window)", decode_em300, _EM | {"door"}),
    "EM300-SLD": Model("EM300-SLD", "EM300-SLD spot leak detector", decode_em300, _EM | {"leak"}),
    "EM300-ZLD": Model("EM300-ZLD", "EM300-ZLD zone leak detector", decode_em300, _EM | {"leak"}),
    "EM300-DI": Model("EM300-DI", "EM300-DI digital input / pulse counter", decode_em300, _EM | {"input", "pulse"}),
    "AM307": Model("AM307", "AM307 / AM307L indoor air quality (7-in-1)", decode_am300,
                   frozenset(_AM_BASE | {"battery"}), minmax_fields=_AM_MINMAX[:3]),
    "AM308": Model("AM308", "AM308 / AM308L indoor air quality (9-in-1)", decode_am300,
                   frozenset(_AM_BASE | {"battery", "pm"}), minmax_fields=_AM_MINMAX),
    "AM319-HCHO": Model("AM319-HCHO", "AM319 HCHO / HCHO-IR / AM319L HCHO-IR (9-in-1)", decode_am300,
                        frozenset(_AM_BASE | {"pm", "hcho"}), minmax_fields=_AM_MINMAX),
    "AM319-HCHO-WELL": Model("AM319-HCHO-WELL", "AM319 HCHO (Well sensor)", decode_am300,
                             frozenset(_AM_BASE | {"pm25_only", "hcho"}), minmax_fields=_AM_MINMAX),
    "AM319-O3": Model("AM319-O3", "AM319 O3 / AM319L O3 (9-in-1)", decode_am300,
                      frozenset(_AM_BASE | {"pm", "o3"}), minmax_fields=_AM_MINMAX),
}

_AM_FIELDS = ("co2", "pm2_5", "pm10", "tvoc", "tvoc_iaq", "pressure", "hcho", "o3", "light_level")


def guess_model(raw: bytes | None) -> tuple[str | None, list[str]]:
    """Best guess + candidate list from a raw payload."""
    if not raw:
        return None, list(MODELS)
    vs = decode_vs121(raw)
    if "people_count_all" in vs:
        return "VS121", ["VS121"]
    v373 = decode_vs373(raw)
    if any(k in v373 for k in ("detection_status", "events", "respiratory_status", "region_1_type")) \
            or any(k.endswith("_out_of_bed_time") for k in v373):
        return "VS373", ["VS373"]
    v321 = decode_vs321(raw)
    if any(k in v321 for k in ("people_count_all", "region_1", "detection_status", "illuminance", "device_timestamp")):
        return "VS321", ["VS321"]
    ts = _guess_ts(raw)
    if ts:
        return ts
    vo = decode_vs_occupancy(raw)
    if "occupancy" in vo:
        if "illuminance" in vo:
            return "VS370", ["VS370", "TS302"]
        return "VS340", ["VS340", "VS341", "VS370", "TS301"]
    e5 = decode_em500(raw)
    if "co2" in e5 or "pressure" in e5:
        return "EM500-CO2", ["EM500-CO2"]
    if "illumination" in e5:
        return "EM500-LGT", ["EM500-LGT"]
    if "pressure_kpa" in e5:
        return "EM500-PP", ["EM500-PP"]
    if any(k in e5 for k in ("electricity", "electricity_error", "moisture", "moisture_error")):
        return "EM500-SMTC", ["EM500-SMTC"]
    if "depth" in e5 or "depth_error" in e5:
        return "EM500-SWL", ["EM500-SWL"]
    if "distance" in e5:
        return "EM500-UDL", ["EM500-UDL"]
    if "temperature_mutation" in e5 and "humidity" not in e5:
        return "EM500-PT100", ["EM500-PT100", "EM500-SMTC"]
    am = decode_am300(raw)
    if any(f in am for f in _AM_FIELDS):
        am_all = [k for k in MODELS if k.startswith("AM")]
        if "o3" in am:
            return "AM319-O3", ["AM319-O3"]
        if "hcho" in am:
            best = "AM319-HCHO" if "pm10" in am else "AM319-HCHO-WELL"
            return best, [best, "AM319-HCHO", "AM319-HCHO-WELL"]
        if "pm2_5" in am:
            return "AM308", ["AM308", "AM319-HCHO", "AM319-O3", "AM319-HCHO-WELL"]
        return "AM307", am_all
    em = decode_em300(raw)
    if "pulse_count" in em or "water" in em:
        return "EM300-DI", ["EM300-DI"]
    if "magnet_status" in em:
        return "EM300-MCS", ["EM300-MCS"]
    if "input_05" in em:
        return "EM300-SLD", ["EM300-SLD", "EM300-ZLD", "EM300-DI"]
    if "temperature" in em and "humidity" not in em:
        return "EM500-PT100", ["EM500-PT100", "TS101", "TS201", "TS301", "EM300-TH", "EM500-SMTC"]
    if "temperature" in em or "humidity" in em:
        return "EM300-TH", [k for k in MODELS if k.startswith("EM300")] + ["TS201"] + [k for k in MODELS if k.startswith("AM")]
    if ts60x_parses_completely(raw) and any(
            k in decode_ts60x(raw) for k in ("temperature", "humidity", "probe_connected", "latitude", "temperature_alarm_status")):
        return "TS601", ["TS601", "TS602"]
    return None, list(MODELS)


def _guess_ts(raw: bytes) -> tuple[str, list[str]] | None:
    """TS101 / TS201 / TS301 / TS302 signatures (channel format)."""
    older = bytes([0x93, 0xD7]) in raw or bytes([0x94, 0xD7]) in raw
    d2 = decode_ts302(raw)
    has_probe_value = any(k.startswith(("temperature", "humidity")) for k in d2)
    if has_probe_value and any(k in d2 for k in ("temperature_2", "humidity_2", "magnet_status_2")):
        return ("TS302-V1", ["TS302-V1", "TS302"]) if older else ("TS302", ["TS302", "TS302-V1"])
    d1 = decode_ts301(raw)
    if "magnet_status" in d1 and "temperature" in d1:
        return ("TS301-V1", ["TS301-V1", "TS301"]) if older else ("TS301", ["TS301", "TS301-V1"])
    if bytes([0x03, 0x9A]) in raw or any(k.endswith("_sensor_status") for k in d1):
        return "TS301", ["TS301", "TS201"]
    if any(k.endswith("_alarm_status") for k in d1):
        if older:
            return "TS301-V1", ["TS301-V1", "TS101", "TS302-V1"]
        return "TS301", ["TS301", "TS201", "TS101", "TS301-V1"]
    return None


# --------------------------------------------------------------------------
# Entity specs
# --------------------------------------------------------------------------
def _common() -> list[EntitySpec]:
    return [
        EntitySpec("rssi", "RSSI", unit="dBm", device_class="signal_strength",
                   state_class="measurement", diagnostic=True),
        EntitySpec("snr", "SNR", unit="dB", state_class="measurement", icon="mdi:access-point", diagnostic=True),
        EntitySpec("last_seen", "Last seen", kind="timestamp", device_class="timestamp", diagnostic=True),
    ]


def _env() -> list[EntitySpec]:
    t = dict(unit="°C", device_class="temperature", state_class="measurement")
    h = dict(unit="%", device_class="humidity", state_class="measurement")
    return [
        EntitySpec("temperature", "Temperature", **t),
        EntitySpec("humidity", "Humidity", **h),
        EntitySpec("feels_like", "Feels like", icon="mdi:thermometer-check", **t),
        EntitySpec("temperature_min_today", "Temperature min today", icon="mdi:thermometer-low", **t),
        EntitySpec("temperature_max_today", "Temperature max today", icon="mdi:thermometer-high", **t),
        EntitySpec("humidity_min_today", "Humidity min today", icon="mdi:water-minus", **h),
        EntitySpec("humidity_max_today", "Humidity max today", icon="mdi:water-plus", **h),
    ]


def _battery() -> list[EntitySpec]:
    return [EntitySpec("battery", "Battery", unit="%", device_class="battery", state_class="measurement", diagnostic=True)]


def _air(f: frozenset[str]) -> list[EntitySpec]:
    m = dict(state_class="measurement")
    specs: list[EntitySpec] = []
    if "pir" in f:
        specs.append(EntitySpec("pir", "Motion", platform="binary_sensor", device_class="motion"))
    if "light" in f:
        specs.append(EntitySpec("light_level", "Light level", icon="mdi:brightness-6", **m))
    if "co2" in f:
        specs += [
            EntitySpec("co2", "CO2", unit="ppm", device_class="carbon_dioxide", **m),
            EntitySpec("co2_status", "Air quality", kind="text", icon="mdi:air-filter"),
            EntitySpec("co2_max_today", "CO2 max today", unit="ppm", device_class="carbon_dioxide", icon="mdi:molecule-co2"),
        ]
    if "tvoc" in f:
        specs += [
            EntitySpec("tvoc_iaq", "TVOC index", icon="mdi:air-filter", precision=2, **m),
            EntitySpec("tvoc", "TVOC", unit="µg/m³", device_class="volatile_organic_compounds", enabled_default=False, **m),
        ]
    if "pressure" in f:
        specs.append(EntitySpec("pressure", "Pressure", unit="hPa", device_class="atmospheric_pressure", **m))
    if "pm" in f or "pm25_only" in f:
        specs += [
            EntitySpec("pm2_5", "PM2.5", unit="µg/m³", device_class="pm25", **m),
            EntitySpec("pm2_5_max_today", "PM2.5 max today", unit="µg/m³", device_class="pm25", icon="mdi:blur"),
        ]
    if "pm" in f:
        specs.append(EntitySpec("pm10", "PM10", unit="µg/m³", device_class="pm10", **m))
    if "hcho" in f:
        specs.append(EntitySpec("hcho", "Formaldehyde (HCHO)", unit="mg/m³", icon="mdi:chemical-weapon", precision=3, **m))
    if "o3" in f:
        specs.append(EntitySpec("o3", "Ozone", unit="ppm", icon="mdi:weather-hazy", precision=2, **m))
    if "co2high" in f:
        dur = dict(kind="duration", unit="min", device_class="duration", precision=1)
        specs += [
            EntitySpec("co2high_active", "CO2 high", platform="binary_sensor", device_class="problem", icon="mdi:molecule-co2"),
            EntitySpec("co2high_today_s", "CO2 above limit today", icon="mdi:calendar-today", state_class="total_increasing", **dur),
            EntitySpec("co2high_yesterday_s", "CO2 above limit yesterday", icon="mdi:calendar-arrow-left", **dur),
            EntitySpec("co2high_week_s", "CO2 above limit this week", icon="mdi:calendar-week", state_class="total_increasing", **dur),
            EntitySpec("co2high_month_s", "CO2 above limit this month", icon="mdi:calendar-month", state_class="total_increasing", **dur),
        ]
    if "pir" in f:
        specs.append(EntitySpec("buzzer", "Buzzer", platform="binary_sensor", diagnostic=True, enabled_default=False))
    return specs


def _measure(key: str, name: str, unit: str | None, device_class: str | None, icon: str | None = None,
             precision: int | None = None, minmax: bool = True) -> list[EntitySpec]:
    """A measurement plus its 'max today' / 'min today' companions."""
    base = dict(unit=unit, device_class=device_class, precision=precision)
    specs = [EntitySpec(key, name, state_class="measurement", icon=icon, **base)]
    if minmax:
        specs += [
            EntitySpec(f"{key}_max_today", f"{name} max today", icon="mdi:arrow-collapse-up", **base),
            EntitySpec(f"{key}_min_today", f"{name} min today", icon="mdi:arrow-collapse-down", **base),
        ]
    return specs


def _em500(f: frozenset[str]) -> list[EntitySpec]:
    specs: list[EntitySpec] = []
    if "illumination" in f:
        specs += _measure("illumination", "Illuminance", "lx", "illuminance")
    if "pipe_pressure" in f:
        specs += _measure("pressure_kpa", "Pressure", "kPa", "pressure", icon="mdi:gauge")
    if "temp_only" in f:
        specs += _measure("temperature", "Temperature", "°C", "temperature")
    if "soil" in f:
        specs += _measure("temperature", "Soil temperature", "°C", "temperature")
        specs += _measure("moisture", "Soil moisture", "%", "moisture", precision=1)
        specs += _measure("electricity", "Soil conductivity (EC)", "µS/cm", "conductivity", icon="mdi:flash-outline")
    if "depth" in f:
        specs += _measure("depth", "Water level", "cm", "distance", icon="mdi:waves-arrow-up")
    if "distance" in f:
        specs += _measure("distance", "Distance", "mm", "distance", icon="mdi:arrow-expand-vertical")
    if "sensor_error" in f:
        specs.append(EntitySpec("sensor_error", "Sensor status", kind="text", icon="mdi:alert-circle-outline", diagnostic=True))
    return specs


def _alarm(key: str, label: str, enabled: bool = True) -> list[EntitySpec]:
    return [
        EntitySpec(f"{key}_alarm_active", f"{label} alarm", platform="binary_sensor", device_class="problem",
                   enabled_default=enabled),
        EntitySpec(f"{key}_alarm_status", f"{label} alarm status", kind="label", icon="mdi:alarm-light-outline",
                   enabled_default=enabled),
    ]


def _ts(f: frozenset[str]) -> list[EntitySpec]:
    specs: list[EntitySpec] = []
    if "ts_temp" in f:
        specs += _measure("temperature", "Temperature", "°C", "temperature", precision=1)
        specs += _alarm("temperature", "Temperature")
        if "ts_hum" in f:
            specs += [EntitySpec("humidity", "Humidity", unit="%", device_class="humidity", state_class="measurement",
                                 enabled_default=False)]
            specs += _alarm("humidity", "Humidity", enabled=False)
        if "ts_contact" in f:
            specs.append(EntitySpec("magnet_status", "Contact", platform="binary_sensor", device_class="door",
                                    enabled_default=False))
    if "ts_dual" in f:
        for n in (1, 2):
            specs += _measure(f"temperature_{n}", f"Temperature {n}", "°C", "temperature", precision=1)
            specs += _alarm(f"temperature_{n}", f"Temperature {n}")
            if "ts_hum" in f:
                specs += [EntitySpec(f"humidity_{n}", f"Humidity {n}", unit="%", device_class="humidity",
                                     state_class="measurement", enabled_default=False)]
                specs += _alarm(f"humidity_{n}", f"Humidity {n}", enabled=False)
            specs.append(EntitySpec(f"magnet_status_{n}", f"Contact {n}", platform="binary_sensor", device_class="door",
                                    enabled_default=False))
    if "ts60x" in f:
        specs += _measure("temperature", "Temperature", "°C", "temperature", precision=1)
        specs += _measure("humidity", "Humidity", "%", "humidity", precision=1)
        specs += _alarm("temperature", "Temperature") + _alarm("humidity", "Humidity")
        specs += _alarm("tilt", "Tilt") + _alarm("light", "Light")
        specs += [
            EntitySpec("probe_connected", "Probe connected", platform="binary_sensor", device_class="connectivity"),
            EntitySpec("battery_low_alarm", "Battery low", platform="binary_sensor", device_class="battery"),
            EntitySpec("airplane_mode", "Airplane mode", platform="binary_sensor", icon="mdi:airplane", diagnostic=True,
                       enabled_default=False),
            EntitySpec("probe_type", "Probe type", diagnostic=True, icon="mdi:thermometer-probe", enabled_default=False),
            EntitySpec("latitude", "Latitude", unit="°", icon="mdi:crosshairs-gps", enabled_default=False, precision=6),
            EntitySpec("longitude", "Longitude", unit="°", icon="mdi:crosshairs-gps", enabled_default=False, precision=6),
        ]
        specs += [EntitySpec(f"angle_{a}", f"Angle {a.upper()}", unit="°", icon="mdi:angle-acute",
                             state_class="measurement", enabled_default=False) for a in "xyz"]
    return specs


def _vs373() -> list[EntitySpec]:
    dur = dict(kind="duration", unit="min", device_class="duration", precision=1)
    specs = [
        EntitySpec("alarm_fall", "Fall detected", platform="binary_sensor", device_class="safety", icon="mdi:human-handsdown"),
        EntitySpec("alarm_motionless", "Motionless alarm", platform="binary_sensor", device_class="problem"),
        EntitySpec("alarm_out_of_bed", "Out of bed alarm", platform="binary_sensor", device_class="problem", icon="mdi:bed-empty"),
        EntitySpec("alarm_dwell", "Dwell alarm", platform="binary_sensor", device_class="problem"),
        EntitySpec("alarm_lying_down", "Lying down alarm", platform="binary_sensor", device_class="problem"),
        EntitySpec("alarm_breathing", "Abnormal breathing", platform="binary_sensor", device_class="problem", icon="mdi:lungs"),
        EntitySpec("last_alarm", "Last alarm", kind="label", icon="mdi:alarm-light"),
        EntitySpec("last_alarm_at", "Last alarm time", kind="timestamp", device_class="timestamp"),
        EntitySpec("detection_status", "Room status", kind="label", icon="mdi:home-account"),
        EntitySpec("target_status", "Person status", kind="label", icon="mdi:human"),
        EntitySpec("respiratory_status", "Breathing", kind="label", icon="mdi:lungs"),
        EntitySpec("respiratory_rate", "Respiratory rate", unit="br/min", state_class="measurement", icon="mdi:lungs", precision=1),
        EntitySpec("use_time_now", "Room in use now", icon="mdi:timer-sand", **dur),
        EntitySpec("use_time_today", "Room in use today (device)", icon="mdi:calendar-today", **dur),
    ]
    for r in range(1, 7):
        specs.append(EntitySpec(f"region_{r}_occupancy", f"Region {r} occupied", platform="binary_sensor",
                                device_class="occupancy", enabled_default=False))
        specs.append(EntitySpec(f"region_{r}_out_of_bed_time", f"Region {r} out of bed", icon="mdi:bed-empty",
                                enabled_default=False, **dur))
    return specs


def _binary_event(prefix: str, noun: str, verb_on: str, device_class: str | None,
                  icon_on: str, with_left_open: bool) -> list[EntitySpec]:
    """Stats for a binary input. noun='Door', verb_on='open' -> 'Door open today'."""
    dur = dict(kind="duration", unit="min", device_class="duration", precision=1)
    cnt = dict(state_class="total_increasing", icon="mdi:counter")
    p = prefix
    specs = [
        EntitySpec(f"{p}active", noun, platform="binary_sensor", device_class=device_class),
        EntitySpec(f"{p}status", f"{noun} status", kind="text", icon=icon_on),
        EntitySpec(f"{p}current_s", f"{noun} {verb_on} duration", icon="mdi:timer-sand", **dur),
        EntitySpec(f"{p}since", f"{noun} {verb_on} since", kind="timestamp", device_class="timestamp", icon=icon_on),
        EntitySpec(f"{p}last_on_at", f"{noun} last {verb_on}", kind="timestamp", device_class="timestamp"),
        EntitySpec(f"{p}last_off_at", f"{noun} last cleared" if prefix == "leak_" else f"{noun} last closed",
                   kind="timestamp", device_class="timestamp"),
        EntitySpec(f"{p}last_duration_s", f"{noun} last {verb_on} duration", icon="mdi:history", **dur),
        EntitySpec(f"{p}today_s", f"{noun} {verb_on} today", icon="mdi:calendar-today", state_class="total_increasing", **dur),
        EntitySpec(f"{p}yesterday_s", f"{noun} {verb_on} yesterday", icon="mdi:calendar-arrow-left", **dur),
        EntitySpec(f"{p}week_s", f"{noun} {verb_on} this week", icon="mdi:calendar-week", state_class="total_increasing", **dur),
        EntitySpec(f"{p}last_week_s", f"{noun} {verb_on} last week", icon="mdi:calendar-week-begin", **dur),
        EntitySpec(f"{p}month_s", f"{noun} {verb_on} this month", icon="mdi:calendar-month", state_class="total_increasing", **dur),
        EntitySpec(f"{p}last_month_s", f"{noun} {verb_on} last month", icon="mdi:calendar-month-outline", **dur),
        EntitySpec(f"{p}count_today", f"{noun} events today", **cnt),
        EntitySpec(f"{p}count_yesterday", f"{noun} events yesterday", icon="mdi:counter"),
        EntitySpec(f"{p}count_week", f"{noun} events this week", **cnt),
        EntitySpec(f"{p}count_last_week", f"{noun} events last week", icon="mdi:counter"),
        EntitySpec(f"{p}count_month", f"{noun} events this month", **cnt),
        EntitySpec(f"{p}count_last_month", f"{noun} events last month", icon="mdi:counter"),
        EntitySpec(f"{p}longest_today_s", f"{noun} longest {verb_on} today", icon="mdi:timer-alert-outline", **dur),
        EntitySpec(f"{p}longest_week_s", f"{noun} longest {verb_on} this week", icon="mdi:timer-alert-outline", **dur),
        EntitySpec(f"{p}avg_today_s", f"{noun} average {verb_on} today", icon="mdi:timer-outline", **dur),
    ]
    if with_left_open:
        specs.insert(1, EntitySpec(f"{p}left_open", f"{noun} left {verb_on}", platform="binary_sensor",
                                   device_class="problem", icon=icon_on))
    return specs


def _occupancy(counting: bool = True) -> list[EntitySpec]:
    specs = _occupancy_all()
    if counting:
        return specs
    people_only = {"people_count_all", "region_count", "occ_peak_today", "occ_peak_today_at", "occ_peak_yesterday",
                   "occ_person_minutes_today", "occ_person_minutes_yesterday", "occ_avg_people_today"}
    return [s for s in specs if s.key not in people_only]


def _occupancy_all() -> list[EntitySpec]:
    dur = dict(kind="duration", unit="min", device_class="duration", precision=1)
    return [
        EntitySpec("occ_occupied", "Occupied", platform="binary_sensor", device_class="occupancy"),
        EntitySpec("occ_status", "Occupancy status", kind="text", icon="mdi:account-group"),
        EntitySpec("people_count_all", "People count", state_class="measurement", icon="mdi:account-group"),
        EntitySpec("region_count", "Region count", icon="mdi:account-eye", enabled_default=False),
        EntitySpec("occ_occupied_since", "Occupied since", kind="timestamp", device_class="timestamp", icon="mdi:clock-start"),
        EntitySpec("occ_occupied_duration_s", "Occupied duration", icon="mdi:timer-sand", **dur),
        EntitySpec("occ_last_session_s", "Last session", icon="mdi:history", **dur),
        EntitySpec("occ_longest_session_today_s", "Longest session today", icon="mdi:timer-alert-outline", **dur),
        EntitySpec("occ_occupied_today_s", "Occupied today", icon="mdi:calendar-today", state_class="total_increasing", **dur),
        EntitySpec("occ_occupied_yesterday_s", "Occupied yesterday", icon="mdi:calendar-arrow-left", **dur),
        EntitySpec("occ_sessions_today", "Sessions today", state_class="total_increasing", icon="mdi:counter"),
        EntitySpec("occ_sessions_yesterday", "Sessions yesterday", icon="mdi:counter"),
        EntitySpec("occ_peak_today", "Peak people today", icon="mdi:account-multiple-plus"),
        EntitySpec("occ_peak_today_at", "Peak people time", kind="timestamp", device_class="timestamp",
                   icon="mdi:clock-star-four-points-outline"),
        EntitySpec("occ_peak_yesterday", "Peak people yesterday", icon="mdi:account-multiple"),
        EntitySpec("occ_person_minutes_today", "Person-minutes today", unit="person-min",
                   state_class="total_increasing", icon="mdi:account-clock"),
        EntitySpec("occ_person_minutes_yesterday", "Person-minutes yesterday", unit="person-min",
                   icon="mdi:account-clock-outline"),
        EntitySpec("occ_avg_people_today", "Average people when occupied", unit="people", icon="mdi:account-group-outline"),
        EntitySpec("occ_utilisation_today_pct", "Utilisation today", unit="%", state_class="measurement",
                   icon="mdi:chart-donut", precision=1),
        EntitySpec("occ_utilisation_yesterday_pct", "Utilisation yesterday", unit="%", icon="mdi:chart-donut-variant",
                   precision=1),
    ]


def entity_specs(model_key: str) -> list[EntitySpec]:
    model = MODELS[model_key]
    f = model.features
    specs: list[EntitySpec] = []
    if "occupancy" in f:
        specs += _occupancy(model.counting)
    if "illuminance" in f:
        specs.append(EntitySpec("illuminance", "Light", kind="label", icon="mdi:brightness-6"))
    if "regions10" in f:
        specs += [EntitySpec(f"region_{r}", f"Region {r} occupied", platform="binary_sensor",
                             device_class="occupancy", enabled_default=False) for r in range(1, 11)]
    if "vs373" in f:
        specs += _vs373()
    specs += _em500(f)
    if "ts" in f or "ts60x" in f:
        specs += _ts(f)
    if "env" in f:
        specs += _env()
    if "battery" in f:
        specs += _battery()
    specs += _air(f)
    if "door" in f:
        specs += _binary_event("door_", "Door", "open", "door", "mdi:door-open", with_left_open=True)
    if "leak" in f:
        specs += _binary_event("leak_", "Leak", "active", "moisture", "mdi:water-alert", with_left_open=False)
    if "input" in f:
        specs += _binary_event("input_", "Input", "high", None, "mdi:electric-switch", with_left_open=False)
    if "pulse" in f:
        specs.append(EntitySpec("pulse_count", "Pulse count", state_class="total_increasing", icon="mdi:counter"))
        specs.append(EntitySpec("water", "Water (converted)", state_class="total_increasing", icon="mdi:water",
                                enabled_default=False))
    return specs + _common()
