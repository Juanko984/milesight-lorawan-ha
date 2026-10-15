"""Device model registry and entity specifications (pure Python)."""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Callable

from .decoders import (
    decode_am300,
    decode_at101,
    decode_ct10x,
    decode_ct30x,
    decode_em300,
    decode_em400,
    decode_em500,
    decode_em500_smtc,
    decode_gs101,
    decode_gs301,
    decode_gs524n,
    decode_gs601,
    gs601_parses_completely,
    decode_ts60x,
    decode_uc11n1,
    decode_uc11t1,
    decode_uc11xx,
    decode_uc50x,
    decode_uc51x,
    decode_uc100,
    decode_uc100_v2,
    decode_uc300,
    decode_uc521,
    decode_ts101,
    decode_ts201,
    decode_ts301,
    decode_ts301_v1,
    decode_ts302,
    decode_ts302_v1,
    ts60x_parses_completely,
    decode_vs121,
    decode_am102,
    decode_am103,
    decode_am104,
    decode_am107,
    decode_am304l,
    decode_am305l,
    decode_ds3604,
    decode_em300_cl,
    decode_em300_mld,
    decode_em310_tilt,
    decode_em320_tilt,
    decode_em310_udl,
    decode_em320_th_v2,
    decode_em410_rdl,
    decode_em411_rdl,
    decode_vs132,
    decode_vs133,
    decode_vs135,
    decode_vs330,
    decode_vs350,
    decode_vs351,
    decode_vs360,
    cth01_parses_cleanly,
    decode_cth01,
    wt102_parses_completely,
    wt303_parses_completely,
    wt401_parses_completely,
    decode_wt101,
    decode_wt102,
    decode_wt201,
    decode_wt201_v2,
    decode_wt30x,
    decode_wt303,
    decode_wt401,
    ws_power_channels,
    decode_ws101,
    decode_ws136,
    decode_ws156,
    decode_ws201,
    decode_ws202,
    decode_ws203,
    decode_ws301,
    decode_ws302,
    decode_ws303,
    decode_ws501,
    decode_ws502,
    decode_ws503,
    decode_ws501_v4,
    decode_ws502_v4,
    decode_ws503_v4,
    decode_ws52x,
    decode_ws52x_v3,
    decode_ws558,
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
    dynamic: bool = False          # entities are created per channel as data arrives (configurable controllers)
    buttons: tuple[str, ...] = ()  # event entities (button presses)
    event_types: tuple[str, ...] = ()
    control: str | None = None     # downlink encoder kind for switch entities (see decoders.encode_ws_switch)
    gangs: int = 0                 # number of switchable channels (switch_1 .. switch_n)
    climate: str | None = None     # thermostat encoder kind (see decoders.encode_wt)
    counters: tuple[str, ...] = ()  # per-report counts summed per day / week / month (people counters)


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

_GS601_DEF = tuple((f"{k}_alarm_active", False) for k in ("vaping_index", "pm1_0", "pm2_5", "pm10", "temperature", "tvoc")) \
    + (("vaping_interference", False), ("burning_alarm", False), ("tamper_status", False))
_PRESS3 = ("short_press", "double_press", "long_press")
_PANEL = tuple(f"button_{n}" for n in range(1, 7))


def _ws_switch(key: str, label: str, decoder, gangs: int, control: str, meter: bool = False,
               extra: frozenset[str] = frozenset()) -> "Model":
    f = {"switch"} | ({"meter"} if meter else set()) | set(extra)
    if gangs == 1:
        f.add("on")
    return Model(key, label, decoder, frozenset(f), minmax_fields=("power",) if meter else (), control=control,
                 gangs=gangs)


_CT1 = frozenset({"ct", "load", "sensor_error"})
_CT3 = frozenset({"ct", "ct3", "load", "sensor_error"})
_CT1_DEF = (("current_alarm_active", False), ("temperature_alarm_active", False))
_CT3_DEF = tuple((f"current_{n}_alarm_active", False) for n in (1, 2, 3)) + (("temperature_alarm_active", False),)
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
    "EM400-UDL": Model("EM400-UDL", "EM400-UDL ultrasonic distance / level", decode_em400,
                       frozenset({"battery", "em400"}), minmax_fields=("distance", "temperature"),
                       defaults=(("distance_alarm_active", False), ("temperature_alarm_active", False))),
    "EM400-TLD": Model("EM400-TLD", "EM400-TLD trash bin fill level", decode_em400,
                       frozenset({"battery", "em400", "fill"}), minmax_fields=("distance", "temperature"),
                       defaults=(("distance_alarm_active", False), ("temperature_alarm_active", False))),
    "EM400-MUD": Model("EM400-MUD", "EM400-MUD multifunctional ultrasonic distance", decode_em400,
                       frozenset({"battery", "em400", "fill"}), minmax_fields=("distance", "temperature"),
                       defaults=(("distance_alarm_active", False), ("temperature_alarm_active", False))),
    "CT101": Model("CT101", "CT101 smart current transformer", decode_ct10x, _CT1, minmax_fields=("current",),
                   defaults=_CT1_DEF),
    "CT103": Model("CT103", "CT103 smart current transformer", decode_ct10x, _CT1, minmax_fields=("current",),
                   defaults=_CT1_DEF),
    "CT105": Model("CT105", "CT105 smart current transformer", decode_ct10x, _CT1, minmax_fields=("current",),
                   defaults=_CT1_DEF),
    "CT303": Model("CT303", "CT303 3-channel smart current transformer", decode_ct30x, _CT3,
                   minmax_fields=("current_1", "current_2", "current_3"), defaults=_CT3_DEF),
    "CT305": Model("CT305", "CT305 3-channel smart current transformer", decode_ct30x, _CT3,
                   minmax_fields=("current_1", "current_2", "current_3"), defaults=_CT3_DEF),
    "CT310": Model("CT310", "CT310 3-channel smart current transformer", decode_ct30x, _CT3,
                   minmax_fields=("current_1", "current_2", "current_3"), defaults=_CT3_DEF),
    "GS101": Model("GS101", "GS101 gas detector (valve / relay output)", decode_gs101, frozenset({"gs101", "gas"}),
                   minmax_fields=(), defaults=(("device_fault", False), ("end_of_life", False))),
    "GS301": Model("GS301", "GS301 bathroom odour detector (NH3 / H2S)", decode_gs301,
                   frozenset({"env", "battery", "gs301", "sensor_error"}), minmax_fields=("temperature", "humidity", "nh3", "h2s")),
    "GS524N": Model("GS524N", "GS524N smoke detector", decode_gs524n, frozenset({"gs524n", "smoke", "battery"}),
                    minmax_fields=(), defaults=(("smoke_alarm", False), ("battery_low_alarm", False), ("removed", False),
                                                ("device_fault", False))),
    "GS601": Model("GS601", "GS601 vape detector", decode_gs601,
                   frozenset({"gs601", "vape", "env", "battery", "occupancy", "sensor_error"}),
                   minmax_fields=("temperature", "humidity", "vaping_index", "pm2_5", "tvoc"),
                   occupancy_fn=_presence, counting=False, defaults=_GS601_DEF),
    "AT101": Model("AT101", "AT101 GNSS / Wi-Fi asset tracker", decode_at101,
                   frozenset({"at101", "battery", "moving", "away"}), minmax_fields=("temperature",),
                   defaults=(("temperature_alarm_active", False),)),
    "WS101": Model("WS101", "WS101 smart button", decode_ws101, frozenset({"battery"}), minmax_fields=(),
                   buttons=("button",), event_types=_PRESS3),
    "WS136": Model("WS136", "WS136 smart scene panel", decode_ws136, frozenset({"battery"}), minmax_fields=(),
                   buttons=_PANEL, event_types=("press",)),
    "WS156": Model("WS156", "WS156 smart scene panel", decode_ws156, frozenset({"battery"}), minmax_fields=(),
                   buttons=_PANEL, event_types=_PRESS3),
    "WS201": Model("WS201", "WS201 fill level monitor (tissue / soap / towels)", decode_ws201,
                   frozenset({"battery", "ws201"}), minmax_fields=()),
    "WS202": Model("WS202", "WS202 PIR & light sensor", decode_ws202, frozenset({"battery", "ws202", "motion"}),
                   minmax_fields=()),
    "WS203": Model("WS203", "WS203 motion & temperature / humidity sensor", decode_ws203,
                   frozenset({"battery", "env", "occupancy", "ws203"}), occupancy_fn=_presence, counting=False,
                   defaults=(("temperature_alarm_active", False),)),
    "WS301": Model("WS301", "WS301 magnetic contact switch (door/window)", decode_ws301,
                   frozenset({"battery", "door", "tamper"}), minmax_fields=()),
    "WS302": Model("WS302", "WS302 sound level sensor", decode_ws302, frozenset({"battery", "ws302"}),
                   minmax_fields=("sound_level", "sound_level_eq")),
    "WS303": Model("WS303", "WS303 mini leak detector", decode_ws303, frozenset({"battery", "leak"}), minmax_fields=()),
    "WS501": _ws_switch("WS501", "WS501 1-gang wall switch (firmware v1-v3)", decode_ws501, 1, "ff29"),
    "WS502": _ws_switch("WS502", "WS502 2-gang wall switch (firmware v1-v3)", decode_ws502, 2, "ff29"),
    "WS503": _ws_switch("WS503", "WS503 3-gang wall switch (firmware v1-v3)", decode_ws503, 3, "ff29"),
    "WS501-EU": _ws_switch("WS501-EU", "WS501 EU / US 1-gang wall switch (power metering)", decode_ws501, 1, "0829", meter=True),
    "WS502-EU": _ws_switch("WS502-EU", "WS502 EU 2-gang wall switch (power metering)", decode_ws502, 2, "0829", meter=True),
    "WS501-CN": _ws_switch("WS501-CN", "WS501 CN 1-gang wall switch", decode_ws501, 1, "0829"),
    "WS502-CN": _ws_switch("WS502-CN", "WS502 CN 2-gang wall switch", decode_ws502, 2, "0829"),
    "WS503-CN": _ws_switch("WS503-CN", "WS503 CN 3-gang wall switch", decode_ws503, 3, "0829"),
    "WS501-V4": _ws_switch("WS501-V4", "WS501 1-gang wall switch (firmware v4)", decode_ws501_v4, 1, "ff29", meter=True,
                           extra=frozenset({"ws_alarms"})),
    "WS502-V4": _ws_switch("WS502-V4", "WS502 2-gang wall switch (firmware v4)", decode_ws502_v4, 2, "ff29", meter=True,
                           extra=frozenset({"ws_alarms"})),
    "WS503-V4": _ws_switch("WS503-V4", "WS503 3-gang wall switch (firmware v4)", decode_ws503_v4, 3, "ff29", meter=True,
                           extra=frozenset({"ws_alarms"})),
    "WS513": _ws_switch("WS513", "WS513 smart wall socket", decode_ws52x, 1, "0870", meter=True,
                        extra=frozenset({"socket", "ws_temp", "sensor_error"})),
    "WS515": _ws_switch("WS515", "WS515 smart wall socket", decode_ws52x, 1, "0870", meter=True,
                        extra=frozenset({"socket", "ws_temp", "sensor_error"})),
    "WS513-V3": _ws_switch("WS513-V3", "WS513 smart wall socket (firmware v3)", decode_ws52x_v3, 1, "ff29", meter=True,
                           extra=frozenset({"socket", "ws_temp", "ws_alarms", "sensor_error"})),
    "WS515-V3": _ws_switch("WS515-V3", "WS515 smart wall socket (firmware v3)", decode_ws52x_v3, 1, "ff29", meter=True,
                           extra=frozenset({"socket", "ws_temp", "ws_alarms", "sensor_error"})),
    "WS523": _ws_switch("WS523", "WS523 portable smart socket", decode_ws52x, 1, "0870", meter=True,
                        extra=frozenset({"socket"})),
    "WS525": _ws_switch("WS525", "WS525 portable smart socket", decode_ws52x, 1, "0870", meter=True,
                        extra=frozenset({"socket"})),
    "WS558": _ws_switch("WS558", "WS558 8-channel smart light controller", decode_ws558, 8, "0831", meter=True),
    "WT101": Model("WT101", "WT101 smart radiator thermostat", decode_wt101,
                   frozenset({"battery", "wt", "wt_valve", "heating"}), minmax_fields=("temperature",), climate="wt101",
                   defaults=(("window_open", False), ("freeze_protection", False))),
    "WT102": Model("WT102", "WT102 smart radiator thermostat", decode_wt102,
                   frozenset({"battery", "wt", "wt_valve", "wt102", "heating"}), minmax_fields=("temperature",),
                   climate="wt102", defaults=(("window_open", False), ("freeze_protection", False),
                                              ("temperature_alarm_active", False), ("battery_low_alarm", False))),
    "WT201": Model("WT201", "WT201 smart thermostat (firmware v1)", decode_wt201,
                   frozenset({"wt", "wt_hum", "wt_hvac", "wt_fan", "heating", "cooling", "sensor_error"}),
                   climate="wt201", defaults=(("temperature_alarm_active", False),)),
    "WT201-V2": Model("WT201-V2", "WT201 smart thermostat (v2)", decode_wt201_v2,
                      frozenset({"wt", "wt_hum", "wt_hvac", "wt_fan", "heating", "cooling", "sensor_error"}),
                      climate="wt201v2", defaults=(("temperature_alarm_active", False),)),
    "WT211": Model("WT211", "WT211 smart thermostat", decode_wt201_v2,
                   frozenset({"wt", "wt_hum", "wt_hvac", "wt_fan", "heating", "cooling", "sensor_error"}),
                   climate="wt201v2", defaults=(("temperature_alarm_active", False),)),
    "WT301": Model("WT301", "WT301 fan-coil thermostat", decode_wt30x, frozenset({"wt", "wt30x"}), climate="wt30x"),
    "WT302": Model("WT302", "WT302 fan-coil thermostat", decode_wt30x, frozenset({"wt", "wt30x"}), climate="wt30x"),
    "WT303": Model("WT303", "WT303 fan-coil thermostat", decode_wt303,
                   frozenset({"wt", "wt_hum", "wt_hvac", "wt_fan", "wt303", "heating", "cooling", "sensor_error"}),
                   climate="wt303", defaults=(("temperature_alarm_active", False),)),
    "WT304": Model("WT304", "WT304 fan-coil thermostat (0-10 V / EC fan)", decode_wt303,
                   frozenset({"wt", "wt_hum", "wt_hvac", "wt_fan", "wt303", "heating", "cooling", "sensor_error"}),
                   climate="wt303", defaults=(("temperature_alarm_active", False),)),
    "WT401": Model("WT401", "WT401 smart thermostat", decode_wt401,
                   frozenset({"battery", "wt", "wt_hum", "wt_hvac", "wt_fan", "wt401", "occupancy", "sensor_error"}),
                   occupancy_fn=_presence, counting=False, climate="wt401",
                   buttons=("key_f1", "key_f2", "key_f3"), event_types=("press",)),
    "CTH01": Model("CTH01", "CTH01 multi-circuit energy meter (12 CT, 3-phase)", decode_cth01,
                   frozenset({"cth01", "sensor_error"}), minmax_fields=(), dynamic=True,
                   defaults=(("power_loss_alarm", False),)),
    "AM102": Model("AM102", "AM102 / AM102L ambience sensor (temperature & humidity)", decode_am102, _EM),
    "AM103": Model("AM103", "AM103 / AM103L ambience sensor (CO2, temperature, humidity)", decode_am103,
                   _EM | {"co2", "co2high"}, minmax_fields=("temperature", "humidity", "co2")),
    "AM104": Model("AM104", "AM104 ambience sensor (activity, light)", decode_am104, _EM | {"am10x_light"}),
    "AM107": Model("AM107", "AM107 ambience sensor (7-in-1)", decode_am107,
                   _EM | {"am10x_light", "co2", "co2high", "tvoc_ppb", "pressure"},
                   minmax_fields=("temperature", "humidity", "co2")),
    "AM304L": Model("AM304L", "AM304L indoor ambience sensor (PIR, light)", decode_am304l,
                    _EM | {"pir", "light", "am30xl", "occupancy", "sensor_error"}, occupancy_fn=_presence, counting=False,
                    defaults=(("temperature_alarm_active", False),)),
    "AM305L": Model("AM305L", "AM305L indoor ambience sensor (PIR, light, CO2)", decode_am305l,
                    _EM | {"pir", "light", "am30xl", "co2", "co2high", "occupancy", "sensor_error"},
                    minmax_fields=("temperature", "humidity", "co2"), occupancy_fn=_presence, counting=False,
                    defaults=(("temperature_alarm_active", False), ("co2_alarm_active", False))),
    "DS3604": Model("DS3604", "DS3604 e-ink display", decode_ds3604, frozenset({"battery", "ds3604"}), minmax_fields=(),
                    buttons=("button",), event_types=("single_click", "double_click", "short_press", "long_press")),
    "EM300-CL": Model("EM300-CL", "EM300-CL capacitive liquid level sensor", decode_em300_cl,
                      frozenset({"battery", "em300cl", "sensor_error"}), minmax_fields=(),
                      defaults=(("liquid_alarm_active", False),)),
    "EM300-DI-HALL": Model("EM300-DI-HALL", "EM300-DI-HALL pulse counter (hall sensor)", decode_em300,
                           _EM | {"input", "pulse"}),
    "EM300-MLD": Model("EM300-MLD", "EM300-MLD membrane leak detector", decode_em300_mld,
                       frozenset({"battery", "leak"}), minmax_fields=()),
    "EM310-TILT": Model("EM310-TILT", "EM310-TILT tilt sensor", decode_em310_tilt, frozenset({"battery", "emtilt"}),
                        minmax_fields=()),
    "EM320-TILT": Model("EM320-TILT", "EM320-TILT tilt sensor", decode_em320_tilt, frozenset({"battery", "emtilt"}),
                        minmax_fields=()),
    "EM310-UDL": Model("EM310-UDL", "EM310-UDL ultrasonic distance / level", decode_em310_udl,
                       frozenset({"battery", "em310udl"}), minmax_fields=("distance",)),
    "EM320-TH": Model("EM320-TH", "EM320-TH temperature & humidity (firmware v1)", decode_em300, _EM),
    "EM320-TH-V2": Model("EM320-TH-V2", "EM320-TH temperature & humidity (firmware v2)", decode_em320_th_v2,
                         _EM | {"em320th", "sensor_error"},
                         defaults=(("temperature_alarm_active", False), ("humidity_alarm_active", False))),
    "EM410-RDL": Model("EM410-RDL", "EM410-RDL radar distance / level", decode_em410_rdl,
                       frozenset({"battery", "em400", "rdl", "sensor_error"}), minmax_fields=("distance", "temperature"),
                       defaults=(("distance_alarm_active", False), ("distance_exception_alarm_active", False))),
    "EM411-RDL": Model("EM411-RDL", "EM411-RDL radar distance / level", decode_em411_rdl,
                       frozenset({"battery", "em400", "rdl", "sensor_error"}), minmax_fields=("distance", "temperature"),
                       defaults=(("distance_alarm_active", False), ("distance_exception_alarm_active", False))),
    "VS132": Model("VS132", "VS132 3D ToF people counter", decode_vs132, frozenset({"peoplecount"}), minmax_fields=(),
                   counters=("people_in", "people_out")),
    "VS133": Model("VS133", "VS133 AI ToF people counter", decode_vs133, frozenset({"peoplecount"}), minmax_fields=(),
                   counters=("people_in", "people_out"), dynamic=True),
    "VS135": Model("VS135", "VS135 AI ToF people counter", decode_vs135, frozenset({"peoplecount"}), minmax_fields=(),
                   counters=("people_in", "people_out"), dynamic=True),
    "VS330": Model("VS330", "VS330 bathroom occupancy sensor", decode_vs330,
                   frozenset({"battery", "occupancy", "vs330"}), minmax_fields=(), occupancy_fn=_presence, counting=False),
    "VS350": Model("VS350", "VS350 passage people counter", decode_vs350,
                   frozenset({"battery", "peoplecount", "vs35x", "vs35x_temp"}), minmax_fields=("temperature",),
                   counters=("people_in", "people_out"), defaults=(("temperature_alarm_active", False),)),
    "VS351": Model("VS351", "VS351 thermopile people counter", decode_vs351,
                   frozenset({"battery", "peoplecount", "vs35x", "vs35x_temp", "vs351"}), minmax_fields=("temperature",),
                   counters=("people_in", "people_out"), defaults=(("temperature_alarm_active", False),)),
    "VS360": Model("VS360", "VS360 IR break-beam people counter", decode_vs360,
                   frozenset({"battery", "peoplecount", "vs35x", "vs360"}), minmax_fields=(),
                   counters=("people_in", "people_out")),
    "UC11-T1": Model("UC11-T1", "UC11-T1 temperature & humidity", decode_uc11t1,
                     frozenset({"battery", "uc11t1"}), minmax_fields=("temperature", "humidity")),
    "UC11XX": Model("UC11XX", "UC11xx I/O controller (UC1114 / UC1122 / UC1152 …)", decode_uc11xx,
                    frozenset(), minmax_fields=(), dynamic=True),
    "UC11-N1": Model("UC11-N1", "UC11-N1 I/O controller", decode_uc11n1, frozenset(), minmax_fields=(), dynamic=True),
    "UC300": Model("UC300", "UC300 IoT controller (DI / DO / PT100 / analog / Modbus)", decode_uc300,
                   frozenset(), minmax_fields=(), dynamic=True),
    "UC501": Model("UC501", "UC501 multi-interface controller", decode_uc50x, frozenset(), minmax_fields=(), dynamic=True),
    "UC502": Model("UC502", "UC502 multi-interface controller (solar)", decode_uc50x, frozenset(), minmax_fields=(),
                   dynamic=True),
    "UC511": Model("UC511", "UC511 solenoid valve controller", decode_uc51x, frozenset(), minmax_fields=(), dynamic=True),
    "UC512": Model("UC512", "UC512 solenoid valve controller", decode_uc51x, frozenset(), minmax_fields=(), dynamic=True),
    "UC521": Model("UC521", "UC521 motorised valve controller", decode_uc521, frozenset(), minmax_fields=(), dynamic=True),
    "UC100": Model("UC100", "UC100 Modbus RTU converter (firmware v1)", decode_uc100, frozenset(), minmax_fields=(),
                   dynamic=True),
    "UC100-V2": Model("UC100-V2", "UC100 Modbus RTU converter (firmware v2)", decode_uc100_v2, frozenset(),
                      minmax_fields=(), dynamic=True),
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
    new = _guess_new_ranges(raw)
    if new:
        return new
    ws = _guess_ws(raw)
    if ws:
        return ws
    wt = _guess_wt_channels(raw)
    if wt:
        return wt
    at = decode_at101(raw)
    if at.keys() & {"latitude", "wifi_scan_result", "tamper_status", "history"}:
        return "AT101", ["AT101"]
    e4 = decode_em400(raw)
    if "distance" in e4 or ("position" in e4 and "temperature" in e4):
        return "EM400-UDL", ["EM400-UDL", "EM400-TLD", "EM400-MUD", "EM410-RDL", "EM411-RDL"]
    gs = _guess_gs(raw)
    if gs:
        return gs
    ct = _guess_ct(raw)
    if ct:
        return ct
    uc = _guess_uc(raw)
    if uc:
        return uc
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
    th2 = decode_em320_th_v2(raw)
    if th2.keys() & {"temperature_change", "humidity_change", "trigger_type", "storage_status",
                     "temperature_alarm_status", "humidity_alarm_status"} or (raw[:2] == b"\x04\x9a"):
        return "EM320-TH-V2", ["EM320-TH-V2", "EM320-TH", "EM300-TH"]
    vo = decode_vs_occupancy(raw)
    if "occupancy" in vo:
        if "illuminance" in vo:
            return "VS370", ["VS370", "WS202", "WS301", "TS302"]
        return "VS340", ["VS340", "VS341", "VS370", "WS301", "WS202", "WS303", "TS301", "UC11-N1"]
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
        if "co2" in am and not am.keys() & {"pir", "light_level", "tvoc", "tvoc_iaq", "pressure"}:
            return "AM103", list(dict.fromkeys(["AM103"] + am_all))
        return "AM307", list(dict.fromkeys(am_all + ["AM103"]))
    em = decode_em300(raw)
    if "pulse_count" in em or "water" in em:
        return "EM300-DI", ["EM300-DI", "EM300-DI-HALL"]
    if "magnet_status" in em:
        return "EM300-MCS", ["EM300-MCS"]
    if "input_05" in em:
        return "EM300-SLD", ["EM300-SLD", "EM300-ZLD", "EM300-MLD", "EM300-DI", "WS203"]
    if "temperature" in em and "humidity" not in em:
        return "EM500-PT100", ["EM500-PT100", "TS101", "TS201", "TS301", "EM300-TH", "EM500-SMTC"]
    if "temperature" in em or "humidity" in em:
        return "EM300-TH", ["EM300-TH", "EM320-TH", "EM320-TH-V2", "AM102"] + \
            [k for k in MODELS if k.startswith("EM300") and k != "EM300-TH"] + ["TS201"] + \
            [k for k in MODELS if k.startswith("AM") and k != "AM102"]
    wtc = _guess_wt_commands(raw)
    if wtc:
        return wtc
    cth = decode_cth01(raw)
    if cth01_parses_cleanly(raw) and sum(1 for k in cth if re.fullmatch(r"(current_ct|voltage_l|thdi_ct|thdv_l)\d+|(active|reactive|apparent)_power_\w+"
                                         r"|\w+_energy_\w+|power_factor_\w+", k)) >= 3:
        return "CTH01", ["CTH01"]
    if len(raw) == 6 and raw[1] >> 4 == 1 and (raw[1] & 0x0F) in (1, 2, 4, 5, 7, 0x0A, 0x0B, 0x0E, 0x0F) \
            and raw[2] <= 100:
        return "GS524N", ["GS524N"]
    g6 = decode_gs601(raw)
    if gs601_parses_completely(raw) and not ts60x_parses_completely(raw) and g6.keys() & {
            "vaping_index", "vaping_index_alarm_status", "pm2_5", "tvoc", "tamper_status", "occupancy"}:
        return "GS601", ["GS601"]
    if ts60x_parses_completely(raw) and any(
            k in decode_ts60x(raw) for k in ("temperature", "humidity", "probe_connected", "latitude", "temperature_alarm_status")):
        return "TS601", ["TS601", "TS602", "GS601"] if gs601_parses_completely(raw) else ["TS601", "TS602"]
    if gs601_parses_completely(raw) and "battery" in g6:
        return "GS601", ["GS601", "TS601", "TS602"]
    return None, list(MODELS)


_WS_METER = {(0x03, 0x74), (0x04, 0x80), (0x05, 0x81), (0x06, 0x83), (0x07, 0xC9)}
_WS_V4_ALARMS = {(0x87, 0xC9), (0x88, 0x29), (0x89, 0xDF), (0xB3, 0x74), (0xB4, 0x80), (0xB5, 0x81), (0xB6, 0x83),
                 (0xB7, 0xC9)}
_WS_TEMP = {(0x09, 0x67), (0x89, 0x67), (0x99, 0x67)}


def _guess_ws(raw: bytes) -> tuple[str, list[str]] | None:
    if "button_event" in decode_ws101(raw):
        return "WS101", ["WS101", "DS3604"]
    panel = decode_ws156(raw)
    if any(k.endswith("_event") for k in panel):
        if all(v != "unknown" for k, v in panel.items() if k.endswith(("_mode", "_event"))):
            return "WS156", ["WS156", "WS136"]
        return "WS136", ["WS136", "WS156"]
    if "remaining" in decode_ws201(raw):
        return "WS201", ["WS201"]
    if "sound_level" in decode_ws302(raw):
        return "WS302", ["WS302"]
    ch = ws_power_channels(raw)
    if (0x08, 0x31) in ch:
        return "WS558", ["WS558"]
    sockets = ["WS513", "WS515", "WS523", "WS525", "WS513-V3", "WS515-V3"]
    if (0x08, 0x70) in ch:
        if ch & _WS_V4_ALARMS or (0xFF, 0x29) in ch:
            return "WS513-V3", ["WS513-V3", "WS515-V3"] + sockets[:4]
        if ch & _WS_TEMP:
            return "WS513", ["WS513", "WS515", "WS513-V3", "WS515-V3"]
        return "WS523", sockets
    if ch & _WS_TEMP and ch & _WS_METER:
        return "WS513", ["WS513", "WS515", "WS513-V3", "WS515-V3"]
    v1 = ["WS501", "WS502", "WS503"]
    v4 = ["WS501-V4", "WS502-V4", "WS503-V4"]
    eu = ["WS501-EU", "WS502-EU"]
    cn = ["WS501-CN", "WS502-CN", "WS503-CN"]
    if (0x08, 0x29) in ch:
        return ("WS501-EU", eu + cn) if ch & _WS_METER else ("WS501-CN", cn + eu)
    if (0xFF, 0x29) in ch or (0xFF, 0x2B) in ch or ch & _WS_V4_ALARMS:
        return ("WS501-V4", v4 + v1) if ch & (_WS_METER | _WS_V4_ALARMS) else ("WS501", v1 + v4)
    if ch & _WS_METER:
        return "WS501-V4", v4 + eu + sockets + ["WS558"]
    return None


_WT201_FAMILY = ["WT201-V2", "WT211", "WT201"]


def _pairs(raw: bytes) -> set[tuple[int, int]]:
    """(channel id, type) pairs at the positions a channel-format decoder would read them – approximate,
    used only together with a decoder check."""
    return {(raw[k], raw[k + 1]) for k in range(len(raw) - 1)}


def _guess_new_ranges(raw: bytes) -> tuple[str, list[str]] | None:
    """AM10x / AM30xL / DS3604 / EM300-CL / EM310 / EM320 / EM410 / VS13x / VS330 / VS35x signatures."""
    d = decode_ds3604(raw)
    if "current_template_id" in d or ("button_event" in d and len(d.get("sn", "")) == 16) \
            or b"\xfb\x01" in (raw[:2], raw[3:5]):          # display content frames
        return "DS3604", ["DS3604", "WS101"]
    a4 = decode_am107(raw)
    if "pir_activity" in a4 or "infrared" in a4:
        if a4.keys() & {"co2", "tvoc_ppb", "pressure"}:
            return "AM107", ["AM107", "AM104"]
        return "AM104", ["AM104", "AM107"]
    a3 = decode_am305l(raw)
    if a3.keys() & {"pir_count", "illuminance_lux", "illuminance_alarm_status", "co2_alarm_status"}:
        return ("AM305L", ["AM305L", "AM304L"]) if "co2" in a3 or "co2_alarm_status" in a3 else ("AM304L", ["AM304L", "AM305L"])
    if decode_em300_cl(raw).keys() & {"liquid", "liquid_alarm_status", "calibration_result"}:
        return "EM300-CL", ["EM300-CL"]
    if "angle_x" in decode_em310_tilt(raw):
        return "EM310-TILT", ["EM310-TILT", "EM320-TILT"]
    if "angle_x" in decode_em320_tilt(raw):
        return "EM320-TILT", ["EM320-TILT", "EM310-TILT"]
    rd = decode_em410_rdl(raw)
    if rd.keys() & {"radar_signal_rssi", "distance_exception_alarm_status", "distance_mutation"}:
        return "EM410-RDL", ["EM410-RDL", "EM411-RDL", "EM400-UDL"]
    ud = decode_em310_udl(raw)
    if "distance" in ud and "position" in ud and "temperature" not in ud:
        return "EM310-UDL", ["EM310-UDL", "EM400-UDL", "EM500-UDL"]
    v3 = decode_vs330(raw)
    if "occupancy" in v3 and v3.keys() & {"distance", "calibration_status"}:
        return "VS330", ["VS330"]
    v13 = decode_vs133(raw)
    if any(k.startswith(("line_2", "line_3", "line_4", "region_", "master_", "node_")) for k in v13) or \
            "device_version" in v13:
        return "VS133", ["VS133", "VS135", "VS132"]
    if "people_total_in" in decode_vs132(raw) or "people_total_out" in decode_vs132(raw):
        return "VS132", ["VS132", "VS133", "VS135"]
    v5 = decode_vs350(raw)
    v6 = decode_vs360(raw)
    if v6.keys() & {"battery_node", "counting_anomaly_alarm_status", "devices_misaligned_alarm_status",
                    "node_device_without_response_alarm_status"}:
        return "VS360", ["VS360"]
    if v5.keys() & {"people_total_in", "people_total_out", "people_in", "total_count_alarm_status"} and \
            "people_count_all" not in v5:
        if "power_status" in decode_vs351(raw):
            return "VS351", ["VS351", "VS350"]
        if "temperature" in v5 or "current_sensitivity" in v5:
            return "VS350", ["VS350", "VS351"]
        return "VS350", ["VS350", "VS351", "VS360"]
    return None


def _guess_wt_channels(raw: bytes) -> tuple[str, list[str]] | None:
    """WT301/302 frames, WT101 and the WT201 family (channel format)."""
    if len(raw) >= 7 and raw[0] == 0x55 and raw[1] in (1, 2) and len(raw) == 5 + (raw[2] << 8 | raw[3]) \
            and sum(raw[:-1]) & 0xFF == raw[-1]:
        return "WT301", ["WT301", "WT302"]
    if decode_wt101(raw).keys() & {"valve_opening", "window_open", "motor_calibration_result", "freeze_protection",
                                   "motor_stroke", "motor_position"}:
        return "WT101", ["WT101"]
    d = decode_wt201_v2(raw)
    if d.keys() & {"temperature_control_mode", "fan_mode", "system_status", "relay", "plan_type", "supported_modes"}:
        if d.keys() & {"target_temperature_2", "temperature_source", "source_switch_alarm", "target_temperature_range_alarm"}:
            return "WT201-V2", ["WT201-V2", "WT211"]
        return "WT201-V2", _WT201_FAMILY
    return None


def _guess_wt_commands(raw: bytes) -> tuple[str, list[str]] | None:
    """WT102 / WT303 / WT304 / WT401 (command format): the payload must parse completely and contain a
    command that is specific to that model."""
    hits = []
    if wt303_parses_completely(raw) and decode_wt303(raw).keys() & {
            "temperature_control_mode", "fan_mode", "data_source", "relay_low", "valve_opening"}:
        hits.append(("WT303", ["WT303", "WT304"]))
    w4 = decode_wt401(raw)
    if wt401_parses_completely(raw) and w4.keys() & {"temperature_control_mode", "fan_mode", "pir_status",
                                                      "target_temperature_2"}:
        hits.append(("WT401", ["WT401"]))
    w1 = decode_wt102(raw)
    if wt102_parses_completely(raw) and w1.keys() & {"valve_opening", "motor_stroke", "motor_position",
                                                      "motor_calibration_result", "target_valve_opening"}:
        hits.append(("WT102", ["WT102"]))
    if not hits:
        return None
    best = hits[0][0]
    cands = [c for _, cs in hits for c in cs]
    return best, list(dict.fromkeys(cands))


def guess_from_name(name: str | None) -> str | None:
    """Model named in the gateway's device name, e.g. 'WS301 front door' -> WS301."""
    if not name:
        return None
    norm = re.sub(r"[^A-Z0-9]", "", name.upper())
    for key in sorted(MODELS, key=len, reverse=True):
        if re.sub(r"[^A-Z0-9]", "", key) in norm:
            return key
    return None


def _guess_gs(raw: bytes) -> tuple[str, list[str]] | None:
    """GS101 / GS301 by their unique channels; GS601 command frames are checked last in guess_model."""
    if decode_gs101(raw).keys() & {"gas_alarm", "valve_status", "relay_output_status", "life_remain", "device_alarm"}:
        return "GS101", ["GS101"]
    g3 = decode_gs301(raw)
    if g3.keys() & {"nh3", "h2s"} or "NH3" in g3.get("sensor_error", "") or "H2S" in g3.get("sensor_error", ""):
        return "GS301", ["GS301"]
    return None


def _guess_ct(raw: bytes) -> tuple[str, list[str]] | None:
    """CT10x (current 0x04 0x98) / CT30x (current 0x04-0x08 0x99). A payload that only has
    temperature (0x09 0x67) is not enough to tell them apart from other devices."""
    c1, c3 = decode_ct10x(raw), decode_ct30x(raw)
    if "current" in c1 or c1.get("sensor_error", "").startswith("Current:"):
        return "CT101", ["CT101", "CT103", "CT105"]
    if any(k.startswith("current_") for k in c3) or "Current " in c3.get("sensor_error", ""):
        return "CT303", ["CT303", "CT305", "CT310"]
    if any(k in c1 for k in ("total_current", "energy")):     # cumulative-only uplink: same layout on CT10x / CT30x
        return "CT101", ["CT101", "CT103", "CT105", "CT303", "CT305", "CT310"]
    return None


def _guess_uc(raw: bytes) -> tuple[str, list[str]] | None:
    """UC-range signatures. Decoders parse from the first byte, so a key only appears when the
    payload really starts with that controller's channel layout."""
    def mod(d: dict) -> bool:
        return any(k.startswith("modbus_chn_") for k in d)

    if mod(decode_uc100_v2(raw)):
        return "UC100-V2", ["UC100-V2", "UC100"]
    u3 = decode_uc300(raw)
    if any(k.startswith(("pt100", "adc", "adv")) for k in u3) or ("gpio_output_1" in u3 and "gpio_input_1" in u3):
        return "UC300", ["UC300"]
    if mod(decode_uc100(raw)):
        return ("UC300", ["UC300", "UC100"]) if any(k.startswith("gpio") for k in u3) else ("UC100", ["UC100", "UC300", "UC100-V2"])
    if decode_uc521(raw).keys() & {"valve_1_opening", "valve_2_opening", "valve_1_type", "valve_2_type",
                                   "pressure_1", "pressure_2"}:
        return "UC521", ["UC521"]
    if decode_uc51x(raw).keys() & {"valve_1", "valve_2", "valve_1_pulse", "valve_2_pulse", "valve_1_result",
                                   "valve_2_result"}:
        return "UC511", ["UC511", "UC512"]
    u50 = decode_uc50x(raw)
    if any(k.startswith(("analog_input", "sdi12")) for k in u50):
        return "UC501", ["UC501", "UC502"]
    if decode_uc11t1(raw).keys() & {"temperature", "humidity"}:
        return "UC11-T1", ["UC11-T1"]
    n1 = decode_uc11n1(raw)
    if mod(n1) or any(k.startswith("adc") for k in n1):
        return "UC11-N1", ["UC11-N1", "UC501", "UC11XX"]
    u11 = decode_uc11xx(raw)
    if mod(u11) or any(k.startswith(("adc", "gpio_output")) for k in u11):
        return "UC11XX", ["UC11XX", "UC11-N1"]
    return None


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
# Downlink commands (generated from Milesight's official encoders, see tools/checks/dl_*.py)
# --------------------------------------------------------------------------
DOWNLINKS: dict[str, dict] = json.loads((pathlib.Path(__file__).parent / "downlinks.json").read_text())


def downlinks(model_key: str) -> dict:
    return DOWNLINKS.get(model_key, {})


def _command_specs(model_key: str) -> list[EntitySpec]:
    dl = downlinks(model_key)
    specs: list[EntitySpec] = []
    cfg = dict(diagnostic=True)
    if "reboot" in dl:
        specs.append(EntitySpec("cmd_reboot", "Reboot", platform="button", device_class="restart", **cfg))
    if "sync_time" in dl or "set_time" in dl:
        specs.append(EntitySpec("cmd_sync_time", "Sync time", platform="button", icon="mdi:clock-check-outline", **cfg))
    if "report_status" in dl:
        specs.append(EntitySpec("cmd_report_status", "Request update", platform="button", icon="mdi:refresh", **cfg))
    for key, name in (("report_interval", "Reporting interval"), ("collection_interval", "Collection interval")):
        if key in dl and "prefix" in dl[key]:
            unit = {"s": "s", "min": "min"}.get(dl[key].get("unit"), dl[key].get("unit"))
            specs.append(EntitySpec(f"cfg_{key}", name, platform="number", unit=unit, device_class="duration",
                                    icon="mdi:timer-cog-outline", **cfg))
    fixed = {s.key for s in specs}
    for name, out in dl.get("outputs", {}).items():
        key = out.get("key") or name
        label = name.replace("_", " ").capitalize()
        if key in fixed:
            continue
        if "set" in out:          # proportional valve: opening %
            specs.append(EntitySpec(key, f"{label} opening", platform="number", unit="%", icon="mdi:valve"))
        else:
            specs.append(EntitySpec(key, label, platform="switch",
                                    device_class="switch", icon="mdi:valve" if "valve" in name else None))
        fixed.add(key)
    return specs


def output_for_key(model_key: str, key: str) -> dict | None:
    for out_name, out in downlinks(model_key).get("outputs", {}).items():
        if (out.get("key") or out_name) == key:
            return out
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


def _cth_label(part: str) -> str:
    """'ct7' -> 'CT 7', 'l2' -> 'L2', 'a' -> 'circuit A'."""
    if part.startswith("ct"):
        return f"CT {part[2:]}"
    if part.startswith("l"):
        return part.upper()
    return f"circuit {part.upper()}"


_CTH_UNITS = {  # measure -> (label, unit, device_class, state_class, precision)
    "active_power": ("Active power", "kW", "power", "measurement", 3),
    "reactive_power": ("Reactive power", "kvar", None, "measurement", 3),
    "apparent_power": ("Apparent power", "kVA", None, "measurement", 3),
    "forward_active_energy": ("Energy imported", "kWh", "energy", "total_increasing", 3),
    "reverse_active_energy": ("Energy exported", "kWh", "energy", "total_increasing", 3),
    "forward_reactive_energy": ("Reactive energy imported", "kvarh", None, "total_increasing", 3),
    "reverse_reactive_energy": ("Reactive energy exported", "kvarh", None, "total_increasing", 3),
    "apparent_energy": ("Apparent energy", "kVAh", None, "total_increasing", 3),
    "power_factor": ("Power factor", None, "power_factor", "measurement", 2),
}


def _cth_measure(m) -> EntitySpec:
    label, unit, dc, sc, prec = _CTH_UNITS[m[1]]
    return EntitySpec(m[0], f"{label} {_cth_label(m[2])}", unit=unit, device_class=dc, state_class=sc, precision=prec)


_DYN = [   # (regex, builder) – applied to decoded keys of controllers with configurable channels
    # VS133 / VS135 lines and regions
    (r"line_(\d)_(child_)?(in|out)", lambda m: EntitySpec(m[0], f"Line {m[1]}{' child' if m[2] else ''} {m[3]} (last report)",
                                                         state_class="measurement", icon="mdi:account-arrow-right")),
    (r"line_(\d)_(child_)?total_(in|out)", lambda m: EntitySpec(m[0], f"Line {m[1]}{' child' if m[2] else ''} {m[3]} (device total)",
                                                               state_class="total_increasing", icon="mdi:counter")),
    (r"region_(\d)_(child_)?count", lambda m: EntitySpec(m[0], f"Region {m[1]}{' children' if m[2] else ' people'}",
                                                        state_class="measurement", icon="mdi:account-group")),
    (r"region_(\d)_(child_)?dwell_time_(avg|max)", lambda m: EntitySpec(
        m[0], f"Region {m[1]}{' child' if m[2] else ''} dwell time {m[3]}", unit="s", device_class="duration",
        state_class="measurement", enabled_default=False)),
    (r"(master|node_\d+)_occlusion_alarm_active", lambda m: EntitySpec(
        m[0], f"{'Sensor' if m[1] == 'master' else m[1].replace('_', ' ').capitalize()} lens blocked", platform="binary_sensor",
        device_class="problem")),
    # CTH01 energy meter
    (r"current_ct(\d+)", lambda m: EntitySpec(m[0], f"Current CT {m[1]}", unit="A", device_class="current",
                                              state_class="measurement", precision=2)),
    (r"voltage_l(\d)", lambda m: EntitySpec(m[0], f"Voltage L{m[1]}", unit="V", device_class="voltage",
                                            state_class="measurement", precision=1)),
    (r"thdi_ct(\d+)", lambda m: EntitySpec(m[0], f"Current THD CT {m[1]}", unit="%", state_class="measurement",
                                           icon="mdi:sine-wave", precision=1, enabled_default=False)),
    (r"thdv_l(\d)", lambda m: EntitySpec(m[0], f"Voltage THD L{m[1]}", unit="%", state_class="measurement",
                                         icon="mdi:sine-wave", precision=1, enabled_default=False)),
    (r"(" + "|".join(_CTH_UNITS) + r")_(ct\d+|[abcd])", _cth_measure),
    (r"(current_ct\d+|voltage_l\d|thdi_ct\d+|thdv_l\d|voltage_unbalance|temperature)_alarm_active",
     lambda m: EntitySpec(m[0], f"{_cth_alarm_label(m[1])} alarm", platform="binary_sensor", device_class="problem")),
    (r"(current_ct\d+|voltage_l\d|thdi_ct\d+|thdv_l\d|voltage_unbalance|temperature)_alarm_status",
     lambda m: EntitySpec(m[0], f"{_cth_alarm_label(m[1])} alarm status", kind="label", icon="mdi:alarm-light-outline",
                          enabled_default=False)),
    (r"battery", lambda m: EntitySpec("battery", "Battery", unit="%", device_class="battery",
                                      state_class="measurement", diagnostic=True)),
    (r"gpio_input_(\d+)", lambda m: EntitySpec(m[0], f"Digital input {m[1]}", platform="binary_sensor")),
    (r"gpio_output_(\d+)", lambda m: EntitySpec(m[0], f"Digital output {m[1]}", platform="binary_sensor")),
    (r"gpio_(\d+)", lambda m: EntitySpec(m[0], f"GPIO {m[1]}", platform="binary_sensor")),
    (r"gpio_counter(?:_(\d+))?", lambda m: EntitySpec(m[0], f"Pulse counter {m[1] or ''}".strip(),
                                                      state_class="total_increasing", icon="mdi:counter")),
    (r"pt100_(\d+)", lambda m: EntitySpec(m[0], f"PT100 {m[1]}", unit="°C", device_class="temperature",
                                          state_class="measurement", precision=1)),
    (r"pt100_(\d+)_(min|max|avg)", lambda m: EntitySpec(m[0], f"PT100 {m[1]} {m[2]}", unit="°C",
                                                        device_class="temperature", enabled_default=False)),
    (r"adv_(\d+)", lambda m: EntitySpec(m[0], f"Analog voltage {m[1]}", unit="V", device_class="voltage",
                                        state_class="measurement", precision=2)),
    (r"(?:adc|analog_input)_(\d+)", lambda m: EntitySpec(m[0], f"Analog input {m[1]}", state_class="measurement",
                                                         icon="mdi:sine-wave", precision=2)),
    (r"(adc|adv|analog_input)_(\d+)_(min|max|avg)", lambda m: EntitySpec(
        m[0], f"{'Analog voltage' if m[1] == 'adv' else 'Analog input'} {m[2]} {m[3]}", enabled_default=False,
        icon="mdi:sine-wave", precision=2)),
    (r"analog_input_(\d+)_type", lambda m: EntitySpec(m[0], f"Analog input {m[1]} type", kind="label", diagnostic=True)),
    (r"(analog_input_\d+|modbus_chn_\d+(?:_reg_\d+)?)_alarm", lambda m: EntitySpec(
        m[0], f"{_dyn_label(m[1])} alarm", kind="label", icon="mdi:alarm-light-outline")),
    (r"modbus_chn_(\d+)(?:_reg_(\d+))?", lambda m: EntitySpec(
        m[0], f"Modbus channel {m[1]}" + (f" register {m[2]}" if m[2] else ""), state_class="measurement",
        icon="mdi:lan")),
    (r"modbus_chn_.*_mutation", lambda m: EntitySpec(m[0], f"{_dyn_label(m[0][:-9])} change", enabled_default=False)),
    (r"sdi12_(\d+)", lambda m: EntitySpec(m[0], f"SDI-12 sensor {m[1]}", kind="text", icon="mdi:text-box-outline")),
    (r"valve_(\d+)", lambda m: EntitySpec(m[0], f"Valve {m[1]}", platform="binary_sensor", device_class="opening",
                                          icon="mdi:valve")),
    (r"valve_(\d+)_opening", lambda m: EntitySpec(m[0], f"Valve {m[1]} opening", unit="%", state_class="measurement",
                                                  icon="mdi:valve")),
    (r"valve_(\d+)_pulse", lambda m: EntitySpec(m[0], f"Valve {m[1]} pulses", state_class="total_increasing",
                                                icon="mdi:counter")),
    (r"valve_(\d+)_(type|direction|result)", lambda m: EntitySpec(m[0], f"Valve {m[1]} {m[2]}", kind="label",
                                                                  diagnostic=True)),
    (r"valve_(\d+)_sensor_status", lambda m: EntitySpec(m[0], f"Valve {m[1]} sensor status", diagnostic=True,
                                                        enabled_default=False)),
    (r"valve_(\d+)_opening_duration", lambda m: EntitySpec(m[0], f"Valve {m[1]} opening duration",
                                                           enabled_default=False)),
    (r"pressure(?:_(\d+))?", lambda m: EntitySpec(m[0], f"Pipe pressure {m[1] or ''}".strip(), unit="kPa",
                                                  device_class="pressure", state_class="measurement")),
    (r"pressure(?:_(\d+))?_sensor_status", lambda m: EntitySpec(m[0], f"Pressure sensor {m[1] or ''} status".replace("  ", " "),
                                                                diagnostic=True)),
    (r"pressure(?:_(\d+))?_alarm_active", lambda m: EntitySpec(m[0], f"Pressure {m[1] or ''} alarm".replace("  ", " "),
                                                               platform="binary_sensor", device_class="problem")),
    (r"pressure(?:_(\d+))?_alarm_status", lambda m: EntitySpec(m[0], f"Pressure {m[1] or ''} alarm status".replace("  ", " "),
                                                               kind="label", icon="mdi:alarm-light-outline")),
]


def _cth_alarm_label(key: str) -> str:
    m = re.fullmatch(r"(current|thdi)_ct(\d+)", key)
    if m:
        return f"{'Current' if m[1] == 'current' else 'Current THD'} CT {m[2]}"
    m = re.fullmatch(r"(voltage|thdv)_l(\d)", key)
    if m:
        return f"{'Voltage' if m[1] == 'voltage' else 'Voltage THD'} L{m[2]}"
    return key.replace("_", " ").capitalize()


def _dyn_label(key: str) -> str:
    m = re.fullmatch(r"modbus_chn_(\d+)(?:_reg_(\d+))?", key)
    if m:
        return f"Modbus channel {m[1]}" + (f" register {m[2]}" if m[2] else "")
    m = re.fullmatch(r"analog_input_(\d+)", key)
    return f"Analog input {m[1]}" if m else key


def dynamic_spec(key: str) -> EntitySpec | None:
    """Entity description for a decoded key of a configurable controller (None = not exposed)."""
    for pattern, build in _DYN:
        m = re.fullmatch(pattern, key)
        if m:
            return build(m)
    return None


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


def _ct(f: frozenset[str]) -> list[EntitySpec]:
    amp = dict(unit="A", device_class="current")
    specs: list[EntitySpec] = []
    chans = [("_1", " 1"), ("_2", " 2"), ("_3", " 3")] if "ct3" in f else [("", "")]
    for sfx, lbl in chans:
        specs += _measure(f"current{sfx}", f"Current{lbl}", "A", "current", icon="mdi:current-ac", precision=2)
        specs += [
            EntitySpec(f"total_current{sfx}", f"Cumulative current{lbl}", unit="Ah", state_class="total_increasing",
                       icon="mdi:sigma", precision=2),
            EntitySpec(f"energy{sfx}", f"Energy{lbl}", unit="kWh", device_class="energy",
                       state_class="total_increasing", precision=2),
            EntitySpec(f"current{sfx}_max", f"Current{lbl} max (last alarm)", icon="mdi:arrow-collapse-up",
                       enabled_default=False, **amp),
            EntitySpec(f"current{sfx}_min", f"Current{lbl} min (last alarm)", icon="mdi:arrow-collapse-down",
                       enabled_default=False, **amp),
            EntitySpec(f"apparent_power{sfx}", f"Estimated power{lbl}", unit="VA", device_class="apparent_power",
                       state_class="measurement", precision=0, enabled_default=False),
        ]
        specs += _alarm(f"current{sfx}", f"Current{lbl}")
    if "ct3" in f:
        specs += [
            EntitySpec("current_total", "Current (all channels)", state_class="measurement", icon="mdi:current-ac",
                       precision=2, **amp),
            EntitySpec("apparent_power", "Estimated power (all channels)", unit="VA", device_class="apparent_power",
                       state_class="measurement", precision=0, enabled_default=False),
        ]
    specs += [
        EntitySpec("temperature", "Temperature", unit="°C", device_class="temperature", state_class="measurement",
                   precision=1),
        EntitySpec("low_voltage_alarm", "Low voltage", platform="binary_sensor", device_class="problem",
                   enabled_default=False),
    ]   # "Sensor status" comes from the sensor_error feature
    specs += _alarm("temperature", "Temperature", enabled=False)
    return specs


def _gs(f: frozenset[str]) -> list[EntitySpec]:
    specs: list[EntitySpec] = []
    fault = EntitySpec("device_fault", "Device fault", platform="binary_sensor", device_class="problem")
    if "gs101" in f:
        specs += [
            EntitySpec("valve_status", "Valve", platform="binary_sensor", device_class="opening", icon="mdi:valve"),
            EntitySpec("relay_output_status", "Relay output", platform="binary_sensor", icon="mdi:electric-switch"),
            EntitySpec("life_remain_days", "Remaining sensor life", unit="d", device_class="duration", precision=0,
                       icon="mdi:timer-sand-complete"),
            EntitySpec("device_alarm", "Last device event", kind="label", icon="mdi:information-outline"),
            fault,
            EntitySpec("end_of_life", "Sensor end of life", platform="binary_sensor", device_class="problem",
                       icon="mdi:calendar-alert"),
        ]
    if "gs301" in f:
        specs += _measure("nh3", "Ammonia (NH3)", "ppm", None, icon="mdi:scent", precision=2)
        specs += _measure("h2s", "Hydrogen sulfide (H2S)", "ppm", None, icon="mdi:scent", precision=3)
        specs.append(EntitySpec("odour_level", "Odour level", kind="label", icon="mdi:scent"))
    if "gs524n" in f:
        specs += [
            EntitySpec("event", "Last event", kind="label", icon="mdi:smoke-detector-variant"),
            EntitySpec("concentration", "Smoke concentration", state_class="measurement", icon="mdi:smoke"),
            EntitySpec("temperature", "Temperature", unit="°C", device_class="temperature", state_class="measurement"),
            EntitySpec("battery_low_alarm", "Battery low", platform="binary_sensor", device_class="battery"),
            EntitySpec("removed", "Removed from base", platform="binary_sensor", device_class="tamper"),
            fault,
        ]
    if "gs601" in f:
        pm = dict(unit="µg/m³", state_class="measurement")
        specs += _measure("vaping_index", "Vaping index", None, None, icon="mdi:smoking")
        specs += _alarm("vaping_index", "Vaping")
        specs += [
            EntitySpec("vaping_interference", "Vaping sensor interference", platform="binary_sensor",
                       device_class="problem"),
            EntitySpec("burning_alarm", "Burning / fire alarm", platform="binary_sensor", device_class="smoke"),
            EntitySpec("tamper_status", "Tamper", platform="binary_sensor", device_class="tamper"),
            EntitySpec("buzzer", "Buzzer", platform="binary_sensor", device_class="sound", icon="mdi:bullhorn"),
            EntitySpec("pm1_0", "PM1", device_class="pm1", **pm),
            EntitySpec("pm2_5", "PM2.5", device_class="pm25", **pm),
            EntitySpec("pm2_5_max_today", "PM2.5 max today", unit="µg/m³", device_class="pm25", icon="mdi:blur"),
            EntitySpec("pm10", "PM10", device_class="pm10", **pm),
            EntitySpec("tvoc", "TVOC", state_class="measurement", icon="mdi:air-filter"),
            EntitySpec("tvoc_max_today", "TVOC max today", icon="mdi:air-filter"),
            EntitySpec("pm_sensor_working_time", "PM sensor working time", unit="h", device_class="duration",
                       diagnostic=True, enabled_default=False),
        ]
        for key, label in (("pm1_0", "PM1"), ("pm2_5", "PM2.5"), ("pm10", "PM10"), ("tvoc", "TVOC"),
                           ("temperature", "Temperature")):
            specs += _alarm(key, label, enabled=False)
    return specs


def _at101() -> list[EntitySpec]:
    gps = dict(unit="°", icon="mdi:crosshairs-gps", enabled_default=False, precision=6)
    km = dict(unit="km", device_class="distance", precision=2)
    specs = [
        EntitySpec("location", "Location", platform="device_tracker"),
        EntitySpec("motion_status", "Motion", kind="label", icon="mdi:run"),
        EntitySpec("geofence_status", "Geofence", kind="label", icon="mdi:map-marker-radius"),
        EntitySpec("tilted", "Tilted", platform="binary_sensor", device_class="problem", icon="mdi:angle-acute"),
        EntitySpec("tamper", "Removed from mount", platform="binary_sensor", device_class="tamper"),
        EntitySpec("latitude", "Latitude", **gps),
        EntitySpec("longitude", "Longitude", **gps),
        EntitySpec("wifi_scan_result", "Wi-Fi scan", kind="label", icon="mdi:wifi-marker", diagnostic=True,
                   enabled_default=False),
        EntitySpec("wifi_ap_count", "Wi-Fi access points seen", icon="mdi:wifi", diagnostic=True, enabled_default=False),
        EntitySpec("distance_today_km", "Distance today", state_class="total_increasing", icon="mdi:map-marker-distance", **km),
        EntitySpec("distance_yesterday_km", "Distance yesterday", icon="mdi:map-marker-distance", **km),
        EntitySpec("distance_week_km", "Distance this week", state_class="total_increasing", icon="mdi:map-marker-distance", **km),
        EntitySpec("distance_last_week_km", "Distance last week", icon="mdi:map-marker-distance", **km),
        EntitySpec("distance_month_km", "Distance this month", state_class="total_increasing", icon="mdi:map-marker-distance", **km),
        EntitySpec("distance_last_month_km", "Distance last month", icon="mdi:map-marker-distance", **km),
    ]
    specs += _measure("temperature", "Temperature", "°C", "temperature", precision=1)
    specs += _alarm("temperature", "Temperature", enabled=False)
    return specs


def _ws(model: "Model") -> list[EntitySpec]:
    f = model.features
    specs: list[EntitySpec] = []
    for key in model.buttons:
        label = ("Button" if key == "button" else f"Key {key[4:].upper()}" if key.startswith("key_")
                 else f"Button {key.split('_')[1]}")
        specs.append(EntitySpec(key, label, platform="event"))
    if "ws201" in f:
        specs += [
            EntitySpec("remaining", "Remaining", unit="%", state_class="measurement", icon="mdi:paper-roll"),
            EntitySpec("distance", "Distance", unit="mm", device_class="distance", state_class="measurement",
                       icon="mdi:arrow-expand-vertical", enabled_default=False),
        ]
    if "ws202" in f:
        specs.append(EntitySpec("daylight", "Light", kind="label", icon="mdi:brightness-6"))
    if "ws203" in f:
        specs += _alarm("temperature", "Temperature", enabled=False)
    if "tamper" in f:
        specs.append(EntitySpec("tamper", "Tamper", platform="binary_sensor", device_class="tamper"))
    if "ws302" in f:
        db = dict(unit="dB", device_class="sound_pressure")
        specs += _measure("sound_level", "Sound level", "dB", "sound_pressure", precision=1)
        specs += [
            EntitySpec("sound_level_eq", "Sound level (Leq)", state_class="measurement", precision=1, **db),
            EntitySpec("sound_level_eq_max_today", "Sound level (Leq) max today", icon="mdi:arrow-collapse-up", precision=1, **db),
            EntitySpec("sound_level_max", "Sound level max (period)", state_class="measurement", precision=1, **db),
            EntitySpec("sound_weighting", "Sound weighting", kind="text", icon="mdi:tune-vertical", diagnostic=True),
        ]
    if "switch" in f:
        n = model.gangs
        dc = "outlet" if "socket" in f else "switch"
        for g in range(1, n + 1):
            label = ("Socket" if "socket" in f else "Switch") if n == 1 else f"Switch {g}"
            specs.append(EntitySpec(f"switch_{g}", label, platform="switch", device_class=dc))
        if model.control in ("ff29", "0829") and "ws_alarms" not in f and "socket" not in f:
            specs.append(EntitySpec("function_key_event", "Function key pressed", platform="binary_sensor",
                                    enabled_default=False, diagnostic=True))
    if "meter" in f:
        specs += _measure("power", "Power", "W", "power", precision=0)
        specs += [
            EntitySpec("energy", "Energy", unit="kWh", device_class="energy", state_class="total_increasing", precision=3),
            EntitySpec("voltage", "Voltage", unit="V", device_class="voltage", state_class="measurement", precision=1),
            EntitySpec("current", "Current", unit="A", device_class="current", state_class="measurement", precision=3),
            EntitySpec("power_factor", "Power factor", unit="%", device_class="power_factor", state_class="measurement"),
        ]
    if "ws_temp" in f:
        specs.append(EntitySpec("temperature", "Temperature", unit="°C", device_class="temperature",
                                state_class="measurement", precision=1))
        specs += _alarm("temperature", "Temperature", enabled=False)
    if "ws_alarms" in f:
        specs += [
            EntitySpec("overcurrent_alarm", "Overcurrent", platform="binary_sensor", device_class="problem"),
            EntitySpec("device_fault", "Device fault", platform="binary_sensor", device_class="problem"),
        ]
        if "socket" not in f:
            specs.append(EntitySpec("overtemperature_alarm", "Overtemperature", platform="binary_sensor",
                                    device_class="heat"))
        if "sensor_error" not in f:
            specs.append(EntitySpec("sensor_error", "Sensor status", kind="text", icon="mdi:alert-circle-outline",
                                    diagnostic=True))
    return specs


def _wt(model: "Model") -> list[EntitySpec]:
    f = model.features
    t = dict(unit="°C", device_class="temperature")
    specs = [EntitySpec("climate", "Thermostat", platform="climate")]
    if "wt30x" in f:
        specs += [
            EntitySpec("temperature", "Temperature", state_class="measurement", precision=1, **t),
            EntitySpec("target_temperature", "Target temperature", precision=1, enabled_default=False, **t),
            EntitySpec("mode", "Mode", kind="label", icon="mdi:thermostat"),
            EntitySpec("fan_speed", "Fan speed", kind="label", icon="mdi:fan"),
            EntitySpec("card_inserted", "Key card inserted", platform="binary_sensor", device_class="occupancy",
                       icon="mdi:card-account-details"),
            EntitySpec("button_lock", "Button lock", platform="binary_sensor", device_class="lock",
                       diagnostic=True, enabled_default=False),
            EntitySpec("control_mode", "Control mode", kind="label", icon="mdi:tune", diagnostic=True),
            EntitySpec("server_temperature", "Server temperature", precision=1, enabled_default=False, **t),
        ]
        return specs
    specs += _measure("temperature", "Temperature", "°C", "temperature", precision=1)
    specs.append(EntitySpec("target_temperature", "Target temperature", precision=1, enabled_default=False, **t))
    if "wt_hum" in f:
        specs.append(EntitySpec("humidity", "Humidity", unit="%", device_class="humidity", state_class="measurement",
                                precision=1))
    if "wt_valve" in f:
        specs += [
            EntitySpec("valve_opening", "Valve opening", unit="%", state_class="measurement", icon="mdi:valve"),
            EntitySpec("window_open", "Window open", platform="binary_sensor", device_class="window"),
            EntitySpec("freeze_protection", "Freeze protection", platform="binary_sensor", device_class="cold"),
            EntitySpec("tamper", "Removed from radiator", platform="binary_sensor", device_class="tamper"),
            EntitySpec("motor_calibration_result", "Motor calibration", kind="label", icon="mdi:cog", diagnostic=True),
            EntitySpec("motor_stroke", "Motor stroke", icon="mdi:arrow-expand-horizontal", diagnostic=True,
                       enabled_default=False),
            EntitySpec("motor_position", "Motor position", icon="mdi:arrow-collapse-horizontal", diagnostic=True,
                       enabled_default=False),
        ]
    if "wt102" in f:
        specs += [
            EntitySpec("target_valve_opening", "Target valve opening", unit="%", icon="mdi:valve", enabled_default=False),
            EntitySpec("battery_low_alarm", "Battery low", platform="binary_sensor", device_class="battery"),
            EntitySpec("mandatory_heating", "Mandatory heating", platform="binary_sensor", icon="mdi:fire-alert",
                       enabled_default=False),
            EntitySpec("auto_away", "Auto away", platform="binary_sensor", icon="mdi:home-export-outline",
                       enabled_default=False),
        ]
        specs += _alarm("temperature", "Temperature", enabled=False)
    if "wt_hvac" in f:
        specs += [
            EntitySpec("temperature_control_mode", "Mode", kind="label", icon="mdi:thermostat"),
            EntitySpec("temperature_control_status", "Status", kind="label", icon="mdi:hvac"),
            EntitySpec("execution_plan" if ("wt303" in f or "wt401" in f) else "plan_type", "Schedule", kind="label",
                       icon="mdi:calendar-clock"),
        ]
        if "wt401" not in f:
            specs += _alarm("temperature", "Temperature", enabled=False)
        if "wt303" not in f and "wt401" not in f:
            specs += [
                EntitySpec("target_temperature_2", "Target temperature 2", precision=1, enabled_default=False, **t),
                EntitySpec("relay", "Active relays", kind="text", icon="mdi:electric-switch", diagnostic=True),
                EntitySpec("supported_modes", "Supported modes", kind="text", icon="mdi:format-list-checks",
                           diagnostic=True, enabled_default=False),
                EntitySpec("temperature_source", "Temperature source", kind="label", icon="mdi:thermometer-lines",
                           diagnostic=True, enabled_default=False),
            ]
    if "wt_fan" in f:
        specs.append(EntitySpec("fan_mode", "Fan mode", kind="label", icon="mdi:fan"))
        if "wt401" not in f:
            specs.append(EntitySpec("fan_status", "Fan", kind="label", icon="mdi:fan-clock"))
    if "wt303" in f:
        specs += [
            EntitySpec("valve_opening", "Valve", unit="%", state_class="measurement", icon="mdi:valve"),
            EntitySpec("heating_target_temperature", "Heating target", precision=1, enabled_default=False, **t),
            EntitySpec("cooling_target_temperature", "Cooling target", precision=1, enabled_default=False, **t),
            EntitySpec("data_source", "Temperature source", kind="label", icon="mdi:thermometer-lines", diagnostic=True),
        ]
        specs += [EntitySpec(k, n, platform="binary_sensor", device_class="running", enabled_default=False)
                  for k, n in (("relay_low", "Fan low relay"), ("relay_medium", "Fan medium relay"),
                               ("relay_high", "Fan high relay"), ("valve_1", "Valve 1"), ("valve_2", "Valve 2"))]
    if "wt401" in f:
        specs += [
            EntitySpec("target_temperature_2", "Target temperature 2", precision=1, enabled_default=False, **t),
            EntitySpec("pir_status", "Presence", kind="label", icon="mdi:motion-sensor"),
            EntitySpec("power_bus_disconnected", "Power bus disconnected", platform="binary_sensor",
                       device_class="problem", enabled_default=False),
        ]
    return specs


def _new_ranges(model: "Model") -> list[EntitySpec]:
    f = model.features
    specs: list[EntitySpec] = []
    cnt = dict(state_class="measurement", icon="mdi:account-arrow-right")
    if "am10x_light" in f:
        specs += [
            EntitySpec("illuminance_lux", "Illuminance", unit="lx", device_class="illuminance", state_class="measurement"),
            EntitySpec("pir_activity", "Motion activity", state_class="measurement", icon="mdi:motion-sensor"),
            EntitySpec("infrared", "Infrared", diagnostic=True, enabled_default=False),
            EntitySpec("infrared_and_visible", "Infrared + visible", diagnostic=True, enabled_default=False),
        ]
    if "tvoc_ppb" in f:
        specs.append(EntitySpec("tvoc_ppb", "TVOC", unit="ppb", device_class="volatile_organic_compounds_parts",
                                state_class="measurement"))
    if "am30xl" in f:
        specs += [
            EntitySpec("illuminance_lux", "Illuminance", unit="lx", device_class="illuminance", state_class="measurement"),
            EntitySpec("pir_count", "Motion count", state_class="total_increasing", icon="mdi:counter"),
            EntitySpec("illuminance_alarm_status", "Light alarm", kind="label", icon="mdi:brightness-6",
                       enabled_default=False),
        ]
        specs += _alarm("temperature", "Temperature", enabled=False)
        if "co2" in f:
            specs += _alarm("co2", "CO2")
    if "ds3604" in f:
        specs.append(EntitySpec("current_template_id", "Template", icon="mdi:page-layout-body", diagnostic=True))
    if "em300cl" in f:
        specs += [
            EntitySpec("liquid", "Liquid level", kind="label", icon="mdi:waves"),
            EntitySpec("liquid_critical", "Liquid level critical", platform="binary_sensor", device_class="problem",
                       icon="mdi:waves-arrow-up"),
            EntitySpec("calibration_result", "Calibration", kind="label", icon="mdi:tune", diagnostic=True),
        ]
        specs += _alarm("liquid", "Liquid level", enabled=False)
    if "emtilt" in f:
        specs += [EntitySpec(f"angle_{a}", f"Angle {a.upper()}", unit="°", state_class="measurement",
                             icon="mdi:angle-acute", precision=2) for a in "xyz"]
        specs += [EntitySpec(f"angle_{a}_alarm", f"Angle {a.upper()} alarm", platform="binary_sensor",
                             device_class="problem", enabled_default=False) for a in "xyz"]
        specs.append(EntitySpec("tilt", "Tilted", platform="binary_sensor", device_class="problem", icon="mdi:angle-acute"))
    if "em310udl" in f:
        specs += _measure("distance", "Distance", "mm", "distance", icon="mdi:arrow-expand-vertical")
        specs.append(EntitySpec("tilted", "Tilted", platform="binary_sensor", device_class="problem", icon="mdi:angle-acute"))
    if "em320th" in f:
        specs += _alarm("temperature", "Temperature", enabled=False) + _alarm("humidity", "Humidity", enabled=False)
    if "rdl" in f:
        specs += [
            EntitySpec("radar_signal_rssi", "Radar signal", unit="dB", state_class="measurement", icon="mdi:radar",
                       diagnostic=True, precision=2),
            EntitySpec("distance_mutation", "Distance change", unit="mm", icon="mdi:delta", enabled_default=False),
        ]
        specs += _alarm("distance_exception", "Distance exception", enabled=False)
    if "peoplecount" in f:
        specs += [
            EntitySpec("people_in", "People in (last report)", **cnt),
            EntitySpec("people_out", "People out (last report)", state_class="measurement", icon="mdi:account-arrow-left"),
            EntitySpec("people_total_in", "People in (device total)", state_class="total_increasing",
                       icon="mdi:account-arrow-right"),
            EntitySpec("people_total_out", "People out (device total)", state_class="total_increasing",
                       icon="mdi:account-arrow-left"),
        ]
        for f_, label, icon in (("people_in", "People in", "mdi:account-arrow-right"),
                                ("people_out", "People out", "mdi:account-arrow-left")):
            for suffix, period, sc in (("today", "today", "total_increasing"), ("yesterday", "yesterday", None),
                                       ("week", "this week", "total_increasing"), ("last_week", "last week", None),
                                       ("month", "this month", "total_increasing"), ("last_month", "last month", None)):
                specs.append(EntitySpec(f"{f_}_{suffix}", f"{label} {period}", state_class=sc, icon=icon))
        specs.append(EntitySpec("people_net_today", "People inside (in − out today)", state_class="measurement",
                                icon="mdi:account-group"))
    if "vs35x" in f:
        specs += _alarm("total_count", "Total count", enabled=False) + _alarm("period_count", "Period count", enabled=False)
    if "vs35x_temp" in f:
        specs += _measure("temperature", "Temperature", "°C", "temperature", precision=1)
        specs += _alarm("temperature", "Temperature", enabled=False)
    if "vs351" in f:
        specs.append(EntitySpec("power_status", "Power source", kind="label", icon="mdi:power-plug-battery"))
    if "vs360" in f:
        specs.append(EntitySpec("battery_node", "Battery (receiver)", unit="%", device_class="battery",
                                state_class="measurement", diagnostic=True))
        specs += _alarm("counting_anomaly", "Counting anomaly") + _alarm("devices_misaligned", "Devices misaligned") \
            + _alarm("node_device_without_response", "Receiver not responding")
    if "vs330" in f:
        specs += [
            EntitySpec("distance", "Distance", unit="mm", device_class="distance", state_class="measurement",
                       enabled_default=False),
            EntitySpec("calibration_status", "Calibration", kind="label", icon="mdi:tune", diagnostic=True),
        ]
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
                  icon_on: str, with_left_open: bool, off_label: str | None = None,
                  events: str = "events") -> list[EntitySpec]:
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
        EntitySpec(f"{p}last_off_at", off_label or (f"{noun} last cleared" if prefix == "leak_" else f"{noun} last closed"),
                   kind="timestamp", device_class="timestamp"),
        EntitySpec(f"{p}last_duration_s", f"{noun} last {verb_on} duration", icon="mdi:history", **dur),
        EntitySpec(f"{p}today_s", f"{noun} {verb_on} today", icon="mdi:calendar-today", state_class="total_increasing", **dur),
        EntitySpec(f"{p}yesterday_s", f"{noun} {verb_on} yesterday", icon="mdi:calendar-arrow-left", **dur),
        EntitySpec(f"{p}week_s", f"{noun} {verb_on} this week", icon="mdi:calendar-week", state_class="total_increasing", **dur),
        EntitySpec(f"{p}last_week_s", f"{noun} {verb_on} last week", icon="mdi:calendar-week-begin", **dur),
        EntitySpec(f"{p}month_s", f"{noun} {verb_on} this month", icon="mdi:calendar-month", state_class="total_increasing", **dur),
        EntitySpec(f"{p}last_month_s", f"{noun} {verb_on} last month", icon="mdi:calendar-month-outline", **dur),
        EntitySpec(f"{p}count_today", f"{noun} {events} today", **cnt),
        EntitySpec(f"{p}count_yesterday", f"{noun} {events} yesterday", icon="mdi:counter"),
        EntitySpec(f"{p}count_week", f"{noun} {events} this week", **cnt),
        EntitySpec(f"{p}count_last_week", f"{noun} {events} last week", icon="mdi:counter"),
        EntitySpec(f"{p}count_month", f"{noun} {events} this month", **cnt),
        EntitySpec(f"{p}count_last_month", f"{noun} {events} last month", icon="mdi:counter"),
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
    if "em400" in f:
        specs += _measure("distance", "Distance", "mm", "distance", icon="mdi:arrow-expand-vertical")
        specs += _alarm("distance", "Distance")
        specs += _measure("temperature", "Temperature", "°C", "temperature", precision=1)
        specs += _alarm("temperature", "Temperature", enabled=False)
        specs.append(EntitySpec("tilted", "Tilted", platform="binary_sensor", device_class="problem",
                                icon="mdi:angle-acute"))
        if "fill" in f:
            specs.append(EntitySpec("fill_level", "Fill level", unit="%", state_class="measurement",
                                    icon="mdi:delete-variant", precision=0))
        else:
            specs.append(EntitySpec("fill_level", "Level", unit="%", state_class="measurement",
                                    icon="mdi:waves-arrow-up", precision=0, enabled_default=False))
    if "ct" in f:
        specs += _ct(f)
    specs += _gs(f)
    if "cth01" in f:
        specs += [
            EntitySpec("temperature", "Temperature", unit="°C", device_class="temperature", state_class="measurement",
                       precision=1),
            EntitySpec("voltage_unbalance", "Voltage unbalance", unit="%", state_class="measurement",
                       icon="mdi:scale-unbalanced", precision=2),
            EntitySpec("power_loss_alarm", "Power loss", platform="binary_sensor", device_class="problem",
                       icon="mdi:power-plug-off"),
        ]
    specs += _ws(model)
    specs += _new_ranges(model)
    if "wt" in f:
        specs += _wt(model)
    if "heating" in f:
        specs += [s for s in _binary_event("heating_", "Heating", "on", "heat", "mdi:fire", with_left_open=False,
                                             off_label="Heating last stopped", events="starts")
                  if s.key != "heating_active"] if model.climate else []
    if "cooling" in f:
        specs += [s for s in _binary_event("cooling_", "Cooling", "on", "cold", "mdi:snowflake", with_left_open=False,
                                             off_label="Cooling last stopped", events="starts")
                  if s.key != "cooling_active"] if model.climate else []
    if "motion" in f:
        specs += _binary_event("motion_", "Motion", "detected", "motion", "mdi:motion-sensor", with_left_open=False,
                               off_label="Motion last cleared")
    if "on" in f:
        specs += [s for s in _binary_event("on_", "Load", "on", "power", "mdi:power-plug", with_left_open=False,
                                             off_label="Load last switched off", events="switch-ons")
                  if s.key not in ("on_active", "on_status")]
    if "at101" in f:
        specs += _at101()
    if "moving" in f:
        specs += _binary_event("moving_", "Tracker", "moving", "moving", "mdi:truck-fast", with_left_open=False,
                               off_label="Tracker last stopped", events="trips")
    if "away" in f:
        specs += _binary_event("away_", "Geofence", "left", None, "mdi:map-marker-off", with_left_open=False,
                               off_label="Geofence last returned", events="exits")
    if "gas" in f:
        specs += _binary_event("gas_", "Gas", "detected", "gas", "mdi:gas-cylinder", with_left_open=False,
                               off_label="Gas last cleared")
    if "smoke" in f:
        specs += _binary_event("smoke_", "Smoke", "detected", "smoke", "mdi:smoke-detector-variant-alert",
                               with_left_open=False, off_label="Smoke last cleared")
    if "vape" in f:
        specs += _binary_event("vape_", "Vaping", "detected", None, "mdi:smoking", with_left_open=False,
                               off_label="Vaping last cleared")
    if "load" in f:
        specs += _binary_event("load_", "Load", "running", "running", "mdi:engine", with_left_open=False,
                               off_label="Load last stopped")
    if "uc11t1" in f:
        specs += _measure("temperature", "Temperature", "°C", "temperature", precision=1)
        specs += _measure("humidity", "Humidity", "%", "humidity", precision=1)
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
    specs += _command_specs(model_key)
    control = {s_.key for s_ in specs if s_.platform in ("switch", "number")}
    # a controllable output replaces its read-only binary sensor / sensor
    specs = [s_ for s_ in specs if not (s_.key in control and s_.platform in ("binary_sensor", "sensor"))]
    return specs + _common()
