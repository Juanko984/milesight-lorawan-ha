"""Uplink envelope parsing and Milesight payload decoders.

Pure Python (no Home Assistant imports) so it can be unit-tested on its own.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import struct
from decimal import ROUND_HALF_UP, Decimal
from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Callable
from typing import Any

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


# --------------------------------------------------------------------------
# Envelope (gateway / network server JSON)
# --------------------------------------------------------------------------
@dataclass
class Uplink:
    """A single uplink from the network server."""

    deveui: str
    raw: bytes | None = None
    predecoded: dict[str, Any] | None = None
    rssi: float | None = None
    snr: float | None = None
    time: datetime | None = None
    fport: int | None = None
    device_name: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return None


def _decode_bytes(value: str, encoding: str) -> bytes | None:
    value = value.strip()
    if not value:
        return b""
    if encoding == "hex":
        try:
            return bytes.fromhex(value)
        except ValueError:
            pass
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        pass
    if _HEX_RE.match(value) and len(value) % 2 == 0:
        return bytes.fromhex(value)
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def parse_envelope(payload: str | bytes, encoding: str = "base64") -> Uplink | None:
    """Parse a network-server uplink message. Returns None if it isn't one."""
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        msg = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(msg, dict):
        return None

    # Milesight gateway / generic
    deveui = _first(msg, "devEUI", "deveui", "devEui", "dev_eui", "DevEUI")
    # ChirpStack v4
    dev_info = msg.get("deviceInfo") if isinstance(msg.get("deviceInfo"), dict) else {}
    deveui = deveui or _first(dev_info, "devEui")
    # TTN v3
    ttn_ids = msg.get("end_device_ids") if isinstance(msg.get("end_device_ids"), dict) else {}
    deveui = deveui or _first(ttn_ids, "dev_eui")
    if not deveui or not isinstance(deveui, str):
        return None
    deveui = deveui.lower().replace(":", "").replace("-", "")

    ttn_up = msg.get("uplink_message") if isinstance(msg.get("uplink_message"), dict) else {}
    data = _first(msg, "data", "payload", "payload_raw", "frm_payload") or _first(ttn_up, "frm_payload")

    up = Uplink(deveui=deveui)
    if isinstance(data, dict):
        up.predecoded = data
    elif isinstance(data, str):
        up.raw = _decode_bytes(data, encoding)
    obj = _first(msg, "object", "decoded")
    if isinstance(obj, dict) and up.predecoded is None:
        up.predecoded = obj

    rx = msg.get("rxInfo")
    rx0 = rx[0] if isinstance(rx, list) and rx and isinstance(rx[0], dict) else {}
    ttn_rx = ttn_up.get("rx_metadata") if isinstance(ttn_up.get("rx_metadata"), list) else []
    ttn_rx0 = ttn_rx[0] if ttn_rx and isinstance(ttn_rx[0], dict) else {}

    up.rssi = _first(msg, "rssi") or _first(rx0, "rssi") or _first(ttn_rx0, "rssi")
    up.snr = _first(msg, "snr", "loRaSNR") or _first(rx0, "snr", "loRaSNR") or _first(ttn_rx0, "snr")
    up.time = _parse_time(_first(msg, "time", "received_at"))
    up.fport = _first(msg, "fPort", "fport", "port") or _first(ttn_up, "f_port")
    up.device_name = _first(msg, "deviceName", "device_name") or _first(dev_info, "deviceName")
    return up


# --------------------------------------------------------------------------
# Byte helpers
# --------------------------------------------------------------------------
def _u16le(b: bytes, i: int) -> int:
    return b[i] | (b[i + 1] << 8)


def _i16le(b: bytes, i: int) -> int:
    v = _u16le(b, i)
    return v - 0x10000 if v > 0x7FFF else v


def _u16be(b: bytes, i: int) -> int:
    return (b[i] << 8) | b[i + 1]


def _u32le(b: bytes, i: int) -> int:
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)


def _need(b: bytes, i: int, n: int) -> bool:
    return i + n <= len(b)


def _decode_common(cid: int, ctype: int, b: bytes, i: int, out: dict) -> int | None:
    """Device-info channels shared by Milesight devices. Returns bytes consumed or None."""
    if cid != 0xFF:
        return None
    if ctype == 0x01 and _need(b, i, 1):
        out["protocol_version"] = b[i]
        return 1
    if ctype == 0x08 and _need(b, i, 6):
        out["sn"] = b[i:i + 6].hex()
        return 6
    if ctype == 0x16 and _need(b, i, 8):
        out["sn"] = b[i:i + 8].hex()
        return 8
    if ctype == 0x09 and _need(b, i, 2):
        out["hardware_version"] = f"v{b[i]:x}.{b[i + 1] >> 4}"
        return 2
    if ctype == 0x0A and _need(b, i, 2):
        out["firmware_version"] = f"v{b[i]:x}.{b[i + 1]:x}"
        return 2
    if ctype == 0x1F and _need(b, i, 4):
        out["firmware_version"] = ".".join(str(x) for x in b[i:i + 4])
        return 4
    if ctype == 0x0F and _need(b, i, 1):
        out["lorawan_class"] = {0: "Class A", 1: "Class B", 2: "Class C", 3: "Class CtoB"}.get(b[i], "unknown")
        return 1
    if ctype == 0xFE and _need(b, i, 1):
        out["reset_event"] = b[i] == 1
        return 1
    if ctype == 0x0B and _need(b, i, 1):
        out["device_status"] = "on" if b[i] else "off"
        return 1
    if ctype == 0xFF and _need(b, i, 2):
        out["tsl_version"] = f"v{b[i]}.{b[i + 1]}"
        return 2
    return None


# --------------------------------------------------------------------------
# VS121 people counter
# --------------------------------------------------------------------------
def decode_vs121(b: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x04 and ctype == 0xC9 and _need(b, i, 4):
            out["people_count_all"] = b[i]
            out["region_count"] = b[i + 1]
            mask = _u16be(b, i + 2)
            for r in range(b[i + 1]):
                out[f"region_{r + 1}"] = (mask >> r) & 1
            i += 4
        elif cid == 0x05 and ctype == 0xCC and _need(b, i, 4):
            out["people_in"] = _i16le(b, i)
            out["people_out"] = _i16le(b, i + 2)
            i += 4
        elif cid == 0x06 and ctype == 0xCD and _need(b, i, 1):
            out["people_count_max"] = b[i]
            i += 1
        elif cid in (0x07, 0x08) and ctype == 0xD5 and _need(b, i, 8):
            base = 1 if cid == 0x07 else 9
            for r in range(8):
                out[f"region_{base + r}_count"] = b[i + r]
            i += 8
        elif 0x09 <= cid <= 0x0C and ctype == 0xDA and _need(b, i, 8):
            src = "abcd"[cid - 0x09]
            for k, dst in enumerate("abcd"):
                out[f"{src}_to_{dst}"] = _u16le(b, i + 2 * k)
            i += 8
        elif cid == 0x0D and ctype == 0xCC and _need(b, i, 4):
            out["people_total_in"] = _u16le(b, i)
            out["people_total_out"] = _u16le(b, i + 2)
            i += 4
        elif cid == 0x0E and ctype == 0xE4 and _need(b, i, 5):
            out["dwell_time_avg"] = _u16le(b, i + 1)
            out["dwell_time_max"] = _u16le(b, i + 3)
            i += 5
        elif cid == 0x0F and ctype == 0x85 and _need(b, i, 4):
            out["device_timestamp"] = _u32le(b, i)
            i += 4
        else:
            break
    return out


# --------------------------------------------------------------------------
# EM300 family (TH / MCS / SLD / ZLD / DI)
# Channel map checked against Milesight-IoT/SensorDecoders (em-series).
# --------------------------------------------------------------------------
def decode_em300(b: bytes) -> dict[str, Any]:
    """Decode an EM300-family uplink.

    0x06/0x00 = magnet (EM300-MCS, 1 = open)
    0x05/0x00 = leak (EM300-SLD/ZLD, 1 = leak) or GPIO (EM300-DI) -> ``input_05``
    """
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x67 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x04 and ctype == 0x68 and _need(b, i, 1):
            out["humidity"] = b[i] / 2
            i += 1
        elif cid == 0x06 and ctype == 0x00 and _need(b, i, 1):
            out["magnet_status"] = 1 if b[i] else 0
            i += 1
        elif cid == 0x05 and ctype == 0x00 and _need(b, i, 1):
            out["input_05"] = 1 if b[i] else 0
            i += 1
        elif cid == 0x85 and ctype == 0x00 and _need(b, i, 2):   # EM300-DI GPIO alarm
            out["input_05"] = 1 if b[i] else 0
            out["gpio_alarm"] = b[i + 1]
            i += 2
        elif cid == 0x05 and ctype == 0xC8 and _need(b, i, 4):   # EM300-DI pulse counter
            out["pulse_count"] = _u32le(b, i)
            i += 4
        elif cid in (0x05, 0x85) and ctype == 0xE1 and _need(b, i, 8):  # EM300-DI water meter (v1.3+)
            out["water_conv"] = _u16le(b, i) / 10
            out["pulse_conv"] = _u16le(b, i + 2) / 10
            out["water"] = _f32(b, i + 4, True)
            i += 8
            if cid == 0x85 and _need(b, i, 1):
                out["water_alarm"] = b[i]
                i += 1
        else:
            break  # history / downlink response / unknown – stop safely
    return out


# --------------------------------------------------------------------------
# AM300 indoor air quality (AM307 / AM308 / AM319 incl. L variants)
# Channel map checked against Milesight-IoT/SensorDecoders (am-series).
# --------------------------------------------------------------------------
def decode_am300(b: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x67 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x04 and ctype == 0x68 and _need(b, i, 1):
            out["humidity"] = b[i] / 2
            i += 1
        elif cid == 0x05 and ctype == 0x00 and _need(b, i, 1):
            out["pir"] = 1 if b[i] else 0
            i += 1
        elif cid == 0x06 and ctype == 0xCB and _need(b, i, 1):
            out["light_level"] = b[i]
            i += 1
        elif cid == 0x07 and ctype == 0x7D and _need(b, i, 2):
            out["co2"] = _u16le(b, i)
            i += 2
        elif cid == 0x08 and ctype == 0x7D and _need(b, i, 2):
            out["tvoc_iaq"] = _u16le(b, i) / 100
            i += 2
        elif cid == 0x08 and ctype == 0xE6 and _need(b, i, 2):
            out["tvoc"] = _u16le(b, i)
            i += 2
        elif cid == 0x09 and ctype == 0x73 and _need(b, i, 2):
            out["pressure"] = _u16le(b, i) / 10
            i += 2
        elif cid == 0x0A and ctype == 0x7D and _need(b, i, 2):
            out["hcho"] = _u16le(b, i) / 100
            i += 2
        elif cid == 0x0B and ctype == 0x7D and _need(b, i, 2):
            out["pm2_5"] = _u16le(b, i)
            i += 2
        elif cid == 0x0C and ctype == 0x7D and _need(b, i, 2):
            out["pm10"] = _u16le(b, i)
            i += 2
        elif cid == 0x0D and ctype == 0x7D and _need(b, i, 2):
            out["o3"] = _u16le(b, i) / 100
            i += 2
        elif cid == 0x0E and ctype == 0x01 and _need(b, i, 1):
            out["buzzer"] = 1 if b[i] else 0
            i += 1
        elif cid == 0x0F and ctype == 0x7D and _need(b, i, 2):   # AM319 HCHO (Well sensor)
            out["hcho"] = _u16le(b, i) / 1000
            i += 2
        else:
            break  # history / downlink response / unknown – stop safely
    return out


# --------------------------------------------------------------------------
# VS-series (radar / ToF / PIR occupancy) – checked against Milesight-IoT/SensorDecoders
# --------------------------------------------------------------------------
_OCC = {0: "vacant", 1: "occupied"}
_ILLUM = {0: "dim", 1: "bright", 254: "disable"}


def _map(m: dict, v: int) -> str:
    return m.get(v, "unknown")


def decode_vs_occupancy(b: bytes) -> dict[str, Any]:
    """VS340 / VS341 desk occupancy, VS370 radar occupancy (+ illuminance)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x00 and _need(b, i, 1):
            out["occupancy"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid == 0x04 and ctype == 0x00 and _need(b, i, 1):
            out["illuminance"] = _map(_ILLUM, b[i])
            i += 1
        else:
            break
    return out


def decode_vs321(b: bytes) -> dict[str, Any]:
    """VS321 AI occupancy & people counting sensor (with temperature / humidity)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid in (0x03, 0x83) and ctype == 0x67 and _need(b, i, 2):
            if cid == 0x03 and _u16le(b, i) == 0xFFFF:
                out["temperature_sensor_status"] = "read_failed"
            else:
                out["temperature"] = _i16le(b, i) / 10
            i += 2
            if cid == 0x83 and _need(b, i, 1):
                out["temperature_alarm"] = b[i]
                i += 1
        elif cid in (0x04, 0x84) and ctype == 0x68 and _need(b, i, 1):
            if cid == 0x04 and b[i] == 0xFF:
                out["humidity_sensor_status"] = "read_failed"
            else:
                out["humidity"] = b[i] / 2
            i += 1
            if cid == 0x84 and _need(b, i, 1):
                out["humidity_alarm"] = b[i]
                i += 1
        elif cid == 0x05 and ctype == 0xFD and _need(b, i, 2):
            out["people_count_all"] = _u16le(b, i)
            i += 2
        elif cid == 0x06 and ctype == 0xFE and _need(b, i, 4):
            mask, data = _u16le(b, i), _u16le(b, i + 2)
            for r in range(10):
                out[f"region_{r + 1}_enable"] = "enable" if (mask >> r) & 1 else "disable"
                out[f"region_{r + 1}"] = (data >> r) & 1
            i += 4
        elif cid == 0x07 and ctype == 0xFF and _need(b, i, 1):
            out["illuminance"] = _map(_ILLUM, b[i])
            i += 1
        elif cid == 0x08 and ctype == 0xF4 and _need(b, i, 2):
            out["detection_status"] = _map({0: "normal", 1: "unavailable"}, b[i + 1])
            i += 2
        elif cid == 0x0A and ctype == 0xEF and _need(b, i, 4):
            out["device_timestamp"] = _u32le(b, i)
            i += 4
        else:
            break
    return out


_VS373_DETECTION = {0: "normal", 1: "vacant", 2: "in_bed", 3: "out_of_bed", 4: "fall"}
_VS373_TARGET = {0: "normal", 1: "motionless", 2: "abnormal", 3: "lying_down"}
_VS373_BREATH = {1: "no_data_input", 2: "normal", 3: "tachypnea", 4: "bradypnea", 5: "undetectable"}
_VS373_REGION_TYPE = {0: "custom", 1: "bed", 2: "door", 3: "ignore", 255: "unset"}
VS373_ALARM_TYPE = {0: "fall", 1: "motionless", 2: "dwell", 3: "out_of_bed", 4: "occupied",
                    5: "vacant", 6: "bradynea", 7: "tachypnea", 8: "lying_down"}
VS373_ALARM_STATUS = {1: "alarm_triggered", 2: "alarm_deactivated", 3: "alarm_ignored", 4: "respiratory_status"}


def _u24le(b: bytes, i: int) -> int:
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16)


def decode_vs373(b: bytes) -> dict[str, Any]:
    """VS373 radar fall detection sensor."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x03 and ctype == 0xF8 and _need(b, i, 6):          # firmware v1.0.1
            out["detection_status"] = _map(_VS373_DETECTION, b[i])
            out["target_status"] = _map(_VS373_TARGET, b[i + 1])
            out["use_time_now"] = _u16le(b, i + 2)
            out["use_time_today"] = _u16le(b, i + 4)
            i += 6
        elif cid == 0x07 and ctype == 0xB0 and _need(b, i, 8):          # firmware v1.0.2+
            out["detection_status"] = _map(_VS373_DETECTION, b[i])
            out["target_status"] = _map(_VS373_TARGET, b[i + 1])
            out["use_time_now"] = _u24le(b, i + 2)
            out["use_time_today"] = _u24le(b, i + 5)
            i += 8
        elif cid == 0x04 and ctype == 0xF9 and _need(b, i, 4):          # v1.0.1: 0 = occupied
            for r in range(4):
                out[f"region_{r + 1}_occupancy"] = 0 if b[i + r] == 1 else 1
            i += 4
        elif cid == 0x09 and ctype == 0xB2 and _need(b, i, 6):
            for r in range(6):
                out[f"region_{r + 1}_type"] = _map(_VS373_REGION_TYPE, b[i + r])
            i += 6
        elif cid == 0x0A and ctype == 0xB3 and _need(b, i, 5):
            data = _u32le(b, i + 1)
            for r in range(b[i]):
                out[f"region_{r + 1}_occupancy"] = (data >> r) & 1
            i += 5
        elif cid == 0x05 and ctype == 0xFA and _need(b, i, 8):
            for r in range(4):
                out[f"region_{r + 1}_out_of_bed_time"] = _u16le(b, i + 2 * r)
            i += 8
        elif cid in (0x0B, 0x0C) and ctype == 0xB4 and _need(b, i, 9):
            base = 1 if cid == 0x0B else 4
            for r in range(3):
                out[f"region_{base + r}_out_of_bed_time"] = _u24le(b, i + 3 * r)
            i += 9
        elif cid == 0x06 and ctype == 0xFB and _need(b, i, 5):
            ev: dict[str, Any] = {
                "alarm_id": _u16le(b, i),
                "alarm_type": _map(VS373_ALARM_TYPE, b[i + 2]),
                "alarm_status": _map(VS373_ALARM_STATUS, b[i + 3]),
            }
            if b[i + 2] in (3, 6, 7):
                ev["region_id"] = b[i + 4]
            out.setdefault("events", []).append(ev)
            i += 5
        elif cid == 0x08 and ctype == 0xB1 and _need(b, i, 3):
            out["respiratory_status"] = _map(_VS373_BREATH, b[i])
            out["respiratory_rate"] = _u16le(b, i + 1) / 100
            i += 3
        else:
            break
    return out


# --------------------------------------------------------------------------
# EM500 range (CO2 / LGT / PP / PT100 / SMTC / SWL / UDL)
# Checked against Milesight-IoT/SensorDecoders (em-series/em500-*).
# --------------------------------------------------------------------------
_SENSOR_ERR = {0xFFFF: "collection failed", 0xFFFD: "out of range"}


def _em500_value(out: dict, key: str, raw: int, value: float | int) -> None:
    """Store a reading, or a sensor error for Milesight's 0xFFFF / 0xFFFD markers."""
    if raw in _SENSOR_ERR:
        out[f"{key}_error"] = _SENSOR_ERR[raw]
        out["sensor_error"] = f"{key.replace('_', ' ').capitalize()}: {_SENSOR_ERR[raw]}"
    else:
        out[key] = value


def decode_em500(b: bytes, soil: bool = False) -> dict[str, Any]:
    """Generic EM500 decoder. With ``soil`` (EM500-SMTC) 0x04/0x68 is soil moisture, not humidity."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0xFF and ctype == 0x1B and _need(b, i, 5):           # measuring equipment info
            out["range_max"] = _i16le(b, i + 1)
            out["range_min"] = _i16le(b, i + 3)
            i += 5
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x67 and _need(b, i, 2):
            _em500_value(out, "temperature", _u16le(b, i), _i16le(b, i) / 10)
            i += 2
        elif cid == 0x83 and ctype == 0xD7 and _need(b, i, 5):           # temperature with alarm
            out["temperature"] = _i16le(b, i) / 10
            out["temperature_mutation"] = _i16le(b, i + 2) / 10
            out["temperature_alarm"] = b[i + 4]
            i += 5
        elif cid == 0x04 and ctype == 0x68 and _need(b, i, 1):
            out["moisture" if soil else "humidity"] = b[i] / 2
            i += 1
        elif cid == 0x04 and ctype == 0xCA and _need(b, i, 2):           # EM500-SMTC moisture (new fw)
            raw = _u16le(b, i)
            _em500_value(out, "moisture", raw, raw / 100)
            i += 2
        elif cid == 0x05 and ctype == 0x7D and _need(b, i, 2):
            out["co2"] = _u16le(b, i)
            i += 2
        elif cid == 0x06 and ctype == 0x73 and _need(b, i, 2):
            out["pressure"] = _u16le(b, i) / 10                          # hPa (EM500-CO2)
            i += 2
        elif cid == 0x03 and ctype == 0x7B and _need(b, i, 2):
            out["pressure_kpa"] = _i16le(b, i)                           # kPa (EM500-PP)
            i += 2
        elif cid == 0x03 and ctype == 0x94 and _need(b, i, 4):
            out["illumination"] = _u32le(b, i)
            i += 4
        elif cid == 0x05 and ctype == 0x7F and _need(b, i, 2):
            raw = _u16le(b, i)
            _em500_value(out, "electricity", raw, raw)
            i += 2
        elif cid == 0x03 and ctype == 0x77 and _need(b, i, 2):
            raw = _u16le(b, i)
            _em500_value(out, "depth", raw, raw)
            i += 2
        elif cid == 0x03 and ctype == 0x82 and _need(b, i, 2):
            out["distance"] = _u16le(b, i)
            i += 2
        elif cid == 0x83 and ctype == 0xE9 and _need(b, i, 5):           # distance with alarm
            out["distance"] = _u16le(b, i) / 10
            out["distance_mutation"] = _u16le(b, i + 2) / 10
            out["distance_alarm"] = b[i + 4]
            i += 5
        else:
            break
    if not any(k.endswith("_error") for k in out) and any(
            k in out for k in ("temperature", "moisture", "electricity", "depth")):
        out["sensor_error"] = "OK"
    return out


def decode_em500_smtc(b: bytes) -> dict[str, Any]:
    """EM500-SMTC soil sensor: 0x04/0x68 is soil moisture, not air humidity."""
    return decode_em500(b, soil=True)


# --------------------------------------------------------------------------
# TS range – TS101 / TS201 / TS301 / TS302 (channel format) and TS601 / TS602 (command format)
# Checked against Milesight-IoT/SensorDecoders (ts-series). Alarm codes are normalised to
#   <name>_alarm_active (True / False) and <name>_alarm_status (text)
# --------------------------------------------------------------------------
# Older firmware (TS101, TS201, TS301/TS302 v1): 0 = release, 1 = threshold alarm, 2 = mutation alarm
_TS_ALARM_OLD = {0: ("threshold_alarm_release", False), 1: ("threshold_alarm", True), 2: ("mutation_alarm", None)}
# Current firmware (TS301/TS302 v2)
_TS_ALARM_NEW = {
    0: ("above_threshold_alarm", True), 1: ("above_threshold_alarm_release", False),
    2: ("below_threshold_alarm", True), 3: ("below_threshold_alarm_release", False),
    4: ("between_threshold_alarm", True), 5: ("between_threshold_alarm_release", False),
    6: ("outside_threshold_alarm", True), 7: ("outside_threshold_alarm_release", False),
    8: ("mutation_alarm", None),
}
_TS_STATUS_OLD = {0: "read error", 1: "out of range"}                         # TS201
_TS_STATUS_NEW = {0: "collection failed", 1: "over range", 2: "under range"}  # TS301/302 v2


def _ts_alarm(out: dict, name: str, code: int, table: dict) -> None:
    text, active = table.get(code, ("unknown", None))
    out[f"{name}_alarm_status"] = text
    if active is not None:
        out[f"{name}_alarm_active"] = active


def _decode_ts(b: bytes, *, dual: bool, new_alarms: bool, status_map: dict) -> dict[str, Any]:
    alarms = _TS_ALARM_NEW if new_alarms else _TS_ALARM_OLD
    out: dict[str, Any] = {}

    def key(base: str, cid: int) -> str:
        if not dual:
            return base
        return f"{base}_{(cid & 0x0F) - 2}"          # 0x?3 -> _1, 0x?4 -> _2

    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        hi = cid & 0xF0
        lo = cid & 0x0F
        if n is not None:
            i += n
        elif cid == 0xFF and ctype == 0xA0 and _need(b, i, 9):        # probe sensor ID
            out["probe_sn"] = b[i + 1:i + 9].hex()
            i += 9
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif lo in (3, 4) and hi in (0x00, 0x80, 0x90, 0xB0) and (
                (dual and ctype != 0x68) or (not dual and (lo == 3 or ctype == 0x68))):
            # TS302 never uses 0x68; single-probe models only use channel 4 for TS201 v2 humidity (0x68)
            # 0x03/0x04 data, 0x83/0x84 threshold alarm, 0x93/0x94 mutation alarm, 0xB3/0xB4 sensor status
            if ctype == 0x67:
                name, size, read = "temperature", 2, lambda j: _i16le(b, j) / 10
            elif ctype == 0x9A:
                name, size, read = "humidity", 2, lambda j: _i16le(b, j) / 10
            elif ctype == 0x68:
                name, size, read = "humidity", 1, lambda j: b[j] / 2
            elif ctype == 0xD7 and hi == 0x90:                          # older mutation alarm (/100)
                name, size, read = "temperature", 2, lambda j: _i16le(b, j) / 10
            elif ctype == 0x00 and hi == 0x00:
                if not _need(b, i, 1):
                    break
                out[key("magnet_status", cid)] = 1 if b[i] else 0
                i += 1
                continue
            else:
                break
            k = key(name, cid)
            if hi == 0xB0:                                               # sensor status
                if not _need(b, i, 1):
                    break
                out[f"{k}_sensor_status"] = status_map.get(b[i], "unknown")
                out["sensor_error"] = f"{k.replace('_', ' ').capitalize()}: {status_map.get(b[i], 'unknown')}"
                i += 1
                continue
            if not _need(b, i, size):
                break
            out[k] = read(i)
            i += size
            if hi == 0x80:                                               # threshold alarm: value + code
                if not _need(b, i, 1):
                    break
                _ts_alarm(out, k, b[i], alarms)
                i += 1
            elif hi == 0x90:                                             # mutation alarm
                if ctype == 0xD7:
                    if not _need(b, i, 3):
                        break
                    out[f"{k}_mutation"] = _i16le(b, i) / 100
                    _ts_alarm(out, k, b[i + 2], alarms)
                    i += 3
                elif ctype == 0x68:                                      # TS201 v2 humidity mutation
                    if not _need(b, i, 2):
                        break
                    out[f"{k}_mutation"] = b[i] / 2
                    _ts_alarm(out, k, b[i + 1], alarms)
                    i += 2
                else:
                    if not _need(b, i, 3):
                        break
                    out[f"{k}_mutation"] = _i16le(b, i) / 10
                    _ts_alarm(out, k, 8 if new_alarms else b[i + 2], alarms)
                    i += 3
        else:
            break   # history / downlink response / unknown – stop safely
    if "sensor_error" not in out and any(k.startswith("temperature") and isinstance(v, float) for k, v in out.items()):
        out["sensor_error"] = "OK"
    return out


def decode_ts101(b: bytes) -> dict[str, Any]:
    return _decode_ts(b, dual=False, new_alarms=False, status_map=_TS_STATUS_OLD)


def decode_ts201(b: bytes) -> dict[str, Any]:
    return _decode_ts(b, dual=False, new_alarms=False, status_map=_TS_STATUS_OLD)


def decode_ts301(b: bytes) -> dict[str, Any]:
    return _decode_ts(b, dual=False, new_alarms=True, status_map=_TS_STATUS_NEW)


def decode_ts301_v1(b: bytes) -> dict[str, Any]:
    return _decode_ts(b, dual=False, new_alarms=False, status_map=_TS_STATUS_NEW)


def decode_ts302(b: bytes) -> dict[str, Any]:
    return _decode_ts(b, dual=True, new_alarms=True, status_map=_TS_STATUS_NEW)


def decode_ts302_v1(b: bytes) -> dict[str, Any]:
    return _decode_ts(b, dual=True, new_alarms=False, status_map=_TS_STATUS_NEW)


# ---- TS601 / TS602 (single-byte command format) ---------------------------
_TS60X_LEVEL_ALARM = {
    0x00: ("collection_error", None), 0x01: ("below_range_error", None), 0x02: ("above_range_error", None),
    0x03: ("no_data", None),
    0x10: ("below_alarm_released", False), 0x11: ("below_alarm", True),
    0x12: ("above_alarm_released", False), 0x13: ("above_alarm", True),
    0x14: ("between_alarm_released", False), 0x15: ("between_alarm", True),
    0x16: ("exceed_tolerance_alarm_released", False), 0x17: ("exceed_tolerance_alarm", True),
    0x20: ("mutation_alarm", None), 0x30: ("mutation_alarm", None),
}
_TS60X_TILT_ALARM = {0x00: ("collection_error", None), 0x01: ("below_range_error", None),
                     0x02: ("above_range_error", None), 0x03: ("no_data", None),
                     0x10: ("tilt_alarm_released", False), 0x11: ("tilt_alarm", True), 0x21: ("falling_alarm", None)}
_TS60X_LIGHT_ALARM = {0x00: ("collection_error", None), 0x01: ("below_range_error", None),
                      0x02: ("above_range_error", None), 0x03: ("no_data", None),
                      0x10: ("bright_to_dark", False), 0x11: ("dark_to_bright", True)}
_TS60X_SENSOR_TYPE = {0: "none", 1: "PT100", 2: "SHT41", 3: "DS18B20"}


def _i32le(b: bytes, i: int) -> int:
    v = _u32le(b, i)
    return v - 0x100000000 if v > 0x7FFFFFFF else v


def decode_ts60x(b: bytes) -> dict[str, Any]:
    """TS601 / TS602 cold-chain sensor. Stops at history records and configuration replies."""
    return _parse_ts60x(b)[0]


def ts60x_parses_completely(b: bytes) -> bool:
    out, consumed = _parse_ts60x(b)
    return consumed >= len(b) and bool(out)


def _parse_ts60x(b: bytes) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    i = 0

    def alarm(name: str, code: int, table: dict) -> None:
        text, active = table.get(code, ("unknown", None))
        out[f"{name}_alarm_status"] = text
        if active is not None:
            out[f"{name}_alarm_active"] = active
        if code in (0x00, 0x01, 0x02):
            out["sensor_error"] = f"{name.capitalize()}: {text.replace('_', ' ')}"

    fixed = {0xDF: 2, 0xDE: 32, 0xDD: 32, 0xDB: 8, 0xDA: 8, 0xD9: 2, 0xC9: 1, 0xC8: 1, 0xD8: 16}
    while i < len(b):
        cmd = b[i]
        i += 1
        if cmd in fixed and _need(b, i, fixed[cmd]):
            if cmd == 0xDA:
                out["hardware_version"] = f"v{b[i]}.{b[i + 1]}"
                out["firmware_version"] = ".".join(str(x) for x in b[i + 2:i + 8] if x) or None
            elif cmd == 0xDB:
                out["sn"] = b[i:i + 8].hex()
            i += fixed[cmd]
        elif cmd == 0x01 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cmd == 0x03 and _need(b, i, 9):
            out["probe_type"] = _TS60X_SENSOR_TYPE.get(b[i], "unknown")
            out["probe_sn"] = b[i + 1:i + 9].hex()
            i += 9
        elif cmd == 0x04 and _need(b, i, 4):
            out["temperature"] = round(_i32le(b, i) / 100, 2)
            out.setdefault("sensor_error", "OK")
            i += 4
        elif cmd == 0x05 and _need(b, i, 2):
            out["humidity"] = _u16le(b, i) / 10
            i += 2
        elif cmd == 0x06 and _need(b, i, 8):
            out["latitude"] = _i32le(b, i) / 1_000_000
            out["longitude"] = _i32le(b, i + 4) / 1_000_000
            i += 8
        elif cmd == 0x07 and _need(b, i, 1):
            out["airplane_mode"] = b[i] == 0          # 0 = entered airplane mode
            i += 1
        elif cmd in (0x08, 0x1A) and _need(b, i, 1):  # temperature alarm (0x1A = type only)
            code = b[i]
            i += 1
            alarm("temperature", code, _TS60X_LEVEL_ALARM)
            if cmd == 0x08:
                if 0x10 <= code <= 0x17 or code == 0x30:
                    if not _need(b, i, 4):
                        break
                    out["temperature"] = round(_i32le(b, i) / 100, 2)
                    i += 4
                elif code == 0x20:
                    if not _need(b, i, 8):
                        break
                    out["temperature"] = round(_i32le(b, i) / 100, 2)
                    out["temperature_mutation"] = round(_i32le(b, i + 4) / 100, 2)
                    i += 8
        elif cmd in (0x09, 0x1B) and _need(b, i, 1):  # humidity alarm
            code = b[i]
            i += 1
            alarm("humidity", code, _TS60X_LEVEL_ALARM)
            if cmd == 0x09:
                if 0x10 <= code <= 0x17 or code == 0x30:
                    if not _need(b, i, 2):
                        break
                    out["humidity"] = _u16le(b, i) / 10
                    i += 2
                elif code == 0x20:
                    if not _need(b, i, 4):
                        break
                    out["humidity"] = _u16le(b, i) / 10
                    out["humidity_mutation"] = _u16le(b, i + 2) / 10
                    i += 4
        elif cmd in (0x0A, 0x1C) and _need(b, i, 1):
            alarm("tilt", b[i], _TS60X_TILT_ALARM)
            if b[i] == 0x21:
                out["last_fall_alarm"] = True
            i += 1
        elif cmd in (0x0B, 0x1D) and _need(b, i, 1):
            alarm("light", b[i], _TS60X_LIGHT_ALARM)
            i += 1
        elif cmd == 0x0C and _need(b, i, 1):
            out["probe_connected"] = b[i] == 1
            i += 1
        elif cmd == 0x0D and _need(b, i, 6):
            out["angle_x"] = _i16le(b, i) / 100
            out["angle_y"] = _i16le(b, i + 2) / 100
            out["angle_z"] = _i16le(b, i + 4) / 100
            i += 6
        elif cmd == 0x0E and _need(b, i, 1):
            out["report_package_type"] = b[i]
            i += 1
        elif cmd == 0x11 and _need(b, i, 1):
            code = b[i]
            i += 1
            if code == 0x10 and _need(b, i, 1):
                out["battery_low_alarm"] = True
                out["battery"] = b[i]
                i += 1
        else:
            i -= 1
            break   # history (0xED), configuration replies, unknown – stop safely
    return out, i


# --------------------------------------------------------------------------
# UC range – controllers (UC11xx, UC11-N1, UC11-T1, UC300, UC501/502, UC511/512, UC521, UC100)
# Checked against Milesight-IoT/SensorDecoders (uc-series). Channel sets depend on how the
# controller is configured, so these decoders produce numbered keys (gpio_input_1, modbus_chn_3 …)
# and the integration creates entities as keys appear.
# --------------------------------------------------------------------------
def _to_fixed2(f: float) -> float:
    """JavaScript Number(f.toFixed(2)): exact ties round away from zero (Python's round() doesn't)."""
    if f != f or f in (float("inf"), float("-inf")):
        return f
    return float(Decimal(f).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _f32(b: bytes, i: int, rnd: bool) -> float:
    bits = _u32le(b, i)
    sign = -1.0 if bits >> 31 else 1.0
    e = (bits >> 23) & 0xFF
    m = (bits & 0x7FFFFF) << 1 if e == 0 else (bits & 0x7FFFFF) | 0x800000
    f = sign * m * 2.0 ** (e - 150)
    return _to_fixed2(f) if rnd else f


def _f16(b: bytes, i: int, rnd: bool) -> float:
    bits = _u16le(b, i)
    sign = -1.0 if bits >> 15 else 1.0
    e = (bits >> 10) & 0x1F
    m = (bits & 0x3FF) << 1 if e == 0 else (bits & 0x3FF) | 0x400
    f = sign * m * 2.0 ** (e - 25)
    return _to_fixed2(f) if rnd else f


def _f64(b: bytes, i: int) -> float:
    return struct.unpack_from("<d", b, i)[0]


def _i8(v: int) -> int:
    return v - 0x100 if v > 0x7F else v


def _modbus_value(b: bytes, i: int, dtype: int, sign: bool, rnd: bool, *,
                  bool_types: tuple[int, ...] = (0,), raw_bytes: bool = False,
                  hi_word: bool = False) -> tuple[Any, int] | None:
    """Milesight Modbus data types → (value, bytes consumed).

    bool_types: data types reported as on/off (1/0); raw_bytes: types 0/1 as the raw byte (UC11xx);
    hi_word: types 9/11 take the upper 16 bits of a 32-bit register pair (UC300).
    """
    if not _need(b, i, 1):
        return None
    if dtype in (0, 1):
        if raw_bytes:
            return b[i], 1
        if dtype in bool_types:
            return (1 if b[i] == 1 else 0), 1
        return (_i8(b[i]) if sign else b[i]), 1
    if dtype in (2, 3):
        return (_i16le(b, i) if sign else _u16le(b, i)), 2
    if dtype in (4, 6):
        return (_i32le(b, i) if sign else _u32le(b, i)), 4
    if dtype in (8, 9, 10, 11):
        j = i + 2 if hi_word and dtype in (9, 11) else i
        return (_i16le(b, j) if sign else _u16le(b, j)), 4
    if dtype in (5, 7):
        return _f32(b, i, rnd), 4
    if dtype in (12, 14) and _need(b, i, 8):
        v = int.from_bytes(b[i:i + 8], "little", signed=sign)
        return v, 8
    if dtype in (13, 15) and _need(b, i, 8):
        return _f64(b, i), 8
    return None


def _adc4(out: dict, name: str, b: bytes, i: int, div: float) -> None:
    out[name] = _i16le(b, i) / div
    out[f"{name}_min"] = _i16le(b, i + 2) / div
    out[f"{name}_max"] = _i16le(b, i + 4) / div
    out[f"{name}_avg"] = _i16le(b, i + 6) / div


def _stats16(out: dict, name: str, b: bytes, i: int, rnd: bool, order=("", "_max", "_min", "_avg")) -> None:
    for k, suffix in enumerate(order):
        out[f"{name}{suffix}"] = _f16(b, i + 2 * k, rnd)


def decode_uc11t1(b: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x03 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x01 and ctype == 0x67 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x02 and ctype == 0x68 and _need(b, i, 1):
            out["humidity"] = b[i] / 2
            i += 1
        else:
            break
    return out


def _uc11_modbus(out: dict, b: bytes, i: int, offset: int) -> int | None:
    if not _need(b, i, 3):
        return None
    chn = b[i] - offset
    dtype = b[i + 1] & 0x07
    res = _modbus_value(b, i + 2, dtype, False, False, raw_bytes=True)
    if res is None or not _need(b, i + 2, res[1]):
        return None
    out[f"modbus_chn_{chn}"] = res[0]
    return i + 2 + res[1]


def decode_uc11xx(b: bytes) -> dict[str, Any]:
    """UC11xx I/O controller (UC1114, UC1122, UC1152 …)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out) if cid == 0xFF and ctype != 0x0E else None
        if n is not None:
            i += n
        elif cid in (0x01, 0x02) and ctype == 0xC8 and _need(b, i, 4):
            out[f"gpio_counter_{cid}"] = _u32le(b, i)
            i += 4
        elif cid in (0x01, 0x02) and _need(b, i, 1):
            out[f"gpio_input_{cid}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid in (0x09, 0x0A) and _need(b, i, 1):
            out[f"gpio_output_{cid - 8}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid in (0x11, 0x12) and _need(b, i, 8):
            _adc4(out, f"adc_{cid - 0x10}", b, i, 100)
            i += 8
        elif cid == 0xFF and ctype == 0x0E:
            nxt = _uc11_modbus(out, b, i, 0)
            if nxt is None:
                break
            i = nxt
        else:
            break
    return out


def decode_uc11n1(b: bytes) -> dict[str, Any]:
    """UC11-N1 I/O controller."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out) if cid == 0xFF and ctype != 0x0E else None
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x04 and ctype == 0xC8 and _need(b, i, 4):
            out["gpio_counter"] = _u32le(b, i)
            i += 4
        elif cid in (0x03, 0x04) and _need(b, i, 1):
            out[f"gpio_{cid - 2}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid in (0x05, 0x06) and _need(b, i, 8):
            _adc4(out, f"adc_{cid - 4}", b, i, 100)
            i += 8
        elif cid == 0xFF and ctype == 0x0E:
            nxt = _uc11_modbus(out, b, i, 6)
            if nxt is None:
                break
            i = nxt
        else:
            break
    return out


def _modbus_19(out: dict, b: bytes, i: int, rnd: bool, **kw: Any) -> int | None:
    """0xFF 0x19: channel id, data length, data type (+sign bit)."""
    if not _need(b, i, 3):
        return None
    chn, ddef = b[i] + 1, b[i + 2]
    res = _modbus_value(b, i + 3, ddef & 0x7F, bool(ddef >> 7), rnd, **kw)
    if res is None or not _need(b, i + 3, res[1]):
        return None
    out[f"modbus_chn_{chn}"] = res[0]
    return i + 3 + res[1]


def decode_uc300(b: bytes) -> dict[str, Any]:
    """UC300 IoT controller: 4 DI, 2 DO, 2 PT100, 2 AI (mA), 2 AV (V), Modbus."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out) if cid == 0xFF and ctype not in (0x19, 0x15) else None
        if n is not None:
            i += n
        elif 0x03 <= cid <= 0x06 and ctype == 0x00 and _need(b, i, 1):
            out[f"gpio_input_{cid - 2}"] = 1 if b[i] == 1 else 0
            i += 1
        elif 0x03 <= cid <= 0x06 and ctype == 0xC8 and _need(b, i, 4):
            out[f"gpio_counter_{cid - 2}"] = _u32le(b, i)
            i += 4
        elif cid in (0x07, 0x08) and ctype == 0x01 and _need(b, i, 1):
            out[f"gpio_output_{cid - 6}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid in (0x09, 0x0A) and ctype == 0x67 and _need(b, i, 2):
            out[f"pt100_{cid - 8}"] = _i16le(b, i) / 10
            i += 2
        elif cid in (0x0B, 0x0C) and ctype == 0x02 and _need(b, i, 4):
            out[f"adc_{cid - 0x0A}"] = _u32le(b, i) / 100
            i += 4
        elif cid in (0x0D, 0x0E) and ctype == 0x02 and _need(b, i, 4):
            out[f"adv_{cid - 0x0C}"] = _u32le(b, i) / 100
            i += 4
        elif cid in (0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E) and ctype == 0xE2 and _need(b, i, 8):
            name = {0x09: "pt100_1", 0x0A: "pt100_2", 0x0B: "adc_1", 0x0C: "adc_2", 0x0D: "adv_1", 0x0E: "adv_2"}[cid]
            _stats16(out, name, b, i, True)
            i += 8
        elif cid == 0xFF and ctype == 0x19:
            nxt = _modbus_19(out, b, i, True, hi_word=True)
            if nxt is None:
                break
            i = nxt
        elif cid == 0xFF and ctype == 0x15 and _need(b, i, 1):
            out[f"modbus_chn_{b[i] + 1}_alarm"] = "read error"
            i += 1
        else:
            break
    return out


def decode_uc50x(b: bytes) -> dict[str, Any]:
    """UC501 / UC502 multi-interface controller: GPIO, analog inputs, SDI-12, Modbus."""
    out: dict[str, Any] = {}
    alarm_map = {1: "threshold alarm", 2: "value change alarm"}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out) if cid == 0xFF and ctype not in (0x0E, 0x14, 0x15) else None
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid in (0x03, 0x04) and ctype == 0x00 and _need(b, i, 1):
            out[f"gpio_input_{cid - 2}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid in (0x03, 0x04) and ctype == 0x01 and _need(b, i, 1):
            out[f"gpio_output_{cid - 2}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid in (0x03, 0x04) and ctype == 0xC8 and _need(b, i, 4):
            out[f"gpio_counter_{cid - 2}"] = _u32le(b, i)
            i += 4
        elif cid == 0xFF and ctype == 0x14 and _need(b, i, 1):
            out[f"analog_input_{b[i] >> 4}_type"] = {0: "current", 1: "voltage"}.get(b[i] & 0x0F, "unknown")
            i += 1
        elif cid in (0x05, 0x06) and ctype == 0x02 and _need(b, i, 8):
            _adc4(out, f"analog_input_{cid - 4}", b, i, 1000)
            i += 8
        elif cid in (0x05, 0x06, 0x85, 0x86) and ctype == 0xE2 and _need(b, i, 8):
            name = f"analog_input_{(cid & 0x0F) - 4}"
            _stats16(out, name, b, i, False, order=("", "_min", "_max", "_avg"))
            i += 8
            if cid & 0x80:
                if not _need(b, i, 1):
                    break
                out[f"{name}_alarm"] = alarm_map.get(b[i], "unknown")
                i += 1
        elif cid == 0x08 and ctype == 0xDB and _need(b, i, 37):
            raw = b[i + 1:i + 37].split(b"\x00", 1)[0]
            out[f"sdi12_{b[i] + 1}"] = raw.decode("latin-1")
            i += 37
        elif cid in (0xFF, 0x80) and ctype == 0x0E and _need(b, i, 3):
            chn = f"modbus_chn_{b[i] - 6}"
            dtype = b[i + 1] & 0x07
            res = _modbus_value(b, i + 2, dtype, False, False, bool_types=(0, 1))
            if res is None or not _need(b, i + 2, res[1]):
                break
            out[chn] = res[0]
            i += 2 + res[1]
            if cid == 0x80:
                if not _need(b, i, 1):
                    break
                out[f"{chn}_alarm"] = alarm_map.get(b[i], "unknown")
                i += 1
        elif cid == 0xFF and ctype == 0x15 and _need(b, i, 1):
            out[f"modbus_chn_{b[i] - 6}_alarm"] = "read error"
            i += 1
        else:
            break
    return out


def _pressure_alarm(out: dict, name: str, b: bytes, i: int, release_text: str, alarm_text: str,
                    overwrite: bool = False) -> None:
    # UC521 reports the alarm pressure as the current value; UC511/512 keep the regular reading
    if overwrite:
        out[name] = _u16le(b, i + 6)
    else:
        out.setdefault(name, _u16le(b, i + 6))
    code = b[i + 8]
    out[f"{name}_alarm_status"] = {0: release_text, 1: alarm_text}.get(code, "unknown")
    if code in (0, 1):
        out[f"{name}_alarm_active"] = code == 1


def decode_uc51x(b: bytes) -> dict[str, Any]:
    """UC511 / UC512 solenoid valve controller."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid in (0x03, 0x05) and ctype == 0x01 and _need(b, i, 1):
            v = 1 if cid == 0x03 else 2
            if b[i] == 0xFF:
                out[f"valve_{v}_result"] = "failed"
            else:
                out[f"valve_{v}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid in (0x04, 0x06) and ctype == 0xC8 and _need(b, i, 4):
            out[f"valve_{cid // 2 - 1}_pulse"] = _u32le(b, i)
            i += 4
        elif cid in (0x07, 0x08) and ctype == 0x01 and _need(b, i, 1):
            out[f"gpio_{cid - 6}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid == 0x09 and ctype == 0x7B and _need(b, i, 2):
            out["pressure"] = _u16le(b, i)
            i += 2
        elif cid == 0xB9 and ctype == 0x7B and _need(b, i, 1):
            out["pressure_sensor_status"] = {1: "sensor error"}.get(b[i], "unknown")
            i += 1
        elif cid == 0x0B and ctype == 0xF5 and _need(b, i, 9):
            _pressure_alarm(out, "pressure", b, i, "release alarm", "trigger alarm")
            i += 9
        elif cid in (0x0E, 0x0F) and ctype == 0xAF and _need(b, i, 3):
            i += 3                       # valve task status (hardware v4+) – not used
        else:
            break
    return out


def decode_uc521(b: bytes) -> dict[str, Any]:
    """UC521 motorised ball-valve controller."""
    out: dict[str, Any] = {}
    vtype = {0: "2_way_ball_valve", 1: "3_way_ball_valve"}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out) if cid == 0xFF and ctype != 0x2A else None
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid in (0x03, 0x05) and ctype == 0xF6 and _need(b, i, 2):
            v = 1 if cid == 0x03 else 2
            t, opening = b[i], b[i + 1]
            if t in (0, 1):
                out[f"valve_{v}_type"] = vtype[t]
                if t == 1 and opening > 100:
                    out[f"valve_{v}_opening"] = opening - 100
                    out[f"valve_{v}_direction"] = "right"
                else:
                    out[f"valve_{v}_opening"] = opening
                    if t == 1:
                        out[f"valve_{v}_direction"] = "left"
            i += 2
        elif cid in (0x04, 0x06) and ctype == 0xC8 and _need(b, i, 4):
            out[f"valve_{cid // 2 - 1}_pulse"] = _u32le(b, i)
            i += 4
        elif cid in (0x07, 0x08) and ctype == 0x01 and _need(b, i, 1):
            out[f"gpio_{cid - 6}"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid in (0x09, 0x0A) and ctype == 0x7B and _need(b, i, 2):
            out[f"pressure_{cid - 8}"] = _u16le(b, i)
            i += 2
        elif cid in (0x0B, 0x0C) and ctype == 0xF5 and _need(b, i, 9):
            _pressure_alarm(out, f"pressure_{cid - 0x0A}", b, i,
                            "pipe pressure threshold alarm release", "pipe pressure threshold alarm", overwrite=True)
            i += 9
        elif cid == 0x0D and ctype == 0xE3 and _need(b, i, 4):
            i += 4                       # valve calibration event – not used
        elif cid in (0xB3, 0xB5) and ctype == 0xF6 and _need(b, i, 2):
            v = 1 if cid == 0xB3 else 2
            out[f"valve_{v}_type"] = vtype.get(b[i], "unknown")
            out[f"valve_{v}_sensor_status"] = b[i + 1]
            i += 2
        elif cid in (0xB9, 0xBA) and ctype == 0x7B and _need(b, i, 1):
            out[f"pressure_{cid - 0xB8}_sensor_status"] = b[i]
            i += 1
        elif cid in (0x0E, 0x0F) and ctype == 0x01 and _need(b, i, 1):
            out[f"valve_{cid - 0x0D}_opening_duration"] = b[i]
            i += 1
        else:
            break
    return out


_UC100_ALARM = {0: "normal", 1: "threshold alarm", 2: "threshold release alarm", 3: "mutation alarm"}      # firmware v1
_UC100_V2_ALARM = {0: "normal", 1: "threshold alarm", 2: "threshold alarm release", 3: "mutation alarm"}   # firmware v2


def decode_uc100(b: bytes) -> dict[str, Any]:
    """UC100 Modbus RTU → LoRaWAN converter (firmware v1)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out) if cid == 0xFF and ctype not in (0x19, 0x15, 0xEE) else None
        if n is not None:
            i += n
        elif cid == 0xFF and ctype == 0x19:
            nxt = _modbus_19(out, b, i, True, bool_types=(0, 1))
            if nxt is None:
                break
            i = nxt
        elif cid == 0xFF and ctype == 0x15 and _need(b, i, 1):
            out[f"modbus_chn_{b[i] + 1}_alarm"] = "read error"
            i += 1
        elif cid == 0xFF and ctype == 0xEE and _need(b, i, 3):
            chn = f"modbus_chn_{(b[i] & 0x3F) + 1}"
            out[f"{chn}_alarm"] = _UC100_ALARM.get(b[i] >> 6, "unknown")
            ddef = b[i + 2]
            res = _modbus_value(b, i + 3, ddef & 0x7F, bool(ddef >> 7), True, bool_types=(0, 1))
            if res is None or not _need(b, i + 3, res[1]):
                break
            out[chn] = res[0]
            i += 3 + res[1]
        elif cid == 0xF9 and ctype == 0x5F and _need(b, i, 7):
            chn = f"modbus_chn_{(b[i] & 0x3F) + 1}"
            if b[i] >> 6 == 3:
                out[f"{chn}_alarm"] = _UC100_ALARM[3]
                out[f"{chn}_mutation"] = _f32(b, i + 3, True)
            i += 7
        else:
            break
    return out


def decode_uc100_v2(b: bytes) -> dict[str, Any]:
    """UC100 Modbus RTU → LoRaWAN converter (firmware v2, register offsets, 64-bit values)."""
    out: dict[str, Any] = {}

    def name(chn_byte_low6: int, offset: int) -> str:
        n = chn_byte_low6 + 1
        return f"modbus_chn_{n}" if offset == 0 else f"modbus_chn_{n}_reg_{offset + 1}"

    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out) if cid == 0xFF and ctype != 0x15 else None
        if n is not None:
            i += n
        elif cid == 0xF9 and ctype == 0x73 and _need(b, i, 2):
            v1, v2 = b[i], b[i + 1]
            chn = name(v1 & 0x3F, (v2 >> 5) & 0x03)
            res = _modbus_value(b, i + 2, v2 & 0x1F, bool(v2 >> 7), True, bool_types=(0, 1))
            if res is None or not _need(b, i + 2, res[1]):
                break
            out[chn] = res[0]
            alarm = (v1 >> 6) & 0x03
            if alarm:
                out[f"{chn}_alarm"] = _UC100_V2_ALARM.get(alarm, "unknown")
            i += 2 + res[1]
        elif cid == 0xFF and ctype == 0x15 and _need(b, i, 1):
            out[f"modbus_chn_{b[i] + 1}_alarm"] = "read error"
            i += 1
        elif cid == 0xF9 and ctype == 0x74 and _need(b, i, 9):
            chn = name(b[i] & 0x3F, (b[i] >> 6) & 0x03)
            out[f"{chn}_mutation"] = _f64(b, i + 1)
            i += 9
        else:
            break
    return out


# --------------------------------------------------------------------------
# EM400 range – ultrasonic distance / level (EM400-UDL, EM400-TLD, EM400-MUD share one format)
# Checked against Milesight-IoT/SensorDecoders (em-series/em400-*).
# --------------------------------------------------------------------------
_EM400_ALARM = {0: ("threshold_alarm_release", False), 1: ("threshold_alarm", True)}


def decode_em400(b: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid in (0x03, 0x83) and ctype == 0x67 and _need(b, i, 2 if cid == 0x03 else 3):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
            if cid == 0x83:
                _ts_alarm(out, "temperature", b[i], _EM400_ALARM)
                i += 1
        elif cid in (0x04, 0x84) and ctype == 0x82 and _need(b, i, 2 if cid == 0x04 else 3):
            out["distance"] = _u16le(b, i)
            i += 2
            if cid == 0x84:
                _ts_alarm(out, "distance", b[i], _EM400_ALARM)
                i += 1
        elif cid == 0x05 and ctype == 0x00 and _need(b, i, 1):
            out["position"] = {0: "normal", 1: "tilt"}.get(b[i], "unknown")
            out["tilted"] = b[i] == 1
            i += 1
        else:
            break
    return out


# --------------------------------------------------------------------------
# CT range – smart current transformers
#   CT101 / CT103 / CT105: one channel   (current 0x04 0x98, uint16 / 100 A)
#   CT303 / CT305 / CT310: three channels (current 0x04/06/08 0x99, uint16 / 10 A)
# Firmware v2 adds energy (0x10-0x12 0x63, kWh) and a low-voltage event (0x13 0x75); the
# v2 format is a superset of v1, so one decoder serves both.
# Checked against Milesight-IoT/SensorDecoders (ct-series).
# --------------------------------------------------------------------------
_CT_ALARM_BITS = ("threshold_alarm", "threshold_alarm_release", "over_range_alarm", "over_range_alarm_release")
_CT_TEMP_ALARM = {0: ("threshold_alarm_release", False), 1: ("threshold_alarm", True)}


def _ct_alarm(out: dict, name: str, code: int) -> None:
    flags = [n for bit, n in enumerate(_CT_ALARM_BITS) if code >> bit & 1]
    if not flags:
        return
    out[f"{name}_alarm_status"] = ", ".join(flags)
    if code & 0b0101:
        out[f"{name}_alarm_active"] = True
    elif code & 0b1010:
        out[f"{name}_alarm_active"] = False


def _ct_temperature(out: dict, b: bytes, i: int) -> None:
    raw = _u16le(b, i)
    if raw in (0xFFFD, 0xFFFF):
        out["sensor_error"] = "Temperature: " + ("over range" if raw == 0xFFFD else "read failed")
    else:
        out["temperature"] = _i16le(b, i) / 10


def _decode_ct(b: bytes, channels: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    single = channels == 1
    ctype_i = 0x98 if single else 0x99
    div = 100 if single else 10

    def name(base: str, ch: int) -> str:
        return base if single else f"{base}_{ch}"

    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        ch_total = (cid - 0x01) // 2 if cid in (0x03, 0x05, 0x07)[:channels] else None
        ch_now = (cid - 0x02) // 2 if cid in (0x04, 0x06, 0x08)[:channels] else None
        ch_alarm = (cid - 0x82) // 2 if cid in (0x84, 0x86, 0x88)[:channels] else None
        if n is not None:
            i += n
        elif ch_total is not None and ctype == 0x97 and _need(b, i, 4):
            out[name("total_current", ch_total)] = _u32le(b, i) / 100
            i += 4
        elif ch_now is not None and ctype == ctype_i and _need(b, i, 2):
            raw = _u16le(b, i)
            if raw == 0xFFFF:
                out["sensor_error"] = f"{name('current', ch_now).replace('_', ' ').capitalize()}: read failed"
            else:
                out[name("current", ch_now)] = raw / div
            i += 2
        elif ch_alarm is not None and ctype == ctype_i and _need(b, i, 7):
            key = name("current", ch_alarm)
            out[f"{key}_max"] = _u16le(b, i) / div
            out[f"{key}_min"] = _u16le(b, i + 2) / div
            out[key] = _u16le(b, i + 4) / div
            _ct_alarm(out, key, b[i + 6])
            i += 7
        elif cid == 0x09 and ctype == 0x67 and _need(b, i, 2):
            _ct_temperature(out, b, i)
            i += 2
        elif cid == 0x89 and ctype == 0x67 and _need(b, i, 3):
            out["temperature"] = _i16le(b, i) / 10
            _ts_alarm(out, "temperature", b[i + 2], _CT_TEMP_ALARM)
            i += 3
        elif 0x10 <= cid < 0x10 + channels and ctype == 0x63 and _need(b, i, 4):
            out[name("energy", cid - 0x0F)] = _u32le(b, i) / 100
            i += 4
        elif cid == 0x13 and ctype == 0x75 and _need(b, i, 1):
            out["low_voltage_alarm"] = b[i] == 1
            i += 1
        else:
            break
    if "sensor_error" not in out and any(k.startswith("current") for k in out):
        out["sensor_error"] = "OK"
    return out


def decode_ct10x(b: bytes) -> dict[str, Any]:
    return _decode_ct(b, 1)


def decode_ct30x(b: bytes) -> dict[str, Any]:
    return _decode_ct(b, 3)


# --------------------------------------------------------------------------
# GS range – gas, odour, smoke and vape detectors
# Checked against Milesight-IoT/SensorDecoders (gs-series).
# --------------------------------------------------------------------------
_GS101_EVENT = {0: "power_off", 1: "power_on", 2: "device_fault", 3: "device_fault_recovered",
                4: "device_will_be_invalid_soon", 5: "device_invalid"}


def decode_gs101(b: bytes) -> dict[str, Any]:
    """GS101 gas detector (with valve / relay output)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x05 and ctype == 0x8E and _need(b, i, 1):
            out["gas_alarm"] = b[i] == 1
            i += 1
        elif cid == 0x06 and ctype == 0x01 and _need(b, i, 1):
            out["valve_status"] = b[i] == 1
            i += 1
        elif cid == 0x07 and ctype == 0x01 and _need(b, i, 1):
            out["relay_output_status"] = b[i] == 1
            i += 1
        elif cid == 0x08 and ctype == 0x90 and _need(b, i, 4):
            out["life_remain"] = _u32le(b, i)
            i += 4
        elif cid == 0xFF and ctype == 0x3F and _need(b, i, 1):
            event = _GS101_EVENT.get(b[i], "unknown")
            out["device_alarm"] = event
            if b[i] in (2, 3, 5):
                out["device_fault"] = b[i] in (2, 5)
            if b[i] in (4, 5):
                out["end_of_life"] = True
            i += 1
        else:
            break
    return out


_GS301_STATUS = {0xFFFE: "polarizing", 0xFFFF: "device error"}


def decode_gs301(b: bytes) -> dict[str, Any]:
    """GS301 bathroom odour detector (NH3 / H2S, temperature, humidity)."""
    out: dict[str, Any] = {}
    errors: list[str] = []
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x02 and ctype == 0x67 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x03 and ctype == 0x68 and _need(b, i, 1):
            out["humidity"] = b[i] / 2
            i += 1
        elif cid in (0x04, 0x05, 0x06) and ctype == 0x7D and _need(b, i, 2):
            raw = _u16le(b, i)
            key = "nh3" if cid == 0x04 else "h2s"
            if raw in _GS301_STATUS:
                errors.append(f"{key.upper()}: {_GS301_STATUS[raw]}")
            else:
                out[key] = raw / (1000 if cid == 0x06 else 100)     # 0x06 = H2S high resolution (fw 1.2+)
            i += 2
        elif cid == 0x07 and ctype == 0xEA and _need(b, i, 5):    # sensor calibration result
            i += 5
        elif cid == 0xFF and ctype == 0x7C and _need(b, i, 43):   # sensor id
            i += 43
        else:
            break
    if errors:
        out["sensor_error"] = ", ".join(errors)
    elif "nh3" in out or "h2s" in out:
        out["sensor_error"] = "OK"
    return out


_GS524N_EVENT = {0x01: "alarm", 0x02: "silent", 0x04: "low_battery", 0x05: "failover", 0x07: "normal",
                 0x0A: "removed", 0x0B: "installed", 0x0E: "testing_alarm_with_normal_battery",
                 0x0F: "testing_alarm_with_low_battery"}


def decode_gs524n(b: bytes) -> dict[str, Any]:
    """GS524N smoke detector (fixed 6-byte frame)."""
    if len(b) != 6:
        return {}
    code = b[1] & 0x0F
    event = _GS524N_EVENT.get(code, "unknown")
    out: dict[str, Any] = {"event": event, "battery": b[2], "concentration": b[3], "temperature": _i8(b[4])}
    if b[1] >> 4 != 1:
        out["sensor_type"] = "unknown"
    if code in (0x01, 0x02, 0x07):
        out["smoke_alarm"] = code == 0x01
    if code in (0x04, 0x0F, 0x07, 0x0E):
        out["battery_low_alarm"] = code in (0x04, 0x0F)
    if code in (0x0A, 0x0B):
        out["removed"] = code == 0x0A
    if code in (0x05, 0x07):
        out["device_fault"] = code == 0x05
    return out


# GS601 alarm type codes
_GS601_ALARM = {0x00: "collection_error", 0x01: "lower_range_error", 0x02: "over_range_error",
                0x10: "alarm_deactivation", 0x11: "alarm_trigger"}
# command -> (field, value size, signed, divisor, extra alarm codes)
_GS601_FIELDS = {
    0x01: ("vaping_index", 1, False, 1), 0x03: ("pm1_0", 2, False, 1), 0x05: ("pm2_5", 2, False, 1),
    0x07: ("pm10", 2, False, 1), 0x09: ("temperature", 2, True, 10), 0x0B: ("humidity", 2, False, 10),
    0x0D: ("tvoc", 2, False, 1),
}
_GS601_FIXED = {0xC8: 1, 0xC9: 1, 0xD9: 2, 0x20: 8, 0x21: 8, 0x22: 8, 0x23: 8, 0x24: 8, 0x25: 8, 0x26: 8,
                0x27: 8, 0x28: 8, 0x29: 8, 0x2A: 8, 0xFE: 1, 0xEE: 0}


def _gs601_value(b: bytes, i: int, size: int, signed: bool, div: int) -> float | int:
    v = b[i] if size == 1 else (_i16le(b, i) if signed else _u16le(b, i))
    return v / div if div != 1 else v


def decode_gs601(b: bytes) -> dict[str, Any]:
    """GS601 vape detector (command format)."""
    return _parse_gs601(b)[0]


def gs601_parses_completely(b: bytes) -> bool:
    return bool(b) and _parse_gs601(b)[1] == len(b)


def _parse_gs601(b: bytes) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    errors: list[str] = []
    i = 0
    while i < len(b):
        cmd = b[i]
        i += 1
        if cmd == 0x00 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cmd in _GS601_FIELDS and _need(b, i, _GS601_FIELDS[cmd][1]):
            key, size, signed, div = _GS601_FIELDS[cmd]
            out[key] = _gs601_value(b, i, size, signed, div)
            i += size
        elif cmd - 1 in _GS601_FIELDS and _need(b, i, 1):          # <field>_alarm
            key, size, signed, div = _GS601_FIELDS[cmd - 1]
            code = b[i]
            i += 1
            if code in (0x10, 0x11) and key != "humidity":
                if not _need(b, i, size):
                    break
                out[key] = _gs601_value(b, i, size, signed, div)
                i += size
                out[f"{key}_alarm_active"] = code == 0x11
            if code <= 0x02:
                errors.append(f"{key.replace('_', '.') if key.startswith('pm') else key.replace('_', ' ')}: "
                              f"{_GS601_ALARM[code].replace('_', ' ')}")
            if code in (0x20, 0x21):
                flag = "vaping_interference" if key == "vaping_index" else "burning_alarm"
                out[flag] = code == 0x21
                out[f"{key}_alarm_status"] = ("interference_alarm_" if key == "vaping_index" else "burning_alarm_") + \
                    ("trigger" if code == 0x21 else "deactivation")
            else:
                out[f"{key}_alarm_status"] = _GS601_ALARM.get(code, "unknown")
        elif cmd == 0x0F and _need(b, i, 1):
            out["tamper_status"] = b[i] == 1
            i += 1
        elif cmd == 0x10 and _need(b, i, 1):
            if b[i] in (0x20, 0x21):
                out["tamper_status"] = b[i] == 0x21
            i += 1
        elif cmd == 0x11 and _need(b, i, 1):
            out["buzzer"] = b[i] == 1
            i += 1
        elif cmd == 0x12 and _need(b, i, 1):
            out["occupancy"] = b[i]
            i += 1
        elif cmd == 0x2B and _need(b, i, 4):
            out["pm_sensor_working_time"] = _u32le(b, i)
            i += 4
        elif cmd == 0xDF and _need(b, i, 2):
            out["tsl_version"] = f"v{b[i]}.{b[i + 1]}"
            i += 2
        elif cmd == 0xDB and _need(b, i, 8):
            out["sn"] = b[i:i + 8].hex()
            i += 8
        elif cmd == 0xDA and _need(b, i, 8):
            out["hardware_version"] = f"v{b[i]}.{b[i + 1]}"
            out["firmware_version"] = f"v{b[i + 2]}.{b[i + 3]}"
            i += 8
        elif cmd == 0xCF and _need(b, i, 1):
            if b[i] == 0x00 and _need(b, i, 2):
                out["lorawan_class"] = {0: "Class A", 1: "Class B", 2: "Class C", 3: "Class CtoB"}.get(b[i + 1], "unknown")
                i += 1
            i += 1
        elif cmd in _GS601_FIXED and _need(b, i, _GS601_FIXED[cmd]):
            i += _GS601_FIXED[cmd]
        else:
            i -= 1
            break
    if errors:
        out["sensor_error"] = ", ".join(errors)
    elif any(k in out for k in ("vaping_index", "pm2_5", "tvoc")):
        out["sensor_error"] = "OK"
    return out, i


# --------------------------------------------------------------------------
# AT range – AT101 GNSS / Wi-Fi asset tracker
# Checked against Milesight-IoT/SensorDecoders (at-series/at101).
# --------------------------------------------------------------------------
_AT_MOTION = {0: "unknown", 1: "start", 2: "moving", 3: "stop"}
_AT_GEOFENCE = {0: "inside", 1: "outside", 2: "unset", 3: "unknown"}


def decode_at101(b: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x67 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid in (0x04, 0x84) and ctype == 0x88 and _need(b, i, 9):
            out["latitude"] = _i32le(b, i) / 1_000_000
            out["longitude"] = _i32le(b, i + 4) / 1_000_000
            out["motion_status"] = _AT_MOTION.get(b[i + 8] & 0x0F, "unknown")
            out["geofence_status"] = _AT_GEOFENCE.get(b[i + 8] >> 4, "unknown")
            i += 9
        elif cid == 0x05 and ctype == 0x00 and _need(b, i, 1):
            out["position"] = {0: "normal", 1: "tilt"}.get(b[i], "unknown")
            if b[i] in (0, 1):
                out["tilted"] = b[i] == 1
            i += 1
        elif cid == 0x06 and ctype == 0xD9 and _need(b, i, 9):
            mac = b[i + 1:i + 7]
            out["wifi_scan_result"] = "finish"
            if mac == b"\xff" * 6:
                out["wifi_scan_result"] = "timeout"
            else:
                out["motion_status"] = _AT_MOTION.get(b[i + 8] & 0x0F, "unknown")
                out.setdefault("wifi", []).append({
                    "group": b[i], "mac": ":".join(f"{x:02x}" for x in mac), "rssi": _i8(b[i + 7])})
                out["wifi_ap_count"] = len(out["wifi"])
            i += 9
        elif cid == 0x07 and ctype == 0x00 and _need(b, i, 1):
            out["tamper_status"] = {0: "install", 1: "uninstall"}.get(b[i], "unknown")
            if b[i] in (0, 1):
                out["tamper"] = b[i] == 1
            i += 1
        elif cid == 0x83 and ctype == 0x67 and _need(b, i, 3):
            out["temperature"] = _i16le(b, i) / 10
            out["temperature_alarm_status"] = {0: "normal", 1: "abnormal"}.get(b[i + 2], "unknown")
            if b[i + 2] in (0, 1):
                out["temperature_alarm_active"] = b[i + 2] == 1
            i += 3
        elif cid == 0x20 and ctype == 0xCE and _need(b, i, 12):
            out.setdefault("history", []).append({
                "timestamp": _u32le(b, i), "longitude": _i32le(b, i + 4) / 1_000_000,
                "latitude": _i32le(b, i + 8) / 1_000_000})
            i += 12
        else:
            break
    return out


# --------------------------------------------------------------------------
# WS range – buttons, sensors, wall switches, sockets and light controllers
# Checked against Milesight-IoT/SensorDecoders (ws-series).
# Button presses are returned as  out["button_events"] = [(entity_key, event_type), ...]
# --------------------------------------------------------------------------
_WS101_EVENT = {1: "short_press", 2: "long_press", 3: "double_press"}
_WS156_EVENT = {0: "short_press", 1: "double_press", 2: "long_press"}
_WS156_MODE = {0: "short_press", 1: "short_press+double_press", 2: "short_press+long_press",
               3: "short_press+double_press+long_press"}


def _ws_battery(cid: int, ctype: int, b: bytes, i: int, out: dict) -> int | None:
    if cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
        out["battery"] = b[i]
        return 1
    return None


def decode_ws101(b: bytes) -> dict[str, Any]:
    """WS101 smart button."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is None:
            n = _ws_battery(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0xFF and ctype == 0x2E and _need(b, i, 1):
            event = _WS101_EVENT.get(b[i], "unknown")
            out["button_event"] = event
            if event != "unknown":
                out.setdefault("button_events", []).append(("button", event))
            i += 1
        else:
            break
    return out


def _decode_ws_panel(b: bytes, with_mode: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is None:
            n = _ws_battery(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0xFF and ctype == 0x34 and _need(b, i, 3):
            key = f"button_{b[i]}"
            if with_mode:
                event = _WS156_EVENT.get(b[i + 2], "unknown")
                out[f"{key}_mode"] = _WS156_MODE.get(b[i + 1], "unknown")
                out[f"{key}_event"] = event
            else:
                event = "press"
                out[f"{key}_d2d"] = _u16le(b, i + 1)
            if event != "unknown":
                out.setdefault("button_events", []).append((key, event))
            i += 3
        else:
            break
    return out


def decode_ws136(b: bytes) -> dict[str, Any]:
    """WS136 scene panel (press = one event per button)."""
    return _decode_ws_panel(b, with_mode=False)


def decode_ws156(b: bytes) -> dict[str, Any]:
    """WS156 scene panel (short / double / long press)."""
    return _decode_ws_panel(b, with_mode=True)


def _decode_ws_sensor(b: bytes, handlers: dict) -> dict[str, Any]:
    """Channel decoder for the simple WS sensors: handlers[(cid, ctype)] = (size, fn(out, b, i))."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is None:
            n = _ws_battery(cid, ctype, b, i, out)
        h = handlers.get((cid, ctype))
        if n is not None:
            i += n
        elif h and _need(b, i, h[0]):
            h[1](out, b, i)
            i += h[0]
        else:
            break
    return out


def _set(key: str, fn):
    def h(out, b, i):
        out[key] = fn(b, i)
    return h


def decode_ws201(b: bytes) -> dict[str, Any]:
    """WS201 fill level monitor (tissue / soap / paper towels)."""
    return _decode_ws_sensor(b, {(0x03, 0x82): (2, _set("distance", _u16le)),
                                 (0x04, 0xD6): (1, _set("remaining", lambda b, i: b[i]))})


def _ws202_pir(out, b, i):
    if b[i] in (0, 1):
        out["pir"] = b[i] == 1


def _ws202_light(out, b, i):
    out["daylight"] = {0: "dim", 1: "bright"}.get(b[i], "unknown")


def decode_ws202(b: bytes) -> dict[str, Any]:
    """WS202 PIR & light sensor."""
    return _decode_ws_sensor(b, {(0x03, 0x00): (1, _ws202_pir), (0x04, 0x00): (1, _ws202_light)})


_WS_TEMP_ALARM = {0: ("threshold_alarm_release", False), 1: ("threshold_alarm", True),
                  2: ("overheat_alarm", True), 3: ("mutation_alarm", None)}


def _ws203_occ(out, b, i):
    if b[i] in (0, 1):
        out["occupancy"] = b[i]


def _ws_temp_alarm(out, b, i):
    out["temperature"] = _i16le(b, i) / 10
    _ts_alarm(out, "temperature", b[i + 2], _WS_TEMP_ALARM)


def decode_ws203(b: bytes) -> dict[str, Any]:
    """WS203 motion & temperature / humidity sensor."""
    return _decode_ws_sensor(b, {
        (0x03, 0x67): (2, _set("temperature", lambda b, i: _i16le(b, i) / 10)),
        (0x04, 0x68): (1, _set("humidity", lambda b, i: b[i] / 2)),
        (0x05, 0x00): (1, _ws203_occ),
        (0x83, 0x67): (3, _ws_temp_alarm),
        (0x20, 0xCE): (9, lambda out, b, i: None),          # history record
    })


def _ws301_magnet(out, b, i):
    if b[i] in (0, 1):
        out["magnet_status"] = b[i]


def _ws301_tamper(out, b, i):
    if b[i] in (0, 1):
        out["tamper"] = b[i] == 1


def decode_ws301(b: bytes) -> dict[str, Any]:
    """WS301 magnetic contact switch."""
    return _decode_ws_sensor(b, {(0x03, 0x00): (1, _ws301_magnet), (0x04, 0x00): (1, _ws301_tamper)})


def _ws302_sound(out, b, i):
    w = b[i]
    out["sound_weighting"] = "L" + {0: "Z", 1: "A", 2: "C"}.get(w & 0x03, "?") + {0: "I", 1: "F", 2: "S"}.get(w >> 2 & 0x03, "?")
    out["sound_level"] = _u16le(b, i + 1) / 10
    out["sound_level_eq"] = _u16le(b, i + 3) / 10
    out["sound_level_max"] = _u16le(b, i + 5) / 10


def decode_ws302(b: bytes) -> dict[str, Any]:
    """WS302 sound level sensor."""
    return _decode_ws_sensor(b, {(0x05, 0x5B): (7, _ws302_sound)})


def _ws303_leak(out, b, i):
    if b[i] in (0, 1):
        out["leak"] = b[i]


def decode_ws303(b: bytes) -> dict[str, Any]:
    """WS303 mini leak detection sensor."""
    return _decode_ws_sensor(b, {(0x03, 0x00): (1, _ws303_leak)})


# ---- wall switches / sockets / light controller -----------------------------------
def _ws_bits(out: dict, value: int, gangs: int, prefix: str = "switch") -> None:
    for n in range(gangs):
        out[f"{prefix}_{n + 1}"] = bool(value >> n & 1)


def _decode_ws_power(b: bytes, *, gangs: int = 1, v_div: float = 10, wh_div: float = 1000,
                     ma_div: float = 1000, seen: set | None = None) -> dict[str, Any]:
    """Switches (ff29 / 0829 state), sockets (0870), WS558 (0831) and their metering / alarm channels.
    ``seen`` collects the (channel id, type) pairs that were parsed (used for model detection)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid in (0xFF, 0x08) and ctype == 0x29 and _need(b, i, 1):
            _ws_bits(out, b[i], gangs)
            i += 1
        elif cid == 0xFF and ctype == 0x2B and _need(b, i, 1):
            out["function_key_event"] = True
            i += 1
        elif cid == 0x08 and ctype == 0x70 and _need(b, i, 1):
            out["switch_1"] = bool(b[i] & 1)
            i += 1
        elif cid == 0x08 and ctype == 0x31 and _need(b, i, 2):
            _ws_bits(out, b[i + 1], 8)
            i += 2
        elif cid == 0x03 and ctype == 0x74 and _need(b, i, 2):
            out["voltage"] = _u16le(b, i) / v_div
            i += 2
        elif cid == 0x04 and ctype == 0x80 and _need(b, i, 4):
            out["power"] = _u32le(b, i)
            i += 4
        elif cid == 0x05 and ctype == 0x81 and _need(b, i, 1):
            out["power_factor"] = b[i]
            i += 1
        elif cid == 0x06 and ctype == 0x83 and _need(b, i, 4):
            out["energy"] = _u32le(b, i) / wh_div
            i += 4
        elif cid == 0x07 and ctype == 0xC9 and _need(b, i, 2):
            out["current"] = _u16le(b, i) / ma_div
            i += 2
        elif cid == 0x09 and ctype == 0x67 and _need(b, i, 2):
            raw = _u16le(b, i)
            if raw in (0xFFFD, 0xFFFF):
                out["sensor_error"] = "Temperature: " + ("over range" if raw == 0xFFFD else "read failed")
            else:
                out["temperature"] = _i16le(b, i) / 10
                out["sensor_error"] = "OK"
            i += 2
        elif cid == 0x89 and ctype == 0x67 and _need(b, i, 3):
            _ws_temp_alarm(out, b, i)
            i += 3
        elif cid == 0x99 and ctype == 0x67 and _need(b, i, 5):
            out["temperature"] = _i16le(b, i) / 10
            out["temperature_mutation"] = _i16le(b, i + 2) / 10
            _ts_alarm(out, "temperature", 3, _WS_TEMP_ALARM)
            i += 5
        elif cid == 0x87 and ctype == 0xC9 and _need(b, i, 3):
            out["current"] = _u16le(b, i) / ma_div
            out["overcurrent_alarm"] = b[i + 2] == 1
            i += 3
        elif cid == 0x88 and ctype == 0x29 and _need(b, i, 1):
            out["device_fault"] = b[i] == 1
            i += 1
        elif cid == 0x89 and ctype == 0xDF and _need(b, i, 1):
            out["overtemperature_alarm"] = b[i] == 1
            i += 1
        elif 0xB3 <= cid <= 0xB7 and ctype in (0x74, 0x80, 0x81, 0x83, 0xC9) and _need(b, i, 1):
            name = {0xB3: "Voltage", 0xB4: "Power", 0xB5: "Power factor", 0xB6: "Energy", 0xB7: "Current"}[cid]
            out["sensor_error"] = f"{name}: collection error"
            i += 1
        elif cid == 0xFF and ctype == 0x26 and _need(b, i, 1):
            out["power_consumption_enable"] = b[i] == 1
            i += 1
        else:
            break
        if seen is not None:
            seen.add((cid, ctype))
    return out


def ws_power_channels(b: bytes) -> set[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    _decode_ws_power(b, gangs=8, seen=seen)
    return seen


def decode_ws50x(b: bytes, gangs: int = 1) -> dict[str, Any]:
    """WS501 / WS502 / WS503 (firmware v1-v3 and EU / US / CN variants; switch state + metering)."""
    return _decode_ws_power(b, gangs=gangs)


def decode_ws50x_v4(b: bytes, gangs: int = 1) -> dict[str, Any]:
    """WS501 / WS502 / WS503 firmware v4 (voltage in V, energy in Wh)."""
    return _decode_ws_power(b, gangs=gangs, v_div=1)


def decode_ws501(b): return decode_ws50x(b, 1)
def decode_ws502(b): return decode_ws50x(b, 2)
def decode_ws503(b): return decode_ws50x(b, 3)
def decode_ws501_v4(b): return decode_ws50x_v4(b, 1)
def decode_ws502_v4(b): return decode_ws50x_v4(b, 2)
def decode_ws503_v4(b): return decode_ws50x_v4(b, 3)


def decode_ws52x(b: bytes) -> dict[str, Any]:
    """WS513 / WS515 / WS523 / WS525 smart sockets (switch_1 = socket)."""
    return _decode_ws_power(b)


def decode_ws52x_v3(b: bytes) -> dict[str, Any]:
    """WS513 / WS515 firmware v3 (energy reported in 1/100000 kWh units)."""
    return _decode_ws_power(b, v_div=1, wh_div=100000)   # current already in 1/1000 A as on v1


def decode_ws558(b: bytes) -> dict[str, Any]:
    """WS558 8-channel smart light controller."""
    return _decode_ws_power(b, gangs=8)


# Downlinks (fPort 85) – verified against Milesight's official encoders
def encode_ws_switch(kind: str, channel: int, on: bool) -> bytes:
    bit = 1 << (channel - 1)
    if kind == "ff29":                   # WS50x v1-v4, WS513/515 v3
        return bytes([0xFF, 0x29, bit << 4 | (bit if on else 0)])
    if kind == "0829":                   # WS50x EU / US / CN
        return bytes([0x08, bit << 4 | (bit if on else 0), 0xFF])
    if kind == "0870":                   # WS513 / WS515 / WS523 / WS525
        return bytes([0x08, 1 if on else 0, 0xFF, 0xFF])
    if kind == "0831":                   # WS558
        return bytes([0x08, bit, bit if on else 0])
    raise ValueError(kind)


# --------------------------------------------------------------------------
# WT range – thermostats and radiator valves
# Checked against Milesight-IoT/SensorDecoders (wt-series).
# --------------------------------------------------------------------------
_WT101_CAL = {0: "success", 1: "fail: out of range", 2: "fail: uninstalled", 3: "calibration cleared",
              4: "temperature control disabled"}


def decode_wt101(b: bytes) -> dict[str, Any]:
    """WT101 smart radiator thermostat (channel format)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is None:
            n = _ws_battery(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid in (0x03, 0x04) and ctype == 0x67 and _need(b, i, 2):
            out["temperature" if cid == 0x03 else "target_temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x05 and ctype == 0x92 and _need(b, i, 1):
            out["valve_opening"] = b[i]
            i += 1
        elif cid == 0x06 and ctype == 0x00 and _need(b, i, 1):
            if b[i] in (0, 1):
                out["tamper"] = b[i] == 1
            i += 1
        elif cid == 0x07 and ctype == 0x00 and _need(b, i, 1):
            if b[i] in (0, 1):
                out["window_open"] = b[i] == 1
            i += 1
        elif cid == 0x08 and ctype == 0xE5 and _need(b, i, 1):
            out["motor_calibration_result"] = _WT101_CAL.get(b[i], "unknown")
            i += 1
        elif cid in (0x09, 0x0B) and ctype == 0x90 and _need(b, i, 2):
            out["motor_stroke" if cid == 0x09 else "motor_position"] = _u16le(b, i)
            i += 2
        elif cid == 0x0A and ctype == 0x00 and _need(b, i, 1):
            if b[i] in (0, 1):
                out["freeze_protection"] = b[i] == 1
            i += 1
        elif cid == 0xF9 and ctype in (0x33, 0x34) and _need(b, i, 7 if ctype == 0x33 else 9):
            i += 7 if ctype == 0x33 else 9             # heating date / schedule
        else:
            break
    return out


# ---- WT201 (v1) / WT201 v2 / WT211 -------------------------------------------
_WT201_STATUS = {0: "standby", 1: "stage-1 heat", 2: "stage-2 heat", 3: "stage-3 heat", 4: "stage-4 heat",
                 5: "em heat", 6: "stage-1 cool", 7: "stage-2 cool", 8: "stage-5 heat", 9: "stage-3 cool"}
_WT201_FAN = {0: "auto", 1: "on", 2: "circulate", 3: "disable"}
_WT201_FAN_STATUS = {0: "standby", 1: "high speed", 2: "low speed", 3: "on"}
_WT201_PLAN = {0: "not executed", 1: "wake", 2: "away", 3: "home", 4: "sleep", 5: "occupied", 6: "vacant", 7: "eco"}
_WT201_ALARM = {1: ("emergency_heating_timeout_alarm", None), 2: ("auxiliary_heating_timeout_alarm", None),
                3: ("persistent_low_temperature_alarm", True), 4: ("persistent_low_temperature_alarm_release", False),
                5: ("persistent_high_temperature_alarm", True), 6: ("persistent_high_temperature_alarm_release", False),
                7: ("freeze_protection_alarm", True), 8: ("freeze_protection_alarm_release", False),
                9: ("threshold_alarm", True), 10: ("threshold_alarm_release", False)}
_WT201_RELAYS = ("Y1", "Y2", "W1", "W2", "EH", "G", "OB")


def _decode_wt201(b: bytes, v2: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    modes = ("heat", "em heat", "cool", "auto")
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid in (0x03, 0x04, 0x0B) and ctype == 0x67 and _need(b, i, 2) and (v2 or cid != 0x0B):
            key = {0x03: "temperature", 0x04: "target_temperature", 0x0B: "target_temperature_2"}[cid]
            out[key] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x05 and ctype == 0xE7 and _need(b, i, 1):
            out["temperature_control_mode"] = modes[b[i] & 0x03]
            out["temperature_control_status"] = _WT201_STATUS.get(b[i] >> 4 & 0x0F, "unknown") \
                if v2 or (b[i] >> 4) <= 7 else "unknown"
            i += 1
        elif cid == 0x06 and ctype == 0xE8 and _need(b, i, 1):
            if v2:
                out["fan_mode"] = ("auto", "on", "circulate", "disable")[b[i] & 0x03]
                st = b[i] >> 2 & 0x07
                if st > 3:                       # the official v2 decoder fails on these values
                    break
                out["fan_status"] = ("standby", "high speed", "low speed", "on")[st]
            else:
                out["fan_mode"] = _WT201_FAN[b[i] & 0x03]
                out["fan_status"] = _WT201_FAN_STATUS[b[i] >> 2 & 0x03]
            i += 1
        elif cid == 0x07 and ctype == 0xBC and _need(b, i, 1):
            code = b[i] & 0x0F
            out["plan_type"] = _WT201_PLAN.get(code, "unknown") if v2 or code <= 4 else "unknown"
            i += 1
        elif v2 and cid == 0x07 and ctype == 0xE9 and _need(b, i, 1):
            out["temperature_source"] = {1: "embedded", 2: "lora", 3: "d2d"}.get(b[i], "unknown")
            i += 1
        elif v2 and cid == 0x87 and ctype == 0xE9 and _need(b, i, 2):
            out["source_switch_alarm"] = b[i + 1] == 1
            i += 2
        elif cid == 0x08 and ctype == 0x8E and _need(b, i, 1):
            out["system_status"] = b[i] == 1
            i += 1
        elif cid == 0x09 and ctype == 0x68 and _need(b, i, 1):
            out["humidity"] = b[i] / 2
            i += 1
        elif cid == 0x0A and ctype == 0x6E and _need(b, i, 1):
            on = [r for n_, r in enumerate(_WT201_RELAYS) if b[i] >> n_ & 1]
            out["relay"] = "&".join(on) if on else "off"
            i += 1
        elif cid == 0xFF and ctype == 0xCB and _need(b, i, 3):
            out["supported_modes"] = ", ".join(m for n_, m in enumerate(("heat", "em heat", "cool", "auto"))
                                               if b[i] >> n_ & 1) or "none"
            i += 3
        elif cid == 0x83 and ctype == 0x67 and _need(b, i, 3 if v2 else 2):
            out["temperature"] = _i16le(b, i) / 10
            if _need(b, i, 3):
                _ts_alarm(out, "temperature", b[i + 2], _WT201_ALARM)
            i += 3 if v2 else 2                  # v1 firmware decoder skips only 2 bytes (kept for compatibility)
        elif cid in (0xB3, 0xB9) and ctype in (0x67, 0x68) and _need(b, i, 1):
            name = "Temperature" if cid == 0xB3 else "Humidity"
            out["sensor_error"] = f"{name}: " + {1: "read failed", 2: "out of range"}.get(b[i], "unknown")
            i += 1
        elif v2 and cid == 0xF9 and ctype == 0x40 and _need(b, i, 7):
            out["target_temperature_range_alarm"] = True
            i += 7
        elif cid == 0x20 and ctype == 0xCE and _need(b, i, 13 if v2 else 8):
            i += 13 if v2 else 8                 # history record
        else:
            break
    return out


def decode_wt201(b: bytes) -> dict[str, Any]:
    """WT201 smart thermostat (firmware v1)."""
    return _decode_wt201(b, v2=False)


def decode_wt201_v2(b: bytes) -> dict[str, Any]:
    """WT201 v2 / WT211 smart thermostat."""
    return _decode_wt201(b, v2=True)


# ---- WT301 / WT302 fan-coil thermostats (frame: 55 cmd len(2, BE) type data... crc) ------------
_WT30X_MODE = {0: "cool", 1: "heat", 2: "fan"}
_WT30X_FAN = {0: "auto", 1: "high", 2: "medium", 3: "low"}


def decode_wt30x(b: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if len(b) < 6 or b[0] != 0x55:
        return out
    data_id, d = b[4], b[5:]

    def field(fid: int, v: int) -> None:
        if fid == 0x01:
            out["system_status"] = v == 1
        elif fid == 0x02:
            out["button_lock"] = v == 1
        elif fid == 0x03:
            out["mode"] = _WT30X_MODE.get(v, "unknown")
        elif fid == 0x04:
            out["fan_speed"] = _WT30X_FAN.get(v, "unknown")
        elif fid in (0x05, 0x06, 0x09):
            out[{5: "temperature", 6: "target_temperature", 9: "server_temperature"}[fid]] = v / 2
        elif fid == 0x07:
            out["card_inserted"] = v == 1
        elif fid == 0x08:
            out["control_mode"] = {0: "auto", 1: "manual"}.get(v, "unknown")

    if data_id == 0x0F and len(d) >= 9:
        for k in range(9):
            field(k + 1, d[k])
    elif 0x01 <= data_id <= 0x09 and d:
        field(data_id, d[0])
    return out


# ---- WT303 / WT304 fan-coil thermostats (command format) -----------------------------------------
_WT303_ALARM = {0x10: ("lower_range_alarm_deactivation", False), 0x11: ("lower_range_alarm_trigger", True),
                0x12: ("over_range_alarm_deactivation", False), 0x13: ("over_range_alarm_trigger", True),
                0x14: ("within_range_alarm_deactivation", False), 0x15: ("within_range_alarm_trigger", True),
                0x16: ("exceed_range_alarm_deactivation", False), 0x17: ("exceed_range_alarm_trigger", True),
                0x20: ("persistent_low_temperature_alarm_deactivation", False),
                0x21: ("persistent_low_temperature_alarm_trigger", True),
                0x22: ("persistent_high_alarm_deactivation", False), 0x23: ("persistent_high_alarm_trigger", True),
                0x30: ("anti_freeze_protection_deactivation", False), 0x31: ("anti_freeze_protection_trigger", True),
                0x32: ("window_status_detection_deactivation", False), 0x33: ("window_status_detection_trigger", True)}
_WT_ERR = {0: "collection error", 1: "lower range error", 2: "over range error", 3: "no data"}
_WT303_MODE = {0: "ventilation", 1: "heat", 2: "cool"}
_WT303_STATUS = {0: "standby", 1: "heat", 2: "cool"}
_WT303_FAN = {0: "auto", 1: "low", 2: "medium", 3: "high"}
_WT303_FAN_STATUS = {0: "off", 1: "low", 2: "medium", 3: "high"}


def _wt_info(cmd: int, b: bytes, i: int, out: dict, extra: bool) -> int | None:
    """Device info commands shared by the WT command-format devices. Returns bytes consumed or None."""
    if cmd == 0xDF and _need(b, i, 2):
        out["tsl_version"] = f"v{b[i]}.{b[i + 1]}"
        return 2
    if cmd == 0xDB and _need(b, i, 8):
        out["sn"] = b[i:i + 8].hex()
        return 8
    if cmd == 0xDA and _need(b, i, 8):
        out["hardware_version"] = f"v{b[i]}.{b[i + 1]}"
        out["firmware_version"] = f"v{b[i + 2]:x}.{b[i + 3]:x}"
        return 8
    if cmd == 0xD9 and _need(b, i, 2):
        return 2
    if cmd == 0xC8 and _need(b, i, 1):
        out["device_status"] = "on" if b[i] else "off"
        return 1
    if extra and cmd in (0xDE, 0xDD) and _need(b, i, 32):
        return 32
    if extra and cmd == 0xD8 and _need(b, i, 16):
        return 16
    return None


def decode_wt303(b: bytes) -> dict[str, Any]:
    """WT303 / WT304 fan-coil thermostat."""
    return _parse_wt303(b)[0]


def wt303_parses_completely(b: bytes) -> bool:
    return bool(b) and _parse_wt303(b)[1] == len(b)


def _parse_wt303(b: bytes) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    i = 0
    while i < len(b):
        cmd = b[i]
        i += 1
        n = _wt_info(cmd, b, i, out, extra=False)
        if n is not None:
            i += n
        elif cmd in (0x01, 0x03, 0x6B, 0x6C) and _need(b, i, 2):
            key = {0x01: "temperature", 0x03: "target_temperature", 0x6B: "heating_target_temperature",
                   0x6C: "cooling_target_temperature"}[cmd]
            out[key] = _i16le(b, i) / 100
            i += 2
        elif cmd == 0x02 and _need(b, i, 2):
            out["humidity"] = _u16le(b, i) / 10
            i += 2
        elif cmd == 0x04 and _need(b, i, 1):
            out["data_source"] = {0: "internal", 1: "external NTC", 2: "LoRaWAN", 3: "D2D"}.get(b[i], "unknown")
            i += 1
        elif cmd == 0x05 and _need(b, i, 1):
            out["temperature_control_mode"] = _WT303_MODE.get(b[i] >> 4, "unknown")
            out["temperature_control_status"] = _WT303_STATUS.get(b[i] & 0x0F, "unknown")
            i += 1
        elif cmd == 0x06 and _need(b, i, 1):
            out["valve_opening"] = b[i]
            i += 1
        elif cmd == 0x07 and _need(b, i, 1):
            out["fan_mode"] = _WT303_FAN.get(b[i] >> 4, "unknown")
            out["fan_status"] = _WT303_FAN_STATUS.get(b[i] & 0x0F, "unknown")
            i += 1
        elif cmd == 0x08 and _need(b, i, 1):
            out["execution_plan"] = "not executed" if b[i] == 255 else f"schedule {b[i] + 1}"
            i += 1
        elif cmd == 0x09 and _need(b, i, 1):
            code = b[i]
            i += 1
            if code in _WT303_ALARM:
                if not _need(b, i, 2):
                    break
                out["temperature"] = _i16le(b, i) / 100
                _ts_alarm(out, "temperature", code, _WT303_ALARM)
                i += 2
            elif code in _WT_ERR:
                out["sensor_error"] = f"Temperature: {_WT_ERR[code]}"
        elif cmd in (0x0A, 0x0B) and _need(b, i, 1):
            if b[i] in _WT_ERR:
                out["sensor_error"] = ("Humidity: " if cmd == 0x0A else "Target temperature: ") + _WT_ERR[b[i]]
            i += 1
        elif cmd == 0x10 and _need(b, i, 4):
            v = _u32le(b, i)
            if v > 0xFFFF:                       # the official decoder rejects these frames
                break
            for bit, name in enumerate(("relay_low", "relay_medium", "relay_high", "valve_1", "valve_2")):
                out[name] = bool(v >> bit & 1)
            i += 4
        elif cmd == 0xCF and _need(b, i, 1):
            i += 2 if b[i] == 0 and _need(b, i, 2) else 1
        elif cmd == 0x67 and _need(b, i, 1):
            out["system_status"] = b[i] == 1
            i += 1
        elif cmd == 0x68 and _need(b, i, 1):
            out["temperature_control_mode"] = _WT303_MODE.get(b[i], "unknown")
            i += 1
        elif cmd == 0x72 and _need(b, i, 1):
            out["fan_mode"] = _WT303_FAN.get(b[i], "unknown")
            i += 1
        else:
            i -= 1
            break
    return out, i


# ---- WT102 smart radiator thermostat (command format) ------------------------------------------
_WT102_CAL = {0: "uncalibrated", 1: "success", 2: "fail: out of range", 3: "fail: temperature control disabled",
              4: "fail: uninstalled"}
_WT102_TALARM = {0x10: ("lower_range_alarm_deactivation", False), 0x11: ("lower_range_alarm_trigger", True),
                 0x12: ("over_range_alarm_deactivation", False), 0x13: ("over_range_alarm_trigger", True)}


def decode_wt102(b: bytes) -> dict[str, Any]:
    """WT102 smart radiator thermostat."""
    return _parse_wt102(b)[0]


def wt102_parses_completely(b: bytes) -> bool:
    return bool(b) and _parse_wt102(b)[1] == len(b)


def _parse_wt102(b: bytes) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    t = lambda k: _i16le(b, k) / 100            # noqa: E731
    i = 0
    while i < len(b):
        cmd = b[i]
        i += 1
        n = _wt_info(cmd, b, i, out, extra=True)
        sub = b[i] if i < len(b) else None
        if n is not None:
            i += n
        elif cmd == 0x00 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cmd in (0x01, 0x06) and _need(b, i, 2):
            out["temperature" if cmd == 0x01 else "target_temperature"] = t(i)
            i += 2
        elif cmd in (0x02, 0x03) and _need(b, i, 2):
            out["motor_stroke" if cmd == 0x02 else "motor_position"] = _u16le(b, i)
            i += 2
        elif cmd in (0x04, 0x07) and _need(b, i, 1):
            out["valve_opening" if cmd == 0x04 else "target_valve_opening"] = b[i]
            i += 1
        elif cmd == 0x05 and _need(b, i, 1):
            out["motor_calibration_result"] = _WT102_CAL.get(b[i], "unknown")
            i += 1
        elif cmd == 0x08 and _need(b, i, 1):
            out["battery"] = b[i]
            out["battery_low_alarm"] = True
            i += 1
        elif cmd == 0x09 and sub is not None:
            i += 1
            if sub in _WT102_TALARM:
                if not _need(b, i, 2):
                    break
                out["temperature"] = t(i)
                _ts_alarm(out, "temperature", sub, _WT102_TALARM)
                i += 2
        elif cmd == 0x0A and sub is not None:
            i += 1
            if sub in (0x20, 0x21):
                if not _need(b, i, 3):
                    break
                out["temperature"], out["valve_opening"] = t(i), b[i + 2]
                out["freeze_protection"] = sub == 0x21
                i += 3
        elif cmd == 0x0B and sub is not None:
            i += 1
            if sub in (0x20, 0x21):
                if not _need(b, i, 4):
                    break
                out["temperature"], out["valve_opening"], out["battery"] = t(i), b[i + 2], b[i + 3]
                out["mandatory_heating"] = sub == 0x21
                i += 4
        elif cmd == 0x0C and sub is not None:
            i += 1
            if sub in (0x20, 0x21, 0x22, 0x23):
                size = 5 if sub in (0x20, 0x21) else 4
                if not _need(b, i, size):
                    break
                out["occupied"] = b[i] == 1
                out["temperature"] = t(i + 1)
                if sub == 0x20:
                    out["target_temperature"] = t(i + 3)
                elif sub == 0x22:
                    out["target_valve_opening"] = b[i + 3]
                out["auto_away"] = sub in (0x21, 0x23)
                i += size
        elif cmd == 0x0D and sub is not None:
            i += 1
            if sub in (0x20, 0x21):
                if not _need(b, i, 3):
                    break
                out["window_open"] = b[i] == 1
                out["temperature"] = t(i + 1)
                i += 3
        elif cmd == 0x0E and sub is not None:
            i += 1
            size = {0: 2, 1: 6, 2: 5, 3: 7}.get(sub)
            if size is None:
                continue
            if not _need(b, i, size):
                break
            if sub == 0:
                out["target_valve_opening"], out["battery"] = b[i], b[i + 1]
            else:
                out["temperature"], out["valve_opening"] = t(i), b[i + 2]
                if sub in (1, 3):
                    out["target_temperature"] = t(i + 3)
                if sub == 2:
                    out["target_valve_opening"] = b[i + 3]
                if sub == 3:
                    out["target_valve_opening"] = b[i + 5]
                out["battery"] = b[i + size - 1]
            i += size
        elif cmd == 0xCF and _need(b, i, 2):
            out["lorawan_class"] = {0: "Class A", 1: "Class B", 2: "Class C", 3: "Class CtoB"}.get(b[i + 1], "unknown")
            i += 2
        else:
            i -= 1
            break
    return out, i


# ---- WT401 smart thermostat (command format) ---------------------------------------------------
_WT401_MODE = {0: "heat", 1: "em heat", 2: "cool", 3: "auto", 4: "dehumidify", 5: "ventilation", 10: "off", 11: "none"}
_WT401_FAN = {0: "auto", 1: "circulate", 2: "on", 3: "low", 4: "medium", 5: "high", 10: "off", 11: "none"}


def decode_wt401(b: bytes) -> dict[str, Any]:
    """WT401 smart thermostat."""
    return _parse_wt401(b)[0]


def wt401_parses_completely(b: bytes) -> bool:
    return bool(b) and _parse_wt401(b)[1] == len(b)


def _parse_wt401(b: bytes) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    i = 0
    while i < len(b):
        cmd = b[i]
        i += 1
        n = _wt_info(cmd, b, i, out, extra=True)
        if n is not None:
            i += n
        elif cmd == 0x00 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cmd in (0x01, 0x06, 0x07) and _need(b, i, 2):
            out[{1: "temperature", 6: "target_temperature", 7: "target_temperature_2"}[cmd]] = _i16le(b, i) / 100
            i += 2
        elif cmd == 0x02 and _need(b, i, 2):
            out["humidity"] = _u16le(b, i) / 10
            i += 2
        elif cmd == 0x03 and _need(b, i, 1):
            out["temperature_control_mode"] = _WT401_MODE.get(b[i], "unknown")
            i += 1
        elif cmd == 0x04 and _need(b, i, 1):
            out["fan_mode"] = _WT401_FAN.get(b[i], "unknown")
            i += 1
        elif cmd == 0x05 and _need(b, i, 1):
            out["execution_plan"] = "not executed" if b[i] == 255 else f"schedule {b[i] + 1}"
            i += 1
        elif cmd == 0x08 and _need(b, i, 1):
            out["occupancy"] = 1 if b[i] in (1, 2) else 0
            out["pir_status"] = {0: "vacant", 1: "occupied", 2: "night occupied"}.get(b[i], "unknown")
            i += 1
        elif cmd in (0x09, 0x0A, 0x0D, 0x0F) and _need(b, i, 1):
            if cmd == 0x09:
                out["ble_event"] = {0: "none", 1: "pair cancel", 2: "disconnect"}.get(b[i], "unknown")
            elif cmd == 0x0A:
                out["power_bus_disconnected"] = b[i] == 1
            elif cmd == 0x0D and b[i] <= 2:
                out.setdefault("button_events", []).append((f"key_f{b[i] + 1}", "press"))
            i += 1
        elif cmd in (0x0B, 0x0C) and _need(b, i, 1):
            if b[i] in _WT_ERR:
                out["sensor_error"] = ("Temperature: " if cmd == 0x0B else "Humidity: ") + _WT_ERR[b[i]]
            i += 1
        elif cmd == 0xCF and _need(b, i, 1):
            i += 2 if b[i] == 0 and _need(b, i, 2) else 1
        elif cmd == 0xC9 and _need(b, i, 1):
            i += 1
        elif cmd == 0x67 and _need(b, i, 1):
            out["system_status"] = b[i] == 1
            i += 1
        elif cmd == 0x74 and _need(b, i, 1):
            out["fan_mode"] = _WT401_FAN.get(b[i], "unknown")
            i += 1
        else:
            i -= 1
            break
    return out, i


# ---- WT downlinks (fPort 85) – verified against Milesight's official encoders --------------------
WT_MODE_CODES = {
    "wt201": {"heat": 0, "em heat": 1, "cool": 2, "auto": 3},
    "wt201v2": {"heat": 0, "em heat": 1, "cool": 2, "auto": 3},
    "wt30x": {"cool": 0, "heat": 1, "fan": 2},
    "wt303": {"ventilation": 0, "heat": 1, "cool": 2},
    "wt401": {"heat": 0, "em heat": 1, "cool": 2, "auto": 3, "dehumidify": 4, "ventilation": 5},
}
WT_FAN_CODES = {
    "wt201": {"auto": 0, "on": 1, "circulate": 2},
    "wt201v2": {"auto": 0, "on": 1, "circulate": 2},
    "wt30x": {"auto": 0, "high": 1, "medium": 2, "low": 3},
    "wt303": {"auto": 0, "low": 1, "medium": 2, "high": 3},
    "wt401": {"auto": 0, "circulate": 1, "on": 2, "low": 3, "medium": 4, "high": 5},
}
_WT401_SETPOINT = {"heat": 0, "em heat": 1, "cool": 2, "auto": 3, "dehumidify": 6, "ventilation": 7}


def _s16(v: float, scale: int) -> bytes:
    return int(round(v * scale)).to_bytes(2, "little", signed=True)


def _wt30x_frame(field: int, value: int) -> bytes:
    frame = bytes([0x55, 0x01, 0x00, 0x02, field, value])
    return frame + bytes([sum(frame) & 0xFF])


def encode_wt(kind: str, action: str, value: Any = None, *, mode: str | None = None,
              target: float | None = None, on: bool = True) -> bytes:
    """action: target (value = °C, mode = current mode) | mode (value = mode name) | power (value = bool)
    | fan (value = fan mode name)."""
    if kind == "wt101":
        if action == "target":
            return bytes([0xFF, 0xB1, int(value) & 0xFF]) + (10).to_bytes(2, "little")   # tolerance 1.0 °C
        if action == "power":
            return bytes([0xFF, 0xB3, 1 if value else 0])
    elif kind == "wt102":
        if action == "target":
            return bytes([0x5A]) + _s16(value, 100)
        if action == "power":
            return bytes([0x65, 0x00, 1 if value else 0])
    elif kind == "wt201":
        if action == "target":
            return bytes([0xFF, 0xFA, WT_MODE_CODES[kind][mode or "heat"]]) + _s16(value, 10)
        if action == "mode":
            return bytes([0xFF, 0xFB, WT_MODE_CODES[kind][value]])
        if action == "power":
            return bytes([0xFF, 0xC5, 1 if value else 0])
        if action == "fan":
            return bytes([0xFF, 0xB6, WT_FAN_CODES[kind][value]])
    elif kind == "wt201v2":
        if action == "target":
            return bytes([0xFF, 0xFA, WT_MODE_CODES[kind][mode or "heat"]]) + _s16(value, 10)
        if action in ("mode", "power"):          # system status + mode + target in one command
            m = value if action == "mode" else (mode or "heat")
            return bytes([0xF9, 0x45, 1 if (on if action == "mode" else value) else 0,
                          WT_MODE_CODES[kind][m]]) + _s16(target if target is not None else 21, 10)
        if action == "fan":
            return bytes([0xFF, 0xB6, WT_FAN_CODES[kind][value]])
    elif kind == "wt30x":
        if action == "target":
            return _wt30x_frame(0x05, int(round(value * 2)))
        if action == "mode":
            return _wt30x_frame(0x03, WT_MODE_CODES[kind][value])
        if action == "power":
            return _wt30x_frame(0x01, 1 if value else 0)
        if action == "fan":
            return _wt30x_frame(0x04, WT_FAN_CODES[kind][value])
    elif kind == "wt303":
        if action == "target":
            return bytes([0x6C if mode == "cool" else 0x6B]) + _s16(value, 100)
        if action == "mode":
            return bytes([0x68, WT_MODE_CODES[kind][value]])
        if action == "power":
            return bytes([0x67, 1 if value else 0])
        if action == "fan":
            return bytes([0x72, WT_FAN_CODES[kind][value]])
    elif kind == "wt401":
        if action == "target":
            return bytes([0x69, _WT401_SETPOINT.get(mode or "heat", 0)]) + _s16(value, 100)
        if action == "mode":
            return bytes([0x68, 0x00, WT_MODE_CODES[kind][value]])
        if action == "power":
            return bytes([0x67, 1 if value else 0])
        if action == "fan":
            return bytes([0x74, WT_FAN_CODES[kind][value]])
    raise ValueError(f"{kind}: {action} not supported")


# --------------------------------------------------------------------------
# CTH01 multi-circuit energy meter (12 CT inputs in 4 circuits a–d, 3 voltage phases)
# Command format; checked against Milesight-IoT/SensorDecoders (cth-series/cth01 and cth01-compress).
# Keys: current_ct1..12, thdi_ct1..12, voltage_l1..3, thdv_l1..3, and per circuit a–d either a circuit total
# (<measure>_a) or per CT values (<measure>_ct1..ct12) for power factor, powers and energies.
# --------------------------------------------------------------------------
_CTH_MASKED = {  # id -> (measure, first circuit index (0 = a), signed, divisor)
    0x08: ("active_power", 0, True), 0x09: ("active_power", 2, True),
    0x0A: ("reactive_power", 0, True), 0x0B: ("reactive_power", 2, True),
    0x0C: ("apparent_power", 0, True), 0x0D: ("apparent_power", 2, True),
    0x0E: ("forward_active_energy", 0, False), 0x0F: ("forward_active_energy", 2, False),
    0x10: ("reverse_active_energy", 0, False), 0x11: ("reverse_active_energy", 2, False),
    0x12: ("forward_reactive_energy", 0, False), 0x13: ("forward_reactive_energy", 2, False),
    0x14: ("reverse_reactive_energy", 0, False), 0x15: ("reverse_reactive_energy", 2, False),
    0x16: ("apparent_energy", 0, False), 0x17: ("apparent_energy", 2, False),
}
_CTH_ALARM = {0x00: ("collection_error", None), 0x01: ("lower_range_error", None), 0x02: ("over_range_error", None),
              0x03: ("no_data", None), 0x04: ("over_range_release", False),
              0x10: ("lower_range_alarm_deactivation", False), 0x11: ("lower_range_alarm_trigger", True),
              0x12: ("over_range_alarm_deactivation", False), 0x13: ("over_range_alarm_trigger", True),
              0x14: ("within_range_alarm_deactivation", False), 0x15: ("within_range_alarm_trigger", True),
              0x16: ("exceed_range_alarm_deactivation", False), 0x17: ("exceed_range_alarm_trigger", True)}
# config replies: id -> total size after the id (callable for variable sizes)
_CTH_SKIP = {
    0x60: lambda b, i: 3 if i < len(b) and b[i] in (0, 1) else 1, 0x61: lambda b, i: 3 if i < len(b) and b[i] in (0, 1) else 1,
    0x63: 1, 0x66: 1, 0x64: lambda b, i: 1 + (b[i] if i < len(b) else 0), 0x67: 10, 0x68: 10, 0x69: 10, 0x6A: 10,
    0x6B: 2, 0x6C: 2, 0x6D: 3, 0x76: 6, 0x77: 7, 0x78: 7, 0x79: 7, 0x7A: 7, 0x7B: 6, 0x7C: 5,
    0xC5: lambda b, i: 2 if i < len(b) and b[i] in (0, 1) else 3, 0xC6: 10, 0xC7: 2, 0xB7: 4, 0x5B: 5, 0x5C: 9,
    0x5D: 1, 0x5E: 1, 0x5F: 1, 0xEF: lambda b, i: 1 + ((b[i] & 0x0F) if i < len(b) else 0), 0xFF: 1, 0xFE: 1,
    0xEE: 0, 0xBF: 0, 0xBE: 0, 0xB9: 0, 0xB8: 0, 0xB6: 0, 0x57: 0, 0xD7: 0,
}


def _cth_value(out: dict, key: str, raw: int, sentinel: int, div: float, errors: list) -> None:
    if raw == sentinel:
        errors.append(key)
    else:
        out[key] = raw / div


def decode_cth01(b: bytes) -> dict[str, Any]:
    return _parse_cth01(b)[0]


def cth01_parses_cleanly(b: bytes) -> bool:
    """True when every byte belongs to a known CTH01 command (used for model detection)."""
    return bool(b) and _parse_cth01(b)[1]


def _parse_cth01(b: bytes) -> tuple[dict[str, Any], bool]:
    out: dict[str, Any] = {}
    errors: list[str] = []
    clean = True
    b = bytes(b)
    i = 0
    while i < len(b):
        cmd = b[i]
        i += 1
        n = _wt_info(cmd, b, i, out, extra=True)
        if n is not None:
            i += n
            continue
        if cmd == 0x01 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 100
            i += 2
        elif cmd == 0x02 and _need(b, i, 2):
            _cth_value(out, "voltage_unbalance", _u16le(b, i), 0xFFFF, 100, errors)
            i += 2
        elif cmd in (0x03, 0x04, 0x05, 0x06):
            count, size = {0x03: (12, 2), 0x04: (3, 2), 0x05: (12, 3), 0x06: (3, 2)}[cmd]
            if not _need(b, i, count * size):
                clean = False
                break
            name = {0x03: "thdi_ct", 0x04: "thdv_l", 0x05: "current_ct", 0x06: "voltage_l"}[cmd]
            for k in range(count):
                raw = _u24le(b, i + k * 3) if size == 3 else _u16le(b, i + k * 2)
                _cth_value(out, f"{name}{k + 1}", raw, 0xFFFFFF if size == 3 else 0xFFFF, 100, errors)
            i += count * size
        elif cmd == 0x07 and _need(b, i, 1):
            mask = b[i]
            i += 1
            for g in range(4):
                per_ct = mask >> g & 1
                if not _need(b, i, 3 if per_ct else 1):
                    i = len(b) + 1
                    break
                if per_ct:
                    for k in range(3):
                        _cth_value(out, f"power_factor_ct{g * 3 + k + 1}", b[i + k], 0xFF, 100, errors)
                    i += 3
                else:
                    _cth_value(out, f"power_factor_{'abcd'[g]}", b[i], 0xFF, 100, errors)
                    i += 1
            if i > len(b):
                clean = False
                break
        elif cmd in _CTH_MASKED and _need(b, i, 1):
            measure, first, signed = _CTH_MASKED[cmd]
            mask = b[i]
            i += 1
            for g in range(2):
                circuit = first + g
                count = 3 if mask >> g & 1 else 1
                if not _need(b, i, count * 4):
                    i = len(b) + 1
                    break
                for k in range(count):
                    raw = _i32le(b, i + k * 4) if signed else _u32le(b, i + k * 4)
                    key = f"{measure}_ct{circuit * 3 + k + 1}" if count == 3 else f"{measure}_{'abcd'[circuit]}"
                    _cth_value(out, key, raw, -1 if signed else 0xFFFFFFFF, 1000, errors)
                i += count * 4
            if i > len(b):
                clean = False
                break
        elif 0x30 <= cmd <= 0x35:
            has_channel = cmd in (0x31, 0x32, 0x33, 0x34)
            if not _need(b, i, 2 if has_channel else 1):
                clean = False
                break
            channel = b[i] if has_channel else None
            code = b[i + 1] if has_channel else b[i]
            i += 2 if has_channel else 1
            name = {0x30: "temperature", 0x31: "current", 0x32: "voltage", 0x33: "thdi", 0x34: "thdv",
                    0x35: "voltage_unbalance"}[cmd]
            with_value = {0x30: range(0x10, 0x18), 0x31: (1, 2, 4, *range(0x10, 0x18)), 0x32: (1, 2, 4, *range(0x10, 0x18)),
                          0x33: (0x12, 0x13), 0x34: (0x12, 0x13), 0x35: (0x12, 0x13)}[cmd]
            known = {0x30: (0, 1, 2, 3, *range(0x10, 0x18)), 0x33: (0, 0x12, 0x13), 0x34: (0, 0x12, 0x13),
                     0x35: (0, 0x12, 0x13)}.get(cmd, tuple(_CTH_ALARM))
            if code in with_value:
                size = 3 if cmd == 0x31 else 2
                if not _need(b, i, size):
                    clean = False
                    break
                i += size
            if code in known:
                label = name if channel is None else (
                    f"current_ct{channel + 1}" if cmd == 0x31 else f"thdi_ct{channel + 1}" if cmd == 0x33
                    else f"{name}_l{channel + 1}")
                _ts_alarm(out, label, code, _CTH_ALARM)
        elif cmd == 0x36:
            out["power_loss_alarm"] = True
            out["_power_loss"] = True
        elif cmd == 0x40 and _need(b, i, 1):
            i += 1
        elif cmd == 0xED:                         # history follows – live values end here
            break
        elif cmd == 0xCF and _need(b, i, 1):
            i += 2 if b[i] == 0xD8 and _need(b, i, 2) else 1
        elif cmd in _CTH_SKIP:
            skip = _CTH_SKIP[cmd]
            i += skip(b, i) if callable(skip) else skip
        else:
            clean = False                        # unknown ids are skipped (one byte), like the official decoder
    measured = any(re.fullmatch(r"(current_ct|voltage_l)\d+", k) for k in out)
    if not out.pop("_power_loss", False) and measured:
        out["power_loss_alarm"] = False                # measurements again -> mains is back
    if errors:
        out["sensor_error"] = "Read error: " + ", ".join(e.replace("_", " ") for e in errors[:6]) + \
            (" …" if len(errors) > 6 else "")
    elif measured:
        out["sensor_error"] = "OK"
    return out, clean


# --------------------------------------------------------------------------
# AM100 / AM300L ranges and DS3604 display – checked against Milesight-IoT/SensorDecoders (tools/checks/am.py)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# AM102 / AM102L / AM103 / AM103L / AM104 / AM107 (AM100 range, IPSO channel format)
# Checked against Milesight-IoT/SensorDecoders (am-series).
# Config replies (0xFF/0xFE + type) are skipped with the lengths the official decoders use;
# history records (0x20 0xCE) are skipped, not output.
# --------------------------------------------------------------------------
def _hw_version_dec(b: bytes, i: int) -> str:
    """Official AM10x / DS3604 hardware version: major in hex, minor = high nibble in decimal."""
    return f"v{b[i]:x}.{b[i + 1] >> 4}"


# downlink-response type -> fixed length (variable ones are handled in _am10x_config_len)
_AM10X_CFG = {0x03: 2, 0x06: 9, 0x10: 1, 0x11: 4, 0x17: 2, 0x27: 1, 0x2D: 1, 0x2F: 1, 0x3B: 1, 0x56: 1,
              0x57: 1, 0x59: 1, 0x5A: 2, 0x68: 1, 0x69: 1, 0x6A: 3, 0x75: 7, 0x85: 1, 0x86: 1,
              0x39: 5, 0x54: 5, 0x87: 3, 0xF0: 4}
_AM10X_CO2_CFG = frozenset({0x1A, 0x39, 0x54, 0x87})   # only on the CO2 models (AM103/AM103L/AM107)


def _am10x_config_len(ctype: int, b: bytes, i: int, co2: bool) -> int | None:
    if ctype in _AM10X_CO2_CFG and not co2:
        return None
    if ctype == 0x3A:                       # report schedule: count + 6 bytes per entry
        if not _need(b, i, 1):
            return None
        n = 1 + 6 * b[i]
    elif ctype == 0x1A:                     # CO2 calibration: mode (+ value when mode 2)
        if not _need(b, i, 1):
            return None
        n = 3 if b[i] == 2 else 1
    else:
        n = _AM10X_CFG.get(ctype)
    return n if n is not None and _need(b, i, n) else None


def _decode_am10x(b: bytes, *, sn_type: int, hist_len: int | None, co2: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        if cid == 0xFF and ctype == 0x09 and _need(b, i, 2):
            out["hardware_version"] = _hw_version_dec(b, i)
            i += 2
        elif cid == 0xFF and ctype in (0x01, 0x0A, 0xFF, sn_type, 0x0F, 0xFE, 0x0B) and \
                (n := _decode_common(cid, ctype, b, i, out)) is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x67 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x04 and ctype == 0x68 and _need(b, i, 1):
            out["humidity"] = b[i] / 2
            i += 1
        elif hist_len is None and cid == 0x05 and ctype == 0x6A and _need(b, i, 2):   # AM104 / AM107
            out["pir_activity"] = _u16le(b, i)
            i += 2
        elif hist_len is None and cid == 0x06 and ctype == 0x65 and _need(b, i, 6):
            out["illuminance_lux"] = _u16le(b, i)
            out["infrared_and_visible"] = _u16le(b, i + 2)
            out["infrared"] = _u16le(b, i + 4)
            i += 6
        elif co2 and cid == 0x07 and ctype == 0x7D and _need(b, i, 2):
            out["co2"] = _u16le(b, i)
            i += 2
        elif co2 and hist_len is None and cid == 0x08 and ctype == 0x7D and _need(b, i, 2):   # AM107: ppb
            out["tvoc_ppb"] = _u16le(b, i)
            i += 2
        elif co2 and hist_len is None and cid == 0x09 and ctype == 0x73 and _need(b, i, 2):
            out["pressure"] = _u16le(b, i) / 10
            i += 2
        elif hist_len is not None and cid == 0x20 and ctype == 0xCE and _need(b, i, hist_len):
            i += hist_len                                         # history record – skipped
        elif cid == 0xFF and ctype == 0x18 and _need(b, i, 2):    # sensor enable (config)
            i += 2
        elif cid in (0xFE, 0xFF) and (n := _am10x_config_len(ctype, b, i, co2)) is not None:
            i += n                                                # downlink response – skipped
        else:
            break
    return out


def decode_am102(b: bytes) -> dict[str, Any]:
    """AM102 / AM102L temperature & humidity sensor (e-ink)."""
    return _decode_am10x(b, sn_type=0x16, hist_len=7, co2=False)


def decode_am103(b: bytes) -> dict[str, Any]:
    """AM103 / AM103L temperature, humidity & CO2 sensor (e-ink)."""
    return _decode_am10x(b, sn_type=0x16, hist_len=9, co2=True)


def decode_am104(b: bytes) -> dict[str, Any]:
    """AM104 temperature, humidity, PIR activity & light sensor."""
    return _decode_am10x(b, sn_type=0x08, hist_len=None, co2=False)


def decode_am107(b: bytes) -> dict[str, Any]:
    """AM107 7-in-1 (temperature, humidity, PIR activity, light, CO2, TVOC ppb, pressure)."""
    return _decode_am10x(b, sn_type=0x08, hist_len=None, co2=True)


# --------------------------------------------------------------------------
# AM304L / AM305L (new AM300L range, IPSO channel format with event channels)
# Checked against Milesight-IoT/SensorDecoders (am-series). AM304L = AM305L without CO2.
# --------------------------------------------------------------------------
_AM30XL_TEMP_ALARM = {
    16: ("below_threshold_alarm_release", False), 17: ("below_threshold_alarm", True),
    18: ("above_threshold_alarm_release", False), 19: ("above_threshold_alarm", True),
    20: ("between_threshold_alarm_release", False), 21: ("between_threshold_alarm", True),
    22: ("exceed_tolerance_alarm_release", False), 23: ("exceed_tolerance_alarm", True),
}
_AM30XL_LUX_ALARM = {16: ("dim", None), 17: ("bright", None)}
_AM30XL_CO2_ALARM = {16: ("polluted_alarm_release", False), 17: ("polluted_alarm", True),
                     18: ("bad_alarm_release", False), 19: ("bad_alarm", True)}
_AM30XL_ANOMALY = {(0xB3, 0x67): "Temperature", (0xB4, 0x68): "Humidity", (0xB6, 0xCB): "Illuminance level",
                   (0xB6, 0x9D): "Illuminance", (0xB7, 0x7D): "CO2"}
_AM30XL_ANOMALY_TEXT = {0: "collection failed", 1: "out of range"}
# config replies: (cid, ctype) -> length, or a dict {first byte: length} (other first bytes consume 0)
_AM30XL_CFG: dict[tuple[int, int], Any] = {
    (0xFF, 0xFE): 1, (0xFF, 0xF2): 2, (0xFF, 0xF5): 1, (0xFF, 0x2E): 1, (0xFF, 0x25): 1, (0xFF, 0x06): 9,
    (0xFF, 0x18): {3: 2, 4: 2}, (0xFF, 0x95): 2, (0xFF, 0xEA): "ea", (0xFF, 0x96): 8, (0xFF, 0x68): 1,
    (0xFF, 0x69): 1, (0xFF, 0x6A): {0: 3, 1: 3}, (0xFF, 0x27): 1, (0xFF, 0x10): 1, (0xFF, 0x4A): 1,
    (0xF9, 0xBD): 3, (0xF9, 0xBE): 4, (0xF9, 0xC0): {0: 2, 1: 2}, (0xF9, 0xBC): {0: 2, 1: 2}, (0xF9, 0xBF): 5,
    (0xF9, 0x63): 4, (0xF9, 0x66): 1,
    (0xFD, 0x6B): 4, (0xFD, 0x6C): 8, (0xFD, 0x6D): 1,
}
_AM305L_CFG: dict[tuple[int, int], Any] = {      # AM305L only (CO2)
    **_AM30XL_CFG, (0xFF, 0x18): {3: 2, 4: 2, 5: 2}, (0xFF, 0x39): 5, (0xFF, 0x87): 3,
    (0xFF, 0x1A): {0: 1, 3: 1}, (0xF9, 0xC4): 6,
}


def _am30xl_cfg_len(cid: int, ctype: int, b: bytes, i: int, co2: bool) -> int | None:
    spec = (_AM305L_CFG if co2 else _AM30XL_CFG).get((cid, ctype))
    if spec is None or not _need(b, i, 1):
        return None
    if spec == "ea":                                    # calibration: id in low 7 bits (2 = CO2, AM305L)
        spec = {0: 3, 1: 3, 2: 3 if co2 else 0}.get(b[i] & 0x7F, 0)
    elif isinstance(spec, dict):
        spec = spec.get(b[i], 0)
    return spec if _need(b, i, spec) else None


def decode_am304l(b: bytes) -> dict[str, Any]:
    """AM304L temperature, humidity, PIR & light sensor."""
    return _decode_am30xl(b, co2=False)


def decode_am305l(b: bytes) -> dict[str, Any]:
    """AM305L temperature, humidity, PIR, light & CO2 sensor."""
    return _decode_am30xl(b, co2=True)


def _decode_am30xl(b: bytes, co2: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        if cid == 0xFF and ctype == 0x0B and _need(b, i, 1):
            out["device_status"] = "on" if b[i] else "off"
            i += 1
        elif cid == 0xFF and ctype == 0x01 and _need(b, i, 1):
            out["protocol_version"] = b[i]
            i += 1
        elif cid == 0xFF and ctype == 0x09 and _need(b, i, 2):
            out["hardware_version"] = f"v{b[i]}.{b[i + 1]}"
            i += 2
        elif cid == 0xFF and ctype in (0x16, 0xFF, 0x0A, 0x0F) and \
                (n := _decode_common(cid, ctype, b, i, out)) is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x67 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x04 and ctype == 0x68 and _need(b, i, 1):
            out["humidity"] = b[i] / 2
            i += 1
        elif cid == 0x05 and ctype == 0x9F and _need(b, i, 2):
            v = _u16le(b, i)
            out["pir"] = bool(v >> 15)
            out["occupancy"] = v >> 15
            out["pir_count"] = v & 0x7FFF
            i += 2
        elif cid == 0x05 and ctype == 0x00 and _need(b, i, 1):     # PIR status change event
            out["pir"] = b[i] == 1
            out["occupancy"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid == 0x06 and ctype == 0xCB and _need(b, i, 1):
            out["light_level"] = b[i]
            i += 1
        elif cid == 0x06 and ctype == 0x9D and _need(b, i, 2):
            out["illuminance_lux"] = _u16le(b, i)
            i += 2
        elif co2 and cid == 0x07 and ctype == 0x7D and _need(b, i, 2):
            out["co2"] = _u16le(b, i)
            i += 2
        elif (cid, ctype) in _AM30XL_ANOMALY and (co2 or cid != 0xB7) and _need(b, i, 1):
            errors[_AM30XL_ANOMALY[(cid, ctype)]] = _AM30XL_ANOMALY_TEXT.get(b[i], "unknown")
            i += 1
        elif cid == 0x83 and ctype == 0x67 and _need(b, i, 3):
            out["temperature"] = _i16le(b, i) / 10
            _ts_alarm(out, "temperature", b[i + 2], _AM30XL_TEMP_ALARM)
            i += 3
        elif cid == 0x86 and ctype == 0x9D and _need(b, i, 3):
            out["illuminance_lux"] = _u16le(b, i)
            _ts_alarm(out, "illuminance", b[i + 2], _AM30XL_LUX_ALARM)
            i += 3
        elif co2 and cid == 0x87 and ctype == 0x7D and _need(b, i, 3):
            out["co2"] = _u16le(b, i)
            _ts_alarm(out, "co2", b[i + 2], _AM30XL_CO2_ALARM)
            i += 3
        elif cid in (0x20, 0x21) and ctype == 0xCE and _need(b, i, 18 if co2 else 15):
            i += 18 if co2 else 15                                 # history record – skipped
        elif (n := _am30xl_cfg_len(cid, ctype, b, i, co2)) is not None:
            i += n                                                 # config reply – skipped
        else:
            break
    if errors:
        out["sensor_error"] = ", ".join(f"{k}: {v}" for k, v in errors.items())
    elif any(k in out for k in ("temperature", "humidity", "co2", "light_level", "illuminance_lux")):
        out["sensor_error"] = "OK"
    return out


# --------------------------------------------------------------------------
# DS3604 e-ink display (IPSO channel format). Telemetry: battery, button presses, current template.
# Display content / template config / update results are skipped.
# --------------------------------------------------------------------------
_DS3604_BUTTON = {0: "single_click", 1: "double_click", 2: "short_press", 3: "long_press"}
_DS3604_CFG = {0x03: 2, 0x10: 1, 0x25: 1, 0x27: 1, 0x28: 1, 0x3E: 1, 0x3D: 1, 0x66: 1, 0x82: 1, 0x89: 5,
               0x90: 1}


def decode_ds3604(b: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        if cid == 0xFF and ctype == 0x09 and _need(b, i, 2):
            out["hardware_version"] = _hw_version_dec(b, i)
            i += 2
        elif cid == 0xFF and ctype in (0x01, 0x0A, 0xFF, 0x16, 0x0F, 0xFE, 0x0B) and \
                (n := _decode_common(cid, ctype, b, i, out)) is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0xFF and ctype == 0x2E and _need(b, i, 1):
            event = _DS3604_BUTTON.get(b[i], "unknown")
            out["button_event"] = event
            if event != "unknown":
                out.setdefault("button_events", []).append(("button", event))
            i += 1
        elif cid in (0xFE, 0xFF) and ctype == 0x73 and _need(b, i, 1):
            out["current_template_id"] = b[i] + 1
            i += 1
        elif cid == 0xFB and ctype == 0x01 and _need(b, i, 1):       # block content (text / QR code)
            block = b[i] & 0x3F
            i += 1
            if block <= 10:
                if not _need(b, i, 1) or not _need(b, i + 1, b[i]):
                    break
                i += 1 + b[i]
        elif cid == 0xFA and ctype in (0x01, 0x02, 0x03) and _need(b, i, 2):   # update results
            i += 2
        elif cid in (0xFE, 0xFF) and ctype in _DS3604_CFG and _need(b, i, _DS3604_CFG[ctype]):
            i += _DS3604_CFG[ctype]
        else:
            break  # image data / template config / unknown – stop safely
    return out


# --------------------------------------------------------------------------
# EM300-CL / -MLD, EM310 / EM320, EM410 / EM411 ranges – checked against Milesight-IoT/SensorDecoders (tools/checks/em.py)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# EM range additions (EM300-CL / EM300-MLD / EM310-TILT / EM320-TILT / EM310-UDL /
# EM320-TH v2 / EM410-RDL / EM411-RDL).
# Checked against Milesight-IoT/SensorDecoders (em-series).
# Not here because an existing decoder already handles the format:
#   EM300-DI-HALL -> decode_em300 (same channels as EM300-DI; pulse_count, input_05, water ...)
#   EM320-TH (v1) -> decode_em300 (battery / temperature / humidity, same as EM300-TH)
# --------------------------------------------------------------------------
_EM300_CL_LIQUID = {0: "uncalibrated", 1: "full", 2: "critical", 255: "error"}
_EM300_CL_ALARM = {0: ("critical_liquid_level_alarm_release", False), 1: ("critical_liquid_level_alarm", True)}


def _em300_cl_liquid(out: dict, code: int) -> None:
    out["liquid"] = _EM300_CL_LIQUID.get(code, "unknown")
    if code in (1, 2):
        out["liquid_critical"] = code == 2
    out["sensor_error"] = "Liquid: error" if code == 255 else "OK"


def decode_em300_cl(b: bytes) -> dict[str, Any]:
    """EM300-CL capacitive liquid level switch (full / critical level)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0xED and _need(b, i, 1):
            _em300_cl_liquid(out, b[i])
            i += 1
        elif cid == 0x83 and ctype == 0xED and _need(b, i, 2):
            _em300_cl_liquid(out, b[i])
            _ts_alarm(out, "liquid", b[i + 1], _EM300_CL_ALARM)
            i += 2
        elif cid == 0x04 and ctype == 0xEE and _need(b, i, 1):
            out["calibration_result"] = {0: "failed", 1: "success"}.get(b[i], "unknown")
            i += 1
        else:
            break
    return out


def decode_em300_mld(b: bytes) -> dict[str, Any]:
    """EM300-MLD membrane leak sensor: EM300 format, 0x05/0x00 (0x06/0x00 per README) = leak."""
    out = decode_em300(b)
    for src in ("input_05", "magnet_status"):
        if src in out:
            out["leak"] = out.pop(src)
    return out


def _tilt_out(out: dict, angles: tuple, flags: tuple) -> None:
    for axis, angle, flag in zip("xyz", angles, flags):
        out[f"angle_{axis}"] = angle
        out[f"angle_{axis}_alarm"] = bool(flag)
    out["tilt"] = any(flags)


def _decode_tilt(b: bytes, em320: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif not em320 and cid == 0x03 and ctype == 0xCF and _need(b, i, 7):
            # int16/100 per axis + status byte (bit0..2 = x/y/z threshold alarm)
            _tilt_out(out, tuple(_i16le(b, i + 2 * k) / 100 for k in range(3)),
                      tuple(b[i + 6] >> k & 1 for k in range(3)))
            i += 7
        elif em320 and cid == 0x03 and ctype == 0xD4 and _need(b, i, 6):
            # per axis int16: bits 15..1 = angle * 100, bit 0 = threshold alarm
            _tilt_out(out, tuple((_i16le(b, i + 2 * k) >> 1) / 100 for k in range(3)),
                      tuple(b[i + 2 * k] & 1 for k in range(3)))
            i += 6
        else:
            break
    return out


def decode_em310_tilt(b: bytes) -> dict[str, Any]:
    return _decode_tilt(b, em320=False)


def decode_em320_tilt(b: bytes) -> dict[str, Any]:
    return _decode_tilt(b, em320=True)


def decode_em310_udl(b: bytes) -> dict[str, Any]:
    """EM310-UDL ultrasonic distance: distance 0x03/0x82 (mm), position 0x04/0x00."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x82 and _need(b, i, 2):
            out["distance"] = _u16le(b, i)
            i += 2
        elif cid == 0x04 and ctype == 0x00 and _need(b, i, 1):
            out["position"] = {0: "normal", 1: "tilt"}.get(b[i], "unknown")
            out["tilted"] = b[i] == 1
            i += 1
        else:
            break
    return out


# EM320-TH v2 -------------------------------------------------------------------
_EM320_ALARM = {
    1: ("below_threshold_alarm", True), 2: ("above_threshold_alarm", True),
    3: ("between_threshold_alarm", True), 4: ("outside_threshold_alarm", True),
    6: ("below_threshold_alarm_release", False), 7: ("above_threshold_alarm_release", False),
    8: ("between_threshold_alarm_release", False), 9: ("outside_threshold_alarm_release", False),
}
_EM320_TEMP_ERR = {1: "collection error", 2: "lower range error", 3: "over range error"}
_EM320_STORAGE = {1: "sufficient", 2: "less than 10 percent", 3: "full", 4: "overwritten"}
# configuration echoes on 0xF9 (skipped): type -> length
_EM320_F9_SKIP = {0xC9: 1, 0x39: 2, 0x0B: 7, 0x0C: 4, 0xD9: 1, 0x69: 1, 0x66: 1, 0x63: 4}


def _em320_err(out: dict, key: str, text: str) -> None:
    out.pop(key, None)
    out[f"{key}_error"] = text
    out["sensor_error"] = f"{key.capitalize()}: {text}"


def decode_em320_th_v2(b: bytes) -> dict[str, Any]:
    """EM320-TH (v2 firmware): 0.1 % humidity, sensor-error markers, threshold/mutation alarms."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x67 and _need(b, i, 2):
            raw = _u16le(b, i)
            if raw in (0x8001, 0x8002, 0x8003):
                _em320_err(out, "temperature", _EM320_TEMP_ERR[raw - 0x8000])
            else:
                out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x04 and ctype == 0x9A and _need(b, i, 2):
            raw = _u16le(b, i)
            if raw == 0xFFFF:
                _em320_err(out, "humidity", "collection error")
            else:
                out["humidity"] = raw / 10
            i += 2
        elif cid == 0x04 and ctype == 0x68 and _need(b, i, 1):
            if b[i] == 0xFF:
                _em320_err(out, "humidity", "collection error")
            else:
                out["humidity"] = b[i] / 2
            i += 1
        elif cid == 0x05 and ctype == 0x6B and _need(b, i, 1):
            out["trigger_type"] = {1: "external trigger"}.get(b[i], "unknown")
            i += 1
        elif cid == 0x05 and ctype == 0x9C and _need(b, i, 1):
            out["storage_status"] = _EM320_STORAGE.get(b[i], "unknown")
            i += 1
        elif cid == 0x83 and ctype == 0x67 and _need(b, i, 3):
            out["temperature"] = _i16le(b, i) / 10
            _ts_alarm(out, "temperature", b[i + 2], _EM320_ALARM)
            i += 3
        elif cid == 0x93 and ctype == 0x67 and _need(b, i, 5):
            out["temperature"] = _i16le(b, i) / 10
            out["temperature_change"] = _i16le(b, i + 2) / 10
            if b[i + 4] == 0:
                _ts_alarm(out, "temperature", 0, {0: ("mutation_alarm", None)})
            i += 5
        elif cid == 0x84 and ctype == 0x9A and _need(b, i, 3):
            out["humidity"] = _i16le(b, i) / 10
            _ts_alarm(out, "humidity", b[i + 2], _EM320_ALARM)
            i += 3
        elif cid == 0x84 and ctype == 0x68 and _need(b, i, 2):
            out["humidity"] = b[i] / 2
            _ts_alarm(out, "humidity", b[i + 1], _EM320_ALARM)
            i += 2
        elif cid == 0x94 and ctype == 0x9A and _need(b, i, 5):
            out["humidity"] = _i16le(b, i) / 10
            out["humidity_change"] = _i16le(b, i + 2) / 10
            if b[i + 4] == 0:
                _ts_alarm(out, "humidity", 0, {0: ("mutation_alarm", None)})
            i += 5
        elif cid == 0x94 and ctype == 0x68 and _need(b, i, 3):
            out["humidity"] = b[i] / 2
            out["humidity_change"] = b[i + 1] / 2
            if b[i + 2] == 0:
                _ts_alarm(out, "humidity", 0, {0: ("mutation_alarm", None)})
            i += 3
        elif cid == 0xB3 and ctype == 0x67 and _need(b, i, 2):
            _em320_err(out, "temperature", _EM320_TEMP_ERR.get(b[i], "unknown"))
            i += 2
        elif cid == 0xB4 and ctype in (0x68, 0x9A) and _need(b, i, 2):
            _em320_err(out, "humidity", {1: "collection error"}.get(b[i], "unknown"))
            i += 2
        elif cid == 0xF9 and ctype in _EM320_F9_SKIP and _need(b, i, _EM320_F9_SKIP[ctype]):
            i += _EM320_F9_SKIP[ctype]
        else:
            break   # history (0x20 0xCE), downlink replies, unknown – stop safely
    if "sensor_error" not in out and ("temperature" in out or "humidity" in out):
        out["sensor_error"] = "OK"
    return out


# EM410-RDL / EM411-RDL radar distance --------------------------------------------
_RDL_ALARM = {0: ("threshold_alarm_release", False), 1: ("threshold_alarm", True), 2: ("mutation_alarm", None)}
_RDL_EXCEPTION = {0: ("blind_spot_alarm_release", False), 1: ("blind_spot_alarm", True),
                  2: ("no_target", None), 3: ("sensor_exception", None)}
_RDL_SENTINEL = {0xFFFD: "no target", 0xFFFE: "disabled", 0xFFFF: "sensor exception"}


def _rdl_distance(out: dict, b: bytes, i: int) -> None:
    raw = _u16le(b, i)
    if raw in _RDL_SENTINEL:
        out.pop("distance", None)
        out["sensor_error"] = f"Distance: {_RDL_SENTINEL[raw]}"
    else:
        out["distance"] = _i16le(b, i)
        out["sensor_error"] = "OK"


def decode_em410_rdl(b: bytes) -> dict[str, Any]:
    """EM410-RDL / EM411-RDL radar distance (mm) with threshold, mutation and blind-spot alarms."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x03 and ctype == 0x67 and _need(b, i, 2):
            out["temperature"] = _i16le(b, i) / 10
            i += 2
        elif cid == 0x04 and ctype == 0x82 and _need(b, i, 2):
            _rdl_distance(out, b, i)
            i += 2
        elif cid == 0x05 and ctype == 0x00 and _need(b, i, 1):
            out["position"] = {0: "normal", 1: "tilt"}.get(b[i], "unknown")
            out["tilted"] = b[i] == 1
            i += 1
        elif cid == 0x06 and ctype == 0xC7 and _need(b, i, 2):
            out["radar_signal_rssi"] = _i16le(b, i) / 100
            i += 2
        elif cid == 0x84 and ctype == 0x82 and _need(b, i, 3):
            _rdl_distance(out, b, i)
            _ts_alarm(out, "distance", b[i + 2], _RDL_ALARM)
            i += 3
        elif cid == 0x94 and ctype == 0x82 and _need(b, i, 5):
            _rdl_distance(out, b, i)
            out["distance_mutation"] = _i16le(b, i + 2)
            _ts_alarm(out, "distance", b[i + 4], _RDL_ALARM)
            i += 5
        elif cid == 0xB4 and ctype == 0x82 and _need(b, i, 3):
            code = b[i + 2]
            _ts_alarm(out, "distance_exception", code, _RDL_EXCEPTION)
            if code in (2, 3):
                out["sensor_error"] = "Distance: " + ("no target" if code == 2 else "sensor exception")
            i += 3
        else:
            break   # history (0x20 0xCE), downlink replies (0xFE/0xFF/0xF8/0xF9), unknown
    return out


def decode_em411_rdl(b: bytes) -> dict[str, Any]:
    """EM411-RDL: identical payload format to EM410-RDL."""
    return decode_em410_rdl(b)


# --------------------------------------------------------------------------
# VS13x / VS330 / VS35x / VS360 people counters – checked against Milesight-IoT/SensorDecoders (tools/checks/vs.py)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# VS132 / VS133 / VS135 / VS330 / VS350 / VS351 / VS360
# Checked against Milesight-IoT/SensorDecoders (vs-series).
# --------------------------------------------------------------------------
def _vs_skip(cid: int, ctype: int, b: bytes, i: int, std: dict, ext: dict | None = None) -> int | None:
    """Length of a configuration (downlink) response we do not decode, or None if unknown.

    std: {ctype: length} for 0xFF / 0xFE responses, ext: {ctype: length} for 0xF8 / 0xF9
    responses (0xF8 carries one extra result byte).
    """
    if cid in (0xFF, 0xFE):
        n = std.get(ctype)
    elif ext is not None and cid in (0xF8, 0xF9):
        n = ext.get(ctype)
        if n is not None and cid == 0xF8:
            n += 1
    else:
        return None
    return n if n is not None and _need(b, i, n) else None


def _vs_hw_version(cid: int, ctype: int, b: bytes, i: int, out: dict) -> int | None:
    """0xFF 0x09 as the newer official decoders print it: major in hex, minor (high nibble) in decimal.

    (_decode_common prints the minor in hex, which differs for minor >= 10.)"""
    if cid == 0xFF and ctype == 0x09 and _need(b, i, 2):
        out["hardware_version"] = f"v{b[i]:x}.{b[i + 1] >> 4}"
        return 2
    return None


# VS132 ToF people counter ---------------------------------------------------
_VS132_SKIP = {0x03: 2, 0x04: 1, 0x10: 1, 0x40: 1, 0x42: 1, 0x43: 1, 0x51: 1}


def decode_vs132(b: bytes) -> dict[str, Any]:
    """VS132 3D ToF people counter (single line, in / out)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        if cid == 0xFF and ctype == 0x09 and _need(b, i, 2):           # VS132 prints "a.b" (decimal)
            out["hardware_version"] = f"{b[i]}.{b[i + 1]}"
            i += 2
            continue
        n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x03 and ctype == 0xD2 and _need(b, i, 4):
            out["people_total_in"] = _u32le(b, i)
            i += 4
        elif cid == 0x04 and ctype == 0xD2 and _need(b, i, 4):
            out["people_total_out"] = _u32le(b, i)
            i += 4
        elif cid == 0x05 and ctype == 0xCC and _need(b, i, 4):
            out["people_in"] = _u16le(b, i)
            out["people_out"] = _u16le(b, i + 2)
            i += 4
        elif (n := _vs_skip(cid, ctype, b, i, _VS132_SKIP)) is not None:
            i += n
        else:
            break
    return out


# VS133 / VS135 AI ToF people counter (4 lines, 4 regions, child counting) ---
_VS133_ALARM = {0: ("alarm_released", False), 1: ("alarm_triggered", True)}
_VS133_SKIP = {0x03: 2, 0x04: 1, 0x10: 1, 0x11: 4, 0x27: 1, 0x40: 1, 0x42: 1, 0x43: 1, 0x44: 1,
               0x51: 1, 0x68: 1, 0x69: 1, 0x6A: 3, 0x6D: 1}
_VS133_SKIP_EXT = {0x84: 3, 0x85: 2, 0x86: 1, 0x87: 1, 0x88: 2}
_VS133_HISTORY_9 = set(range(0x03, 0x10)) | set(range(0x11, 0x1E))
_VS133_HISTORY_8 = {0x10, 0x20, 0x1E, 0x3C}


def decode_vs133(b: bytes) -> dict[str, Any]:
    """VS133 / VS135 AI ToF people counter (identical payload format)."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        if cid == 0xFF and ctype == 0x09 and _need(b, i, 2):
            out["hardware_version"] = f"v{b[i]}.{b[i + 1]}"
            i += 2
        elif cid == 0xFF and ctype == 0x1F and _need(b, i, 4):
            out["firmware_version"] = "v" + ".".join(str(x) for x in b[i:i + 4])
            i += 4
        elif cid == 0xFF and ctype == 0xD4 and _need(b, i, 5):
            out["device_version"] = f"V{b[i]}_{b[i + 1]}.{b[i + 2]}.{b[i + 3]}.{b[i + 4]}"
            i += 5
        elif (n := _decode_common(cid, ctype, b, i, out)) is not None:
            i += n
        elif ctype == 0xD2 and (0x03 <= cid <= 0x0D or 0x11 <= cid <= 0x1B) and \
                ((cid - 0x0E) if cid >= 0x11 else cid) % 3 != 2 and _need(b, i, 4):
            # total in: 0x03/06/09/0C, total out: 0x04/07/0A/0D, child: +0x0E
            child = cid >= 0x11
            base = cid - (0x0E if child else 0)
            line = (base - 0x03) // 3 + 1
            direction = "in" if base % 3 == 0 else "out"
            key = f"line_{line}_child_total_{direction}" if child else f"line_{line}_total_{direction}"
            out[key] = _u32le(b, i)
            if line == 1 and not child:
                out[f"people_total_{direction}"] = out[key]
            i += 4
        elif ctype == 0xCC and cid in (0x05, 0x08, 0x0B, 0x0E, 0x13, 0x16, 0x19, 0x1C) and _need(b, i, 4):
            child = cid >= 0x13
            line = (cid - (0x13 if child else 0x05)) // 3 + 1
            pre = f"line_{line}_child" if child else f"line_{line}"
            out[f"{pre}_in"] = _u16le(b, i)
            out[f"{pre}_out"] = _u16le(b, i + 2)
            if line == 1 and not child:
                out["people_in"], out["people_out"] = out[f"{pre}_in"], out[f"{pre}_out"]
            i += 4
        elif cid in (0x0F, 0x1D) and ctype == 0xE3 and _need(b, i, 4):
            suffix = "child_count" if cid == 0x1D else "count"
            for r in range(4):
                out[f"region_{r + 1}_{suffix}"] = b[i + r]
            i += 4
        elif cid in (0x10, 0x1E) and ctype == 0xE4 and _need(b, i, 5):
            pre = f"region_{b[i]}_child" if cid == 0x1E else f"region_{b[i]}"
            out[f"{pre}_dwell_time_avg"] = _u16le(b, i + 1)
            out[f"{pre}_dwell_time_max"] = _u16le(b, i + 3)
            i += 5
        elif cid == 0x50 and ctype == 0xFC and _need(b, i, 3):
            node = "master" if b[i + 1] == 0 else f"node_{b[i + 1]}"
            _ts_alarm(out, f"{node}_occlusion", b[i + 2], _VS133_ALARM)
            i += 3
        elif cid == 0x20 and ctype == 0xCE and _need(b, i, 5):         # history record: skipped
            dtype = b[i + 4]
            n = 9 if dtype in _VS133_HISTORY_9 else 8 if dtype in _VS133_HISTORY_8 else 0
            if not _need(b, i, n):
                break
            i += n
        elif (n := _vs_skip(cid, ctype, b, i, _VS133_SKIP, _VS133_SKIP_EXT)) is not None:
            i += n
        else:
            break
    return out


def decode_vs135(b: bytes) -> dict[str, Any]:
    return decode_vs133(b)


# VS330 bathroom occupancy (ToF distance) -----------------------------------
_VS330_SKIP = {0x02: 2, 0x03: 2, 0x10: 1, 0x70: 2, 0x71: 1, 0x72: 2, 0x7A: 3}


def decode_vs330(b: bytes) -> dict[str, Any]:
    """VS330 bathroom occupancy sensor."""
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _vs_hw_version(cid, ctype, b, i, out)
        if n is None:
            n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]
            i += 1
        elif cid == 0x02 and ctype == 0x82 and _need(b, i, 2):
            out["distance"] = _u16le(b, i)
            i += 2
        elif cid == 0x03 and ctype == 0x8E and _need(b, i, 1):
            out["occupancy"] = 1 if b[i] == 1 else 0
            i += 1
        elif cid == 0x04 and ctype == 0x8E and _need(b, i, 1):
            out["calibration_status"] = _map({0: "failed", 1: "success"}, b[i])
            i += 1
        elif (n := _vs_skip(cid, ctype, b, i, _VS330_SKIP)) is not None:
            i += n
        else:
            break
    return out


# VS350 / VS351 / VS360 people counters --------------------------------------
_VS35X_ALARM = {0: ("threshold_alarm_release", False), 1: ("threshold_alarm", True),
                3: ("high_temperature_alarm", True), 4: ("high_temperature_alarm_release", False)}
_VS360_ALARM = {1: ("threshold_alarm", True)}
_VS360_EVENT = {0: "counting_anomaly", 1: "node_device_without_response", 2: "devices_misaligned"}
_VS360_EVENT_STATUS = {0: ("alarm_release", False), 1: ("alarm", True)}
_VS351_POWER = {0: "battery supply", 1: "external power supply", 2: "battery charging"}
_VS350_SKIP = {0x06: 9, 0x10: 1, 0x28: 1, 0x35: 8, 0x4A: 1, 0x68: 1, 0x69: 1, 0x6A: 3, 0x6B: 1, 0x6D: 1,
               0x84: 1, 0x8E: 3, 0x96: 8, 0xA6: 1, 0xA7: 2, 0xA8: 1, 0xA9: 1, 0xAA: 1, 0xAB: 3, 0xBD: 2,
               0xEF: 3, 0xAC: 5, 0xAD: 1}
_VS351_SKIP = {0x04: 1, 0x05: 3, 0x06: 9, 0x10: 1, 0x27: 1, 0x28: 1, 0x35: 8, 0x40: 1, 0x41: 1, 0x68: 1,
               0x69: 1, 0x6A: 3, 0x75: 6, 0x77: 2, 0x84: 1, 0x8F: 2, 0x8E: 3, 0x96: 8, 0x97: 1, 0xA6: 1,
               0xA8: 1, 0xA9: 1, 0xAA: 1, 0xAB: 3, 0xEC: 1, 0xED: 3}
_VS351_SKIP_EXT = {0x10: 1, 0x85: 2, 0x86: 1, 0x87: 1, 0x8B: 1, 0x8C: 1, 0x8D: 4, 0xA2: 1, 0xA3: 1}
_VS360_SKIP = {0x06: 9, 0x10: 1, 0x28: 1, 0x35: 8, 0x4A: 1, 0x68: 1, 0x69: 1, 0x6A: 3, 0x6D: 1, 0x75: 6,
               0x84: 1, 0x8E: 3, 0x96: 8, 0xA6: 1, 0xA9: 1, 0xBD: 2, 0xA8: 1, 0xED: 3, 0xFC: 1, 0xFD: 1}
_VS_EXT_REPORT_TYPE = {0x10: 1}


def _decode_vs35x(b: bytes, model: str) -> dict[str, Any]:
    if model == "vs350":
        skip, ext, alarms = _VS350_SKIP, _VS_EXT_REPORT_TYPE, _VS35X_ALARM
    elif model == "vs351":
        skip, ext, alarms = _VS351_SKIP, _VS351_SKIP_EXT, _VS35X_ALARM
    else:
        skip, ext, alarms = _VS360_SKIP, _VS_EXT_REPORT_TYPE, _VS360_ALARM
    out: dict[str, Any] = {}
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        n = _vs_hw_version(cid, ctype, b, i, out)
        if n is None:
            n = _decode_common(cid, ctype, b, i, out)
        if n is not None:
            i += n
        elif cid == 0x01 and ctype == 0x75 and _need(b, i, 1):
            out["battery"] = b[i]                      # VS360: main unit battery
            i += 1
        elif model == "vs360" and cid == 0x02 and ctype == 0x75 and _need(b, i, 1):
            out["battery_node"] = b[i]
            i += 1
        elif model == "vs351" and cid == 0xFF and ctype == 0xCC and _need(b, i, 1):
            out["power_status"] = _map(_VS351_POWER, b[i])
            i += 1
        elif model != "vs360" and cid in (0x03, 0x83) and ctype == 0x67 and _need(b, i, 3 if cid == 0x83 else 2):
            out["temperature"] = _i16le(b, i) / 10
            if cid == 0x83:
                _ts_alarm(out, "temperature", b[i + 2], alarms)
            i += 3 if cid == 0x83 else 2
        elif model == "vs360" and cid == 0x03 and ctype == 0xF4 and _need(b, i, 2):
            _ts_alarm(out, _map(_VS360_EVENT, b[i]), b[i + 1], _VS360_EVENT_STATUS)
            i += 2
        elif cid in (0x04, 0x84) and ctype == 0xCC and _need(b, i, 5 if cid == 0x84 else 4):
            out["people_total_in"] = _u16le(b, i)
            out["people_total_out"] = _u16le(b, i + 2)
            if cid == 0x84:
                _ts_alarm(out, "total_count", b[i + 4], alarms)
            i += 5 if cid == 0x84 else 4
        elif cid in (0x05, 0x85) and ctype == 0xCC and _need(b, i, 5 if cid == 0x85 else 4):
            out["people_in"] = _u16le(b, i)
            out["people_out"] = _u16le(b, i + 2)
            if cid == 0x85:
                _ts_alarm(out, "period_count", b[i + 4], alarms)
            i += 5 if cid == 0x85 else 4
        elif cid == 0x0A and ctype == 0xEF and _need(b, i, 4):
            out["device_timestamp"] = _u32le(b, i)
            i += 4
        elif model == "vs350" and cid == 0x81 and ctype == 0xEE and _need(b, i, 1):
            out["current_sensitivity"] = b[i]
            i += 1
        elif cid == 0x20 and ctype == 0xCE and _need(b, i, 5):         # history record: skipped
            n = {0: 9, 1: 13}.get(b[i + 4], 0)
            if not _need(b, i, n):
                break
            i += n
        elif (n := _vs_skip(cid, ctype, b, i, skip, ext)) is not None:
            i += n
        else:
            break
    return out


def decode_vs350(b: bytes) -> dict[str, Any]:
    """VS350 passage people counter (radar, with temperature)."""
    return _decode_vs35x(b, "vs350")


def decode_vs351(b: bytes) -> dict[str, Any]:
    """VS351 passage people counter (VS350 format + power status, no sensitivity channel)."""
    return _decode_vs35x(b, "vs351")


def decode_vs360(b: bytes) -> dict[str, Any]:
    """VS360 passage people counter (main + node unit)."""
    return _decode_vs35x(b, "vs360")


# --------------------------------------------------------------------------
# Generic downlinks (reboot, intervals, time, status, outputs) from downlinks.json.
# Each template was checked against Milesight's official encoders (tools/checks/dl_*.py).
# --------------------------------------------------------------------------
_TEMPLATE_FMT = {"u8": "<B", "u16le": "<H", "u16be": ">H", "u32le": "<I", "i16le": "<h", "i32le": "<i"}


def encode_template(spec: dict, value: float | None = None) -> bytes:
    """{"hex": ...} -> fixed bytes; {"prefix", "value", "scale", "suffix", "min", "max"} -> prefix + value + suffix."""
    if "hex" in spec:
        return bytes.fromhex(spec["hex"])
    if value is None:
        raise ValueError("value required")
    lo, hi = spec.get("min"), spec.get("max")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ValueError(f"value {value} outside {lo}..{hi}")
    raw = round(value * spec.get("scale", 1))
    return bytes.fromhex(spec["prefix"]) + struct.pack(_TEMPLATE_FMT[spec["value"]], raw) + bytes.fromhex(spec.get("suffix", ""))


# --------------------------------------------------------------------------
# Stored history records (g1) – checked against the official decoders (tools/checks/hist_g1.py)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Stored history (data logging / retransmission) – group g1
# EM300 / EM320 / EM410 / EM500 / TS / AM100 / AM300 / AM300L / AT101 / CTH01
# Checked against Milesight-IoT/SensorDecoders (history arrays of the official decoders).
# Each history_<family>(b) returns [(unix_timestamp, {our_key: value, ...}), ...] in payload order.
# Values use the same keys as the live decoders; text-only fields (event / report type) are dropped,
# sentinel / error readings are left out of the record. Empty records are not returned.
# Non-history channels in the same payload are skipped with the live decoder's channel lengths;
# configuration replies or unknown data stop the scan.
# --------------------------------------------------------------------------
def _hist_fixed(table: dict) -> Callable[[int, int, bytes, int], int | None]:
    return lambda cid, ctype, b, i: table.get((cid, ctype))


def _hist_scan(b: bytes, recs: dict, skip: Callable[[int, int, bytes, int], int | None] | None) -> list[tuple[int, dict]]:
    """Channel-format scan. recs: {(cid, ctype): (record length incl. 4-byte timestamp, parser(b, i) -> dict)}."""
    b = bytes(b)
    res: list[tuple[int, dict]] = []
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        rec = recs.get((cid, ctype))
        if rec is not None:
            size, parse = rec
            if not _need(b, i, size):
                break
            vals = parse(b, i)
            if vals:
                res.append((_u32le(b, i), vals))
            i += size
            continue
        n = _decode_common(cid, ctype, b, i, {})
        if n is None and skip is not None:
            n = skip(cid, ctype, b, i)
        if n is None or not _need(b, i, n):
            break
        i += n
    return res


def _hist_mag(v: int) -> int | None:
    """0 = close, 1 = open (official readMagnetStatus); anything else is unknown."""
    return v if v in (0, 1) else None


def _hist_put(out: dict, key: str, v: Any) -> None:
    if v is not None:
        out[key] = v


# ---- live channel lengths used to skip non-history data ---------------------
_HIST_SKIP_EM500 = _hist_fixed({
    (0xFF, 0x1B): 5, (0x01, 0x75): 1, (0x03, 0x67): 2, (0x83, 0xD7): 5, (0x04, 0x68): 1, (0x04, 0xCA): 2,
    (0x05, 0x7D): 2, (0x06, 0x73): 2, (0x03, 0x7B): 2, (0x03, 0x94): 4, (0x05, 0x7F): 2, (0x03, 0x77): 2,
    (0x03, 0x82): 2, (0x83, 0xE9): 5})
_HIST_SKIP_EM300 = _hist_fixed({
    (0x01, 0x75): 1, (0x03, 0x67): 2, (0x04, 0x68): 1, (0x06, 0x00): 1, (0x05, 0x00): 1, (0x85, 0x00): 2,
    (0x05, 0xC8): 4, (0x05, 0xE1): 8, (0x85, 0xE1): 9})
_HIST_SKIP_AM300 = _hist_fixed({
    (0x01, 0x75): 1, (0x03, 0x67): 2, (0x04, 0x68): 1, (0x05, 0x00): 1, (0x06, 0xCB): 1, (0x07, 0x7D): 2,
    (0x08, 0x7D): 2, (0x08, 0xE6): 2, (0x09, 0x73): 2, (0x0A, 0x7D): 2, (0x0B, 0x7D): 2, (0x0C, 0x7D): 2,
    (0x0D, 0x7D): 2, (0x0E, 0x01): 1, (0x0F, 0x7D): 2})
_HIST_SKIP_RDL = _hist_fixed({
    (0x01, 0x75): 1, (0x03, 0x67): 2, (0x04, 0x82): 2, (0x05, 0x00): 1, (0x06, 0xC7): 2, (0x84, 0x82): 3,
    (0x94, 0x82): 5, (0xB4, 0x82): 3})
_HIST_SKIP_AT101 = _hist_fixed({
    (0x01, 0x75): 1, (0x03, 0x67): 2, (0x04, 0x88): 9, (0x84, 0x88): 9, (0x05, 0x00): 1, (0x06, 0xD9): 9,
    (0x07, 0x00): 1, (0x83, 0x67): 3})
_HIST_EM320V2_LIVE = {
    (0x01, 0x75): 1, (0x03, 0x67): 2, (0x04, 0x9A): 2, (0x04, 0x68): 1, (0x05, 0x6B): 1, (0x05, 0x9C): 1,
    (0x83, 0x67): 3, (0x93, 0x67): 5, (0x84, 0x9A): 3, (0x84, 0x68): 2, (0x94, 0x9A): 5, (0x94, 0x68): 3,
    (0xB3, 0x67): 2, (0xB4, 0x68): 2, (0xB4, 0x9A): 2}


def _hist_skip_em320v2(cid: int, ctype: int, b: bytes, i: int) -> int | None:
    if cid == 0xF9:
        return _EM320_F9_SKIP.get(ctype)
    return _HIST_EM320V2_LIVE.get((cid, ctype))


def _hist_skip_ts(cid: int, ctype: int, b: bytes, i: int) -> int | None:
    """Same channel lengths as _decode_ts (TS101 / TS201 / TS301 / TS302)."""
    if cid == 0xFF and ctype == 0xA0:
        return 9
    if cid == 0x01 and ctype == 0x75:
        return 1
    hi, lo = cid & 0xF0, cid & 0x0F
    if lo not in (3, 4):
        return None
    size = {0x67: 2, 0x9A: 2, 0x68: 1}.get(ctype)
    if hi == 0x00:
        return 1 if ctype == 0x00 else size
    if hi == 0xB0:
        return 1 if size else None
    if hi == 0x80:
        return size + 1 if size else None
    if hi == 0x90:
        return 5 if ctype == 0xD7 else (size + 2 if ctype == 0x68 else (size + 3 if size else None))
    return None


def _hist_skip_am10x(co2: bool) -> Callable[[int, int, bytes, int], int | None]:
    table = {(0x01, 0x75): 1, (0x03, 0x67): 2, (0x04, 0x68): 1, (0xFF, 0x09): 2, (0xFF, 0x18): 2}
    if co2:
        table[(0x07, 0x7D)] = 2

    def skip(cid: int, ctype: int, b: bytes, i: int) -> int | None:
        n = table.get((cid, ctype))
        if n is None and cid in (0xFE, 0xFF):
            n = _am10x_config_len(ctype, b, i, co2)
        return n
    return skip


def _hist_skip_am30xl(co2: bool) -> Callable[[int, int, bytes, int], int | None]:
    table = {(0xFF, 0x0B): 1, (0xFF, 0x01): 1, (0xFF, 0x09): 2, (0x01, 0x75): 1, (0x03, 0x67): 2,
             (0x04, 0x68): 1, (0x05, 0x9F): 2, (0x05, 0x00): 1, (0x06, 0xCB): 1, (0x06, 0x9D): 2,
             (0x83, 0x67): 3, (0x86, 0x9D): 3}
    if co2:
        table.update({(0x07, 0x7D): 2, (0x87, 0x7D): 3})
    for key in _AM30XL_ANOMALY:
        if co2 or key[0] != 0xB7:
            table[key] = 1

    def skip(cid: int, ctype: int, b: bytes, i: int) -> int | None:
        n = table.get((cid, ctype))
        return _am30xl_cfg_len(cid, ctype, b, i, co2) if n is None else n
    return skip


# ---- EM500 range (0x20 0xCE) -------------------------------------------------
def _hist_em500_err(raw: int) -> bool:
    return raw in (0xFFFF, 0xFFFD)


def history_em500_co2(b: bytes) -> list[tuple[int, dict]]:
    """EM500-CO2: co2 (ppm), pressure (hPa), temperature, humidity."""
    return _hist_scan(b, {(0x20, 0xCE): (11, lambda b, i: {
        "co2": _u16le(b, i + 4), "pressure": _u16le(b, i + 6) / 10, "temperature": _i16le(b, i + 8) / 10,
        "humidity": b[i + 10] / 2})}, _HIST_SKIP_EM500)


def history_em500_lgt(b: bytes) -> list[tuple[int, dict]]:
    """EM500-LGT: illumination (lux)."""
    return _hist_scan(b, {(0x20, 0xCE): (8, lambda b, i: {"illumination": _u32le(b, i + 4)})}, _HIST_SKIP_EM500)


def history_em500_pp(b: bytes) -> list[tuple[int, dict]]:
    """EM500-PP: pipe pressure (kPa)."""
    return _hist_scan(b, {(0x20, 0xCE): (6, lambda b, i: {"pressure_kpa": _i16le(b, i + 4)})}, _HIST_SKIP_EM500)


def history_temperature6(b: bytes) -> list[tuple[int, dict]]:
    """EM500-PT100 / TS101: 6-byte record, temperature only."""
    return _hist_scan(b, {(0x20, 0xCE): (6, lambda b, i: {"temperature": _i16le(b, i + 4) / 10})},
                      lambda c, t, bb, i: _HIST_SKIP_EM500(c, t, bb, i) or _hist_skip_ts(c, t, bb, i))


def _hist_smtc(b: bytes, i: int) -> dict:
    out: dict[str, Any] = {}
    raw = _u16le(b, i + 4)
    if not _hist_em500_err(raw):
        out["electricity"] = raw
    raw = _u16le(b, i + 6)
    if not _hist_em500_err(raw):
        out["temperature"] = _i16le(b, i + 6) / 10
    raw = _u16le(b, i + 8)
    if not _hist_em500_err(raw):
        out["moisture"] = raw / 100
    return out


def history_em500_smtc(b: bytes) -> list[tuple[int, dict]]:
    """EM500-SMTC: electricity (µS/cm), temperature, moisture (%); 0xFFFF / 0xFFFD error readings dropped."""
    return _hist_scan(b, {(0x20, 0xCE): (10, _hist_smtc)}, _HIST_SKIP_EM500)


def history_em500_swl(b: bytes) -> list[tuple[int, dict]]:
    """EM500-SWL: depth (cm); 0xFFFF / 0xFFFD error readings dropped."""
    return _hist_scan(b, {(0x20, 0xCE): (6, lambda b, i: {} if _hist_em500_err(_u16le(b, i + 4))
                                          else {"depth": _u16le(b, i + 4)})}, _HIST_SKIP_EM500)


def history_em500_udl(b: bytes) -> list[tuple[int, dict]]:
    """EM500-UDL: distance (mm)."""
    return _hist_scan(b, {(0x20, 0xCE): (6, lambda b, i: {"distance": _u16le(b, i + 4)})}, _HIST_SKIP_EM500)


# ---- TS range (channel format) ------------------------------------------------
def _hist_ts201(b: bytes, i: int) -> dict:
    out: dict[str, Any] = {}
    sensor_type, event = b[i + 4], b[i + 8]
    if (event >> 6) & 0x03 == 0:                       # temperature sensor status normal
        out["temperature"] = _i16le(b, i + 5) / 10
    if sensor_type == 2 and (event >> 4) & 0x03 == 0:  # SHT4x: humidity too
        out["humidity"] = b[i + 7] / 2
    return out


def history_ts201(b: bytes) -> list[tuple[int, dict]]:
    """TS201 v2: temperature (+ humidity for the SHT4x probe); readings flagged as read error / out of range dropped."""
    return _hist_scan(b, {(0x20, 0xCE): (9, _hist_ts201)}, _hist_skip_ts)


def _hist_ts_v2_channel(b: bytes, i: int, sfx: str) -> dict:
    """TS301 / TS302 v2 record: mask, humidity (i16), temperature (i16). -999 = none, -1000/-1001 = magnet."""
    out: dict[str, Any] = {}
    for key, raw in (("temperature", _i16le(b, i + 7)), ("humidity", _i16le(b, i + 5))):
        if raw in (-1000, -1001):
            out[f"magnet_status{sfx}"] = 0 if raw == -1000 else 1
        elif raw not in (-999, -1002):
            out[f"{key}{sfx}"] = raw / 10
    return out


def history_ts301(b: bytes) -> list[tuple[int, dict]]:
    """TS301 (current firmware): temperature / humidity, or magnet_status (0 closed, 1 open) for a contact probe."""
    return _hist_scan(b, {(0x20, 0xCE): (9, lambda b, i: _hist_ts_v2_channel(b, i, ""))}, _hist_skip_ts)


def history_ts302(b: bytes) -> list[tuple[int, dict]]:
    """TS302 (current firmware): 0x20 = probe 1 (_1 keys), 0x21 = probe 2 (_2 keys)."""
    return _hist_scan(b, {(0x20, 0xCE): (9, lambda b, i: _hist_ts_v2_channel(b, i, "_1")),
                          (0x21, 0xCE): (9, lambda b, i: _hist_ts_v2_channel(b, i, "_2"))}, _hist_skip_ts)


def _hist_ts_v1_value(out: dict, b: bytes, j: int, mode: int, sfx: str) -> None:
    if 1 <= mode <= 4:
        out[f"temperature{sfx}"] = _i16le(b, j) / 10
    elif mode in (5, 6):
        _hist_put(out, f"magnet_status{sfx}", _hist_mag(_u16le(b, j)))


def _hist_ts301_v1(b: bytes, i: int) -> dict:
    out: dict[str, Any] = {}
    _hist_ts_v1_value(out, b, i + 5, b[i + 4] >> 4, "")
    return out


def _hist_ts302_v1(b: bytes, i: int) -> dict:
    out: dict[str, Any] = {}
    _hist_ts_v1_value(out, b, i + 5, b[i + 4] >> 4, "_1")
    _hist_ts_v1_value(out, b, i + 7, b[i + 4] & 0x0F, "_2")
    return out


def history_ts301_v1(b: bytes) -> list[tuple[int, dict]]:
    """TS301 (older firmware): temperature or magnet_status depending on the record's event nibble."""
    return _hist_scan(b, {(0x20, 0xCE): (9, _hist_ts301_v1)}, _hist_skip_ts)


def history_ts302_v1(b: bytes) -> list[tuple[int, dict]]:
    """TS302 (older firmware): two probes in one record (temperature_N or magnet_status_N)."""
    return _hist_scan(b, {(0x20, 0xCE): (9, _hist_ts302_v1)}, _hist_skip_ts)


# ---- command format: TS601 / TS602 and CTH01 (0xED <type> <u32 time> + ordinary commands) ----------
def _hist_values(d: dict) -> dict:
    return {k: v for k, v in d.items() if isinstance(v, (int, float)) and not k.startswith("_")}


def history_ts60x(b: bytes) -> list[tuple[int, dict]]:
    """TS601 / TS602: each 0xED record is followed by the normal commands (temperature, humidity, battery …)."""
    b = bytes(b)
    res: list[tuple[int, dict]] = []
    _, i = _parse_ts60x(b)
    while i + 6 <= len(b) and b[i] == 0xED:
        ts = _u32le(b, i + 2)
        out, n = _parse_ts60x(b[i + 6:])
        vals = _hist_values(out)
        if vals:
            res.append((ts, vals))
        i += 6 + n
    return res


def _cth01_next(b: bytes, i: int) -> int | None:
    """Index after the CTH01 command starting at b[i] (same lengths as _parse_cth01), None if truncated."""
    cmd = b[i]
    i += 1
    n = _wt_info(cmd, b, i, {}, extra=True)
    if n is not None:
        return i + n
    if cmd in (0x01, 0x02):
        n = 2
    elif cmd in (0x03, 0x04, 0x05, 0x06):
        n = {0x03: 24, 0x04: 6, 0x05: 36, 0x06: 6}[cmd]
    elif cmd == 0x07:
        if not _need(b, i, 1):
            return None
        n = 1 + sum(3 if b[i] >> g & 1 else 1 for g in range(4))
    elif cmd in _CTH_MASKED:
        if not _need(b, i, 1):
            return None
        n = 1 + sum(12 if b[i] >> g & 1 else 4 for g in range(2))
    elif 0x30 <= cmd <= 0x35:
        head = 2 if cmd in (0x31, 0x32, 0x33, 0x34) else 1
        if not _need(b, i, head):
            return None
        code = b[i + head - 1]
        with_value = {0x30: range(0x10, 0x18), 0x31: (1, 2, 4, *range(0x10, 0x18)), 0x32: (1, 2, 4, *range(0x10, 0x18)),
                      0x33: (0x12, 0x13), 0x34: (0x12, 0x13), 0x35: (0x12, 0x13)}[cmd]
        n = head + ((3 if cmd == 0x31 else 2) if code in with_value else 0)
    elif cmd == 0x36:
        n = 0
    elif cmd == 0x40:
        n = 1
    elif cmd == 0xCF:
        if not _need(b, i, 1):
            return None
        n = 2 if b[i] == 0xD8 and _need(b, i, 2) else 1
    elif cmd in _CTH_SKIP:
        skip = _CTH_SKIP[cmd]
        n = skip(b, i) if callable(skip) else skip
    else:
        n = 0                                   # unknown id: one byte, like the official decoder
    return i + n if _need(b, i, n) else None


def history_cth01(b: bytes) -> list[tuple[int, dict]]:
    """CTH01: each 0xED record is followed by ordinary measurement commands (current_ctN, voltage_lN, energy …)."""
    b = bytes(b)
    res: list[tuple[int, dict]] = []
    i = 0
    while i < len(b) and b[i] != 0xED:          # live part before the first record
        n = _cth01_next(b, i)
        if n is None:
            return res
        i = n
    while i + 6 <= len(b) and b[i] == 0xED:
        ts = _u32le(b, i + 2)
        j = i + 6
        while j < len(b) and b[j] != 0xED:
            n = _cth01_next(b, j)
            if n is None:
                j = len(b)
                break
            j = n
        vals = _hist_values(_parse_cth01(b[i + 6:j])[0])
        if vals:
            res.append((ts, vals))
        i = j
    return res


# ---- EM300 / EM320 range -------------------------------------------------------
def _hist_th(b: bytes, i: int) -> dict:
    return {"temperature": _i16le(b, i + 4) / 10, "humidity": b[i + 6] / 2}


def history_th7(b: bytes) -> list[tuple[int, dict]]:
    """EM320-TH (v1) / AM102 / AM102L: 7-byte record temperature + humidity."""
    return _hist_scan(b, {(0x20, 0xCE): (7, _hist_th)},
                      lambda c, t, bb, i: _HIST_SKIP_EM300(c, t, bb, i) or _hist_skip_am10x(False)(c, t, bb, i))


def history_em300_th(b: bytes) -> list[tuple[int, dict]]:
    """EM300-TH: 8-byte record temperature + humidity (last byte unused)."""
    return _hist_scan(b, {(0x20, 0xCE): (8, _hist_th)}, _HIST_SKIP_EM300)


def history_em300_mcs(b: bytes) -> list[tuple[int, dict]]:
    """EM300-MCS: temperature, humidity, magnet_status (0 closed, 1 open)."""
    def rec(b: bytes, i: int) -> dict:
        out = _hist_th(b, i)
        _hist_put(out, "magnet_status", _hist_mag(b[i + 7]))
        return out
    return _hist_scan(b, {(0x20, 0xCE): (8, rec)}, _HIST_SKIP_EM300)


def history_em300_leak(b: bytes) -> list[tuple[int, dict]]:
    """EM300-SLD / EM300-ZLD: temperature, humidity, input_05 (1 = leak), as the live decoder."""
    def rec(b: bytes, i: int) -> dict:
        out = _hist_th(b, i)
        _hist_put(out, "input_05", _hist_mag(b[i + 7]))
        return out
    return _hist_scan(b, {(0x20, 0xCE): (8, rec)}, _HIST_SKIP_EM300)


def history_em300_mld(b: bytes) -> list[tuple[int, dict]]:
    """EM300-MLD: leak (1 = leak); bytes 4-6 of the record are unused."""
    return _hist_scan(b, {(0x20, 0xCE): (8, lambda b, i: {} if b[i + 7] not in (0, 1) else {"leak": b[i + 7]})},
                      _HIST_SKIP_EM300)


def _hist_di_water(out: dict, b: bytes, i: int) -> dict:
    mode = b[i + 8]
    if mode == 1:
        _hist_put(out, "input_05", _hist_mag(b[i + 9]))
    elif mode == 2:
        out["water_conv"] = _u16le(b, i + 10) / 10
        out["pulse_conv"] = _u16le(b, i + 12) / 10
        out["water"] = _f32(b, i + 14, True)
    return out


def _hist_di_20(b: bytes, i: int) -> dict:
    out = _hist_th(b, i)
    mode = b[i + 7]
    if mode == 1:
        _hist_put(out, "input_05", _hist_mag(b[i + 8]))
    elif mode == 2:
        out["pulse_count"] = _u32le(b, i + 9)
    return out


def history_em300_di(b: bytes) -> list[tuple[int, dict]]:
    """EM300-DI: 0x20 = temperature, humidity, input_05 or pulse_count; 0x21 (water meter firmware) = temperature,
    humidity, input_05 or water_conv / pulse_conv / water."""
    return _hist_scan(b, {(0x20, 0xCE): (13, _hist_di_20),
                          (0x21, 0xCE): (18, lambda b, i: _hist_di_water(_hist_th(b, i), b, i))}, _HIST_SKIP_EM300)


def history_em300_di_hall(b: bytes) -> list[tuple[int, dict]]:
    """EM300-DI-HALL: 0x21 record = input_05 or water_conv / pulse_conv / water (no temperature)."""
    return _hist_scan(b, {(0x21, 0xCE): (18, lambda b, i: _hist_di_water({}, b, i))}, _HIST_SKIP_EM300)


def _hist_em320v2(b: bytes, i: int) -> dict:
    out: dict[str, Any] = {}
    if _u16le(b, i + 4) not in (0x8001, 0x8002, 0x8003):
        out["temperature"] = _i16le(b, i + 4) / 10
    if _u16le(b, i + 6) != 0xFFFF:
        out["humidity"] = _u16le(b, i + 6) / 10
    return out


def history_em320_th_v2(b: bytes) -> list[tuple[int, dict]]:
    """EM320-TH (v2 firmware): temperature, humidity (0.1 %); error markers dropped."""
    return _hist_scan(b, {(0x20, 0xCE): (9, _hist_em320v2)}, _hist_skip_em320v2)


def _hist_rdl(b: bytes, i: int) -> dict:
    out: dict[str, Any] = {}
    if _u16le(b, i + 4) not in (0xFFFD, 0xFFFE, 0xFFFF):
        out["distance"] = _i16le(b, i + 4)
    if _u16le(b, i + 6) not in (0xFFFE, 0xFFFF):
        out["temperature"] = _i16le(b, i + 6) / 10
    if b[i + 10] & 0x10:                               # mutation alarm event
        out["distance_mutation"] = _i16le(b, i + 8)
    return out


def history_em410_rdl(b: bytes) -> list[tuple[int, dict]]:
    """EM410-RDL / EM411-RDL: distance (mm), temperature, distance_mutation (mutation-alarm records)."""
    return _hist_scan(b, {(0x20, 0xCE): (11, _hist_rdl)}, _HIST_SKIP_RDL)


# ---- AM100 / AM300 / AM300L ranges ---------------------------------------------------
def history_am103(b: bytes) -> list[tuple[int, dict]]:
    """AM103 / AM103L: temperature, humidity, co2."""
    return _hist_scan(b, {(0x20, 0xCE): (9, lambda b, i: {**_hist_th(b, i), "co2": _u16le(b, i + 7)})},
                      _hist_skip_am10x(True))


def _hist_am300(tvoc_key: str, extra: tuple) -> Callable[[bytes, int], dict]:
    def rec(b: bytes, i: int) -> dict:
        out: dict[str, Any] = {"temperature": _i16le(b, i + 4) / 10, "humidity": _u16le(b, i + 6) / 2}
        _hist_put(out, "pir", _hist_mag(b[i + 8]))
        out["light_level"] = b[i + 9]
        out["co2"] = _u16le(b, i + 10)
        out[tvoc_key] = _u16le(b, i + 12) / 100 if tvoc_key == "tvoc_iaq" else _u16le(b, i + 12)
        out["pressure"] = _u16le(b, i + 14) / 10
        for n, (key, div) in enumerate(extra):
            out[key] = _u16le(b, i + 16 + 2 * n) / div if div != 1 else _u16le(b, i + 16 + 2 * n)
        return out
    return rec


def _hist_am300_recs(extra: tuple, ids: tuple = (0x20, 0x21)) -> dict:
    size = 16 + 2 * len(extra)
    return {(ids[0], 0xCE): (size, _hist_am300("tvoc_iaq", extra)), (ids[1], 0xCE): (size, _hist_am300("tvoc", extra))}


_HIST_AM307 = _hist_am300_recs(())
_HIST_AM308 = _hist_am300_recs((("pm2_5", 1), ("pm10", 1)))
_HIST_AM319_HCHO = _hist_am300_recs((("pm2_5", 1), ("pm10", 1), ("hcho", 100)))
_HIST_AM319_O3 = _hist_am300_recs((("pm2_5", 1), ("pm10", 1), ("o3", 100)))
_HIST_AM319_WELL = _hist_am300_recs((("pm2_5", 1), ("hcho", 1000)), ids=(0x22, 0x23))


def history_am307(b: bytes) -> list[tuple[int, dict]]:
    """AM307: temperature, humidity, pir (0/1), light_level, co2, tvoc_iaq (0x20) or tvoc µg/m³ (0x21), pressure."""
    return _hist_scan(b, _HIST_AM307, _HIST_SKIP_AM300)


def history_am308(b: bytes) -> list[tuple[int, dict]]:
    """AM308: as AM307 plus pm2_5, pm10."""
    return _hist_scan(b, _HIST_AM308, _HIST_SKIP_AM300)


def history_am319_hcho(b: bytes) -> list[tuple[int, dict]]:
    """AM319 HCHO: as AM308 plus hcho (mg/m³)."""
    return _hist_scan(b, _HIST_AM319_HCHO, _HIST_SKIP_AM300)


def history_am319_o3(b: bytes) -> list[tuple[int, dict]]:
    """AM319 O3: as AM308 plus o3 (ppm)."""
    return _hist_scan(b, _HIST_AM319_O3, _HIST_SKIP_AM300)


def history_am319_hcho_well(b: bytes) -> list[tuple[int, dict]]:
    """AM319 HCHO (Well sensor): records on 0x22 (TVOC index) / 0x23 (TVOC µg/m³), pm2_5, hcho (/1000), no pm10."""
    return _hist_scan(b, _HIST_AM319_WELL, _HIST_SKIP_AM300)


def _hist_am30xl(lux: bool, co2: bool) -> Callable[[bytes, int], dict]:
    def rec(b: bytes, i: int) -> dict:
        out: dict[str, Any] = {}
        if b[i + 4] == 1:                              # 1 = data valid
            out["temperature"] = _i16le(b, i + 5) / 10
        if b[i + 7] == 1:
            out["humidity"] = b[i + 8] / 2
        if (b[i + 9] >> 6) & 1:
            status = b[i + 9] & 0x3F
            out["pir"] = status == 1
            out["occupancy"] = 1 if status == 1 else 0
            out["pir_count"] = _u16le(b, i + 10)
        if b[i + 12] == 1:
            out["illuminance_lux" if lux else "light_level"] = _u16le(b, i + 13)
        if co2 and b[i + 15] == 1:
            out["co2"] = _u16le(b, i + 16)
        return out
    return rec


def history_am304l(b: bytes) -> list[tuple[int, dict]]:
    """AM304L: 0x20 = light level, 0x21 = lux variant; temperature, humidity, pir/occupancy, pir_count (valid fields only)."""
    return _hist_scan(b, {(0x20, 0xCE): (15, _hist_am30xl(False, False)), (0x21, 0xCE): (15, _hist_am30xl(True, False))},
                      _hist_skip_am30xl(False))


def history_am305l(b: bytes) -> list[tuple[int, dict]]:
    """AM305L: as AM304L plus co2."""
    return _hist_scan(b, {(0x20, 0xCE): (18, _hist_am30xl(False, True)), (0x21, 0xCE): (18, _hist_am30xl(True, True))},
                      _hist_skip_am30xl(True))


# ---- AT101 ------------------------------------------------------------------------
def history_at101(b: bytes) -> list[tuple[int, dict]]:
    """AT101: stored GNSS fixes (latitude, longitude)."""
    return _hist_scan(b, {(0x20, 0xCE): (12, lambda b, i: {"latitude": _i32le(b, i + 8) / 1_000_000,
                                                            "longitude": _i32le(b, i + 4) / 1_000_000})},
                      _HIST_SKIP_AT101)


# --------------------------------------------------------------------------
# Stored history records (g23) – checked against the official decoders (tools/checks/hist_g23.py)
# --------------------------------------------------------------------------
# ==========================================================================
# Stored history (data logging) records – VS / UC / WS / WT ranges (survey group g2 + g3).
# Each history_<family>(b) returns [(unix_timestamp, {our_key: value}), ...] in payload order.
# Non-history channels are skipped with the lengths the official decoders use; parsing stops
# (returns what was found so far) at unknown or truncated data. Records without any value are dropped.
# Checked against Milesight's official JS decoders (hist/g23_check.py).
# ==========================================================================


def _h23_scan(b: bytes, hist: dict, fixed: dict, skip=None) -> list[tuple[int, dict]]:
    """hist[(cid, ctype)] = parser(b, i) -> (consumed, ts, values) | None;
    fixed[(cid, ctype)] = length | fn(b, i) -> length | None; skip(cid, ctype, b, i) -> length | None."""
    recs: list[tuple[int, dict]] = []
    i = 0
    while i + 2 <= len(b):
        cid, ctype = b[i], b[i + 1]
        i += 2
        p = hist.get((cid, ctype))
        if p is not None:
            r = p(b, i)
            if r is None:
                break
            n, ts, vals = r
            i += n
            if vals:
                recs.append((ts, vals))
            continue
        n = fixed.get((cid, ctype))
        if callable(n):
            n = n(b, i)
        if n is None and skip is not None:
            n = skip(cid, ctype, b, i)
        if n is None:
            n = _decode_common(cid, ctype, b, i, {})
        if n is None or not _need(b, i, n):
            break
        i += n
    return recs


# ---- VS121 people counter (0x20 0xCE: ts u32 + type u8 + data) -------------------------------
def _h23_vs121_rec(b: bytes, i: int):
    if not _need(b, i, 5):
        return None
    ts, t, j = _u32le(b, i), b[i + 4], i + 5
    v: dict[str, Any] = {}
    if t == 0x11:
        if not _need(b, j, 5):
            return None
        v["dwell_time_avg"] = _u16le(b, j + 1)
        v["dwell_time_max"] = _u16le(b, j + 3)
        return 10, ts, v
    if t == 0x03:
        if not _need(b, j, 1):
            return None
        v["people_count_max"] = b[j]
        return 6, ts, v
    if not 0x01 <= t <= 0x12 or not _need(b, j, 4):
        return None
    if t == 0x01:
        v["people_count_all"] = b[j]
        v["region_count"] = b[j + 1]
        mask = _u16be(b, j + 2)
        for r in range(b[j + 1]):
            v[f"region_{r + 1}"] = (mask >> r) & 1
    elif t == 0x02:
        v["people_in"], v["people_out"] = _u16le(b, j), _u16le(b, j + 2)
    elif 0x04 <= t <= 0x07:
        base = (t - 0x04) * 4 + 1
        for r in range(4):
            v[f"region_{base + r}_count"] = b[j + r]
    elif 0x08 <= t <= 0x0F:
        src = "abcd"[(t - 0x08) // 2]
        dst = "ab" if t % 2 == 0 else "cd"
        v[f"{src}_to_{dst[0]}"], v[f"{src}_to_{dst[1]}"] = _u16le(b, j), _u16le(b, j + 2)
    elif t == 0x10:
        v["people_total_in"], v["people_total_out"] = _u16le(b, j), _u16le(b, j + 2)
    else:                                   # 0x12
        v["line_in"], v["line_out"] = _u16le(b, j), _u16le(b, j + 2)
    return 9, ts, v


_H23_VS121_FIXED = {(0x04, 0xC9): 4, (0x05, 0xCC): 4, (0x06, 0xCD): 1, (0x07, 0xD5): 8, (0x08, 0xD5): 8,
                    (0x09, 0xDA): 8, (0x0A, 0xDA): 8, (0x0B, 0xDA): 8, (0x0C, 0xDA): 8, (0x0D, 0xCC): 4,
                    (0x0E, 0xE4): 5, (0x0F, 0x85): 4, (0x10, 0xF7): 4}


def history_vs121(b: bytes) -> list[tuple[int, dict]]:
    """VS121 AI people counter history."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_vs121_rec}, _H23_VS121_FIXED)


# ---- VS321 occupancy / people counting (0x20 0xCE: ts + mode + data) --------------------------
def _h23_vs321_rec(b: bytes, i: int):
    if not _need(b, i, 5):
        return None
    ts, mode = _u32le(b, i), b[i + 4]
    if mode == 0 and _need(b, i, 7):
        return 7, ts, {"people_count_all": _u16le(b, i + 5)}
    if mode == 1 and _need(b, i, 9):
        mask, data = _u16le(b, i + 5), _u16le(b, i + 7)
        v: dict[str, Any] = {}
        for r in range(10):
            v[f"region_{r + 1}_enable"] = "enable" if (mask >> r) & 1 else "disable"
            v[f"region_{r + 1}"] = (data >> r) & 1
        return 9, ts, v
    return None


_H23_VS321_FIXED = {(0x01, 0x75): 1, (0x03, 0x67): 2, (0x04, 0x68): 1, (0x05, 0xFD): 2, (0x06, 0xFE): 4,
                    (0x07, 0xFF): 1, (0x08, 0xF4): 2, (0x0A, 0xEF): 4, (0x83, 0x67): 3, (0x84, 0x68): 2}


def history_vs321(b: bytes) -> list[tuple[int, dict]]:
    """VS321 AI occupancy sensor history (people count or region occupancy)."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_vs321_rec}, _H23_VS321_FIXED)


# ---- VS133 / VS135 ToF people counter (0x20 0xCE: ts + type + data, 9 or 8 bytes) --------------
def _h23_vs133_rec(b: bytes, i: int):
    if not _need(b, i, 5):
        return None
    ts, t, j = _u32le(b, i), b[i + 4], i + 5
    v: dict[str, Any] = {}
    if t in (0x10, 0x20, 0x1E, 0x3C):
        if not _need(b, i, 8):
            return None
        pre = f"region_{b[j]}_child" if t in (0x1E, 0x3C) else f"region_{b[j]}"
        v[f"{pre}_dwell_time_{'avg' if t in (0x10, 0x1E) else 'max'}"] = _u16le(b, j + 1)
        return 8, ts, v
    if not (0x03 <= t <= 0x0F or 0x11 <= t <= 0x1D) or not _need(b, i, 9):
        return None
    if t in (0x0F, 0x1D):
        suffix = "child_count" if t == 0x1D else "count"
        for r in range(4):
            v[f"region_{r + 1}_{suffix}"] = b[j + r]
        return 9, ts, v
    child = t >= 0x11
    base = t - (0x0E if child else 0)          # 0x03..0x0E
    line = (base - 0x03) // 3 + 1
    pre = f"line_{line}_child" if child else f"line_{line}"
    kind = (base - 0x03) % 3                   # 0 total in, 1 total out, 2 period
    if kind == 2:
        v[f"{pre}_in"], v[f"{pre}_out"] = _u16le(b, j), _u16le(b, j + 2)
        if line == 1 and not child:
            v["people_in"], v["people_out"] = v[f"{pre}_in"], v[f"{pre}_out"]
    else:
        d = "in" if kind == 0 else "out"
        v[f"{pre}_total_{d}"] = _u32le(b, j)
        if line == 1 and not child:
            v[f"people_total_{d}"] = v[f"{pre}_total_{d}"]
    return 9, ts, v


def _h23_vs133_len(cid: int, ctype: int, b: bytes, i: int) -> int | None:
    if cid == 0xFF and ctype == 0xD4:
        return 5
    if ctype == 0xD2 and (0x03 <= cid <= 0x0D or 0x11 <= cid <= 0x1B) and \
            ((cid - 0x0E) if cid >= 0x11 else cid) % 3 != 2:
        return 4
    if ctype == 0xCC and cid in (0x05, 0x08, 0x0B, 0x0E, 0x13, 0x16, 0x19, 0x1C):
        return 4
    if ctype == 0xE3 and cid in (0x0F, 0x1D):
        return 4
    if ctype == 0xE4 and cid in (0x10, 0x1E):
        return 5
    if cid == 0x50 and ctype == 0xFC:
        return 3
    return _vs_skip(cid, ctype, b, i, _VS133_SKIP, _VS133_SKIP_EXT)


def history_vs133(b: bytes) -> list[tuple[int, dict]]:
    """VS133 / VS135 AI ToF people counter history (lines 1-4, regions, child counting)."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_vs133_rec}, {}, _h23_vs133_len)


# ---- VS350 / VS351 / VS360 passage counters (0x20 0xCE: ts + type + period [+ total]) ----------
def _h23_vs35x_rec(b: bytes, i: int):
    if not _need(b, i, 5):
        return None
    ts, t = _u32le(b, i), b[i + 4]
    n = {0: 9, 1: 13}.get(t)
    if n is None or not _need(b, i, n):
        return None
    v = {"people_in": _u16le(b, i + 5), "people_out": _u16le(b, i + 7)}
    if t == 1:
        v["people_total_in"], v["people_total_out"] = _u16le(b, i + 9), _u16le(b, i + 11)
    return n, ts, v


_H23_VS35X_FIXED = {(0x01, 0x75): 1, (0x02, 0x75): 1, (0xFF, 0xCC): 1, (0x03, 0x67): 2, (0x83, 0x67): 3,
                    (0x03, 0xF4): 2, (0x04, 0xCC): 4, (0x84, 0xCC): 5, (0x05, 0xCC): 4, (0x85, 0xCC): 5,
                    (0x0A, 0xEF): 4, (0x81, 0xEE): 1}
_H23_VS35X_SKIP = {**_VS350_SKIP, **_VS351_SKIP, **_VS360_SKIP}
_H23_VS35X_EXT = {**_VS_EXT_REPORT_TYPE, **_VS351_SKIP_EXT}


def history_vs35x(b: bytes) -> list[tuple[int, dict]]:
    """VS350 / VS351 / VS360 passage people counter history (period in/out, optional totals)."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_vs35x_rec}, _H23_VS35X_FIXED,
                     lambda c, t, b_, i: _vs_skip(c, t, b_, i, _H23_VS35X_SKIP, _H23_VS35X_EXT))


# ---- VS373 radar fall detection (0x20 0xCE: ts + alarm event, 9 bytes) -------------------------
def _h23_vs373_rec(b: bytes, i: int):
    if not _need(b, i, 9):
        return None
    v: dict[str, Any] = {"alarm_id": _u16le(b, i + 4), "alarm_type": _map(VS373_ALARM_TYPE, b[i + 6]),
                         "alarm_status": _map(VS373_ALARM_STATUS, b[i + 7])}
    if b[i + 6] in (3, 6, 7):
        v["region_id"] = b[i + 8]
    return 9, _u32le(b, i), v


_H23_VS373_FIXED = {(0x03, 0xF8): 6, (0x07, 0xB0): 8, (0x04, 0xF9): 4, (0x09, 0xB2): 6, (0x0A, 0xB3): 5,
                    (0x05, 0xFA): 8, (0x0B, 0xB4): 9, (0x0C, 0xB4): 9, (0x06, 0xFB): 5, (0x08, 0xB1): 3}


def history_vs373(b: bytes) -> list[tuple[int, dict]]:
    """VS373 history = stored alarm events (same fields as the live 'events' entries)."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_vs373_rec}, _H23_VS373_FIXED)


# ---- UC300 (0x20 0xDC: I/O channels by mask, 0x20 0xDD: Modbus channels by mask) ---------------
def _h23_uc300_io(b: bytes, i: int):
    if not _need(b, i, 6):
        return None
    ts, mask, j = _u32le(b, i), _u16le(b, i + 4), i + 6
    v: dict[str, Any] = {}
    for k in range(13):
        if not mask >> k & 1:
            continue
        if k < 4:
            if not _need(b, j, 5):
                return None
            raw = _u32le(b, j + 1)
            if b[j] == 0:
                v[f"gpio_input_{k + 1}"] = 1 if raw == 1 else 0
            else:
                v[f"gpio_counter_{k + 1}"] = raw
            j += 5
        elif k < 6:
            if not _need(b, j, 1):
                return None
            v[f"gpio_output_{k - 3}"] = 1 if b[j] == 1 else 0
            j += 1
        elif k < 8:
            if not _need(b, j, 2):
                return None
            v[f"pt100_{k - 5}"] = _f16(b, j, True)
            j += 2
        elif k < 12:
            if not _need(b, j, 8):
                return None
            _stats16(v, f"{'adc' if k < 10 else 'adv'}_{(k - 8) % 2 + 1}", b, j, True)
            j += 8
        else:                                  # custom text message (not a measurement)
            if not _need(b, j, 48):
                return None
            j += 48
    return j - i, ts, v


def _h23_uc300_modbus(b: bytes, i: int):
    if not _need(b, i, 8):
        return None
    ts, mask, j = _u32le(b, i), _u32le(b, i + 4), i + 8
    v: dict[str, Any] = {}
    for k in range(32):
        if not mask >> k & 1:
            continue
        if not _need(b, j, 5):
            return None
        ddef = b[j]
        dtype = ddef & 0x7F
        if dtype <= 11:
            res = _modbus_value(b, j + 1, dtype, bool(ddef >> 7), True, hi_word=True)
            if res is not None:
                v[f"modbus_chn_{k + 1}"] = res[0]
        j += 5
    return j - i, ts, v


def _h23_uc300_len(cid: int, ctype: int, b: bytes, i: int) -> int | None:
    if 0x03 <= cid <= 0x06 and ctype == 0x00 or cid in (0x07, 0x08) and ctype == 0x01:
        return 1
    if 0x03 <= cid <= 0x06 and ctype == 0xC8 or 0x0B <= cid <= 0x0E and ctype == 0x02:
        return 4
    if cid in (0x09, 0x0A) and ctype == 0x67:
        return 2
    if 0x09 <= cid <= 0x0E and ctype == 0xE2:
        return 8
    if cid == 0xFF and ctype == 0x15:
        return 1
    if cid == 0xFF and ctype == 0x19:
        nxt = _modbus_19({}, b, i, True, hi_word=True)
        return None if nxt is None else nxt - i
    return None


def history_uc300(b: bytes) -> list[tuple[int, dict]]:
    """UC300 history: I/O (GPIO, PT100, AI/AV statistics) and Modbus records, in payload order."""
    return _h23_scan(b, {(0x20, 0xDC): _h23_uc300_io, (0x20, 0xDD): _h23_uc300_modbus}, {}, _h23_uc300_len)


# ---- UC501 / UC502 (0x20 0xDC GPIO+AI, 0x20 0xE0 SDI-12, 0x20 0xDD Modbus) ----------------------
def _h23_uc50x_io(b: bytes, i: int):
    if not _need(b, i, 22):
        return None
    v: dict[str, Any] = {}
    for n, j in ((1, i + 4), (2, i + 9)):
        t, raw = b[j], _u32le(b, j + 1)
        if t == 0:
            v[f"gpio_input_{n}"] = 1 if raw == 1 else 0
        elif t == 1:
            v[f"gpio_output_{n}"] = 1 if raw == 1 else 0
        elif t == 2:
            v[f"gpio_counter_{n}"] = raw
    v["analog_input_1"] = _i32le(b, i + 14) / 1000
    v["analog_input_2"] = _i32le(b, i + 18) / 1000
    return 22, _u32le(b, i), v


def _h23_uc50x_sdi12(b: bytes, i: int):
    if not _need(b, i, 6):
        return None
    n = 6 + 36 * bin(_u16le(b, i + 4)).count("1")
    return (n, _u32le(b, i), {}) if _need(b, i, n) else None       # text only: no numeric values


def _h23_uc50x_modbus(b: bytes, i: int):
    if not _need(b, i, 6):
        return None
    ts, mask, j = _u32le(b, i), _u16le(b, i + 4), i + 6
    v: dict[str, Any] = {}
    for k in range(16):
        if not mask >> k & 1:
            continue
        if not _need(b, j, 5):
            return None
        v[f"modbus_chn_{k + 1}"] = _f32(b, j + 1, False) if b[j] & 0x07 in (5, 7) else _u32le(b, j + 1)
        j += 5
    return j - i, ts, v


def _h23_uc50x_len(cid: int, ctype: int, b: bytes, i: int) -> int | None:
    if cid in (0x03, 0x04) and ctype in (0x00, 0x01) or cid == 0x01 and ctype == 0x75 \
            or cid == 0xFF and ctype in (0x14, 0x15):
        return 1
    if cid in (0x03, 0x04) and ctype == 0xC8:
        return 4
    if cid in (0x05, 0x06) and ctype in (0x02, 0xE2):
        return 8
    if cid in (0x85, 0x86) and ctype == 0xE2:
        return 9
    if cid == 0x08 and ctype == 0xDB:
        return 37
    if cid in (0xFF, 0x80) and ctype == 0x0E and _need(b, i, 2):
        size = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 6: 4, 5: 4, 7: 4}[b[i + 1] & 0x07]
        return 2 + size + (1 if cid == 0x80 else 0)
    return None


def history_uc50x(b: bytes) -> list[tuple[int, dict]]:
    """UC501 / UC502 history: GPIO + analog inputs, Modbus (SDI-12 text records are skipped)."""
    return _h23_scan(b, {(0x20, 0xDC): _h23_uc50x_io, (0x20, 0xE0): _h23_uc50x_sdi12,
                         (0x20, 0xDD): _h23_uc50x_modbus}, {}, _h23_uc50x_len)


# ---- UC511 / UC512 valve controller (0x20 0xCE valve/GPIO/pulse, 0x21 0xCE pipe pressure) -------
def _h23_uc51x_valve(b: bytes, i: int):
    if not _need(b, i, 9):
        return None
    val = b[i + 4]
    idx = 2 if val >> 4 & 1 else 1
    v: dict[str, Any] = {f"valve_{idx}": val & 1}
    if val >> 1 & 1:
        v[f"valve_{idx}_pulse"] = _u32le(b, i + 5)
    else:
        v[f"gpio_{idx}"] = val >> 2 & 1
    return 9, _u32le(b, i), v


def _h23_uc51x_pressure(b: bytes, i: int):
    return (6, _u32le(b, i), {"pressure": _u16le(b, i + 4)}) if _need(b, i, 6) else None


_H23_UC51X_FIXED = {(0x01, 0x75): 1, (0x03, 0x01): 1, (0x05, 0x01): 1, (0x04, 0xC8): 4, (0x06, 0xC8): 4,
                    (0x07, 0x01): 1, (0x08, 0x01): 1, (0x09, 0x7B): 2, (0xB9, 0x7B): 1, (0x0B, 0xF5): 9,
                    (0xF8, 0xA4): 8, (0xF8, 0xA5): 2, (0xF8, 0xA8): 9, (0xF9, 0xA7): 3, (0xF9, 0xA8): 8,
                    (0x0E, 0xAF): 3, (0x0F, 0xAF): 3, (0xF8, 0xAF): 3}


def history_uc51x(b: bytes) -> list[tuple[int, dict]]:
    """UC511 / UC512 solenoid valve controller history."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_uc51x_valve, (0x21, 0xCE): _h23_uc51x_pressure}, _H23_UC51X_FIXED)


# ---- UC100 Modbus converter, firmware v1 (0x20 0xCE: ts + chn + def + 4-byte value) -----------
def _h23_uc100_rec(b: bytes, i: int):
    if not _need(b, i, 10):
        return None
    ts, chn, ddef, j = _u32le(b, i), f"modbus_chn_{b[i + 4] + 1}", b[i + 5], i + 6
    v: dict[str, Any] = {}
    if ddef >> 1 & 1:                          # read ok
        t, sign = (ddef >> 2) & 0x1F, bool(ddef >> 7)
        if t in (0, 1):
            v[chn] = 1 if b[j] == 1 else 0
        elif t in (2, 3, 14, 15, 4, 5, 6, 7, 16, 17, 18, 19):
            v[chn] = _i32le(b, j) if sign else _u32le(b, j)
        elif t in (8, 9, 20, 21):
            v[chn] = _i16le(b, j) if sign else _u16le(b, j)
        elif 10 <= t <= 13 or 22 <= t <= 25:
            v[chn] = _f32(b, j, True)
    return 10, ts, v


def _h23_uc100_len(cid: int, ctype: int, b: bytes, i: int) -> int | None:
    if cid == 0xFF and ctype == 0x15:
        return 1
    if cid == 0xF9 and ctype == 0x5F:
        return 7
    if cid == 0x20 and ctype == 0xCD and _need(b, i, 5):     # custom message history: text only
        return 5 + b[i + 4]
    if cid == 0xFF and ctype in (0x19, 0xEE):
        nxt = _modbus_19({}, b, i, True, bool_types=(0, 1))   # same layout: chn, len/flags, def, value
        return None if nxt is None else nxt - i
    return None


def history_uc100(b: bytes) -> list[tuple[int, dict]]:
    """UC100 (firmware v1) Modbus history."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_uc100_rec}, {}, _h23_uc100_len)


# ---- UC100 v2 (0x21 0xCE: ts + chn + def u16 + 2 x 8-byte values) ------------------------------
def _h23_uc100v2_value(b: bytes, j: int, t: int, sign: bool):
    if t in (0, 1):
        return 1 if b[j] == 1 else 0
    if t in (2, 3, 8, 9, 20, 21, 14, 15):
        return _i16le(b, j) if sign else _u16le(b, j)
    if 4 <= t <= 7 or 16 <= t <= 19:
        return _i32le(b, j) if sign else _u32le(b, j)
    if 10 <= t <= 13 or 22 <= t <= 25:
        return _f32(b, j, True)
    if 30 <= t <= 33 or 38 <= t <= 41:
        return int.from_bytes(b[j:j + 8], "little", signed=sign)
    if 26 <= t <= 29 or 34 <= t <= 37:
        return _f64(b, j)
    return 0                                   # the official decoder reports 0 for unknown types


def _h23_uc100v2_rec(b: bytes, i: int):
    if not _need(b, i, 23):
        return None
    ts, chn, d = _u32le(b, i), f"modbus_chn_{b[i + 4] + 1}", _u16le(b, i + 5)
    v: dict[str, Any] = {}
    if d >> 8 & 1:
        t, sign = (d >> 9) & 0x3F, bool(d >> 15)
        v[chn] = _h23_uc100v2_value(b, i + 7, t, sign)
        if (d >> 6) & 0x03 == 2:
            v[f"{chn}_reg_2"] = _h23_uc100v2_value(b, i + 15, t, sign)
    return 23, ts, v


def _h23_uc100v2_len(cid: int, ctype: int, b: bytes, i: int) -> int | None:
    if cid == 0xFF and ctype == 0x15:
        return 1
    if cid == 0xF9 and ctype == 0x74:
        return 9
    if cid == 0x21 and ctype == 0xCD and _need(b, i, 5):
        return 5 + b[i + 4]
    if cid == 0xFC:                            # history response: 1 byte after the 2-byte header
        return 1
    if cid == 0xF9 and ctype == 0x73 and _need(b, i, 2):
        res = _modbus_value(b, i + 2, b[i + 1] & 0x1F, bool(b[i + 1] >> 7), True, bool_types=(0, 1))
        return None if res is None else 2 + res[1]
    return None


def history_uc100_v2(b: bytes) -> list[tuple[int, dict]]:
    """UC100 (firmware v2) Modbus history (register 1 and optional register 2)."""
    return _h23_scan(b, {(0x21, 0xCE): _h23_uc100v2_rec}, {}, _h23_uc100v2_len)


# ---- WS203 motion + T/H sensor (0x20 0xCE: ts + type + occupancy + temperature + humidity) -----
def _h23_ws203_rec(b: bytes, i: int):
    if not _need(b, i, 9):
        return None
    v: dict[str, Any] = {"temperature": _i16le(b, i + 6) / 10, "humidity": b[i + 8] / 2}
    if b[i + 5] in (0, 1):
        v["occupancy"] = b[i + 5]
    return 9, _u32le(b, i), v


def history_ws203(b: bytes) -> list[tuple[int, dict]]:
    """WS203 motion & temperature / humidity sensor history."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_ws203_rec},
                     {(0x01, 0x75): 1, (0x03, 0x67): 2, (0x04, 0x68): 1, (0x05, 0x00): 1, (0x83, 0x67): 3})


# ---- WT201 v1 thermostat (0x20 0xCE: ts + 2 packed u16) ----------------------------------------
def _h23_wt201_rec(b: bytes, i: int):
    if not _need(b, i, 8):
        return None
    v1, v2 = _u16le(b, i + 4), _u16le(b, i + 6)
    v: dict[str, Any] = {
        "fan_mode": _WT201_FAN[v1 & 0x03],
        "fan_status": _WT201_FAN_STATUS[v1 >> 2 & 0x03],
        "system_status": bool(v1 >> 4 & 1),
        "temperature": ((v1 >> 5 & 0x7FF) - 1000) / 10,
        "temperature_control_mode": ("heat", "em heat", "cool", "auto")[v2 & 0x03],
        "temperature_control_status": _WT201_STATUS.get(v2 >> 2 & 0x07, "unknown"),
        "target_temperature": ((v2 >> 5 & 0x7FF) - 1000) / 10,
    }
    return 8, _u32le(b, i), v


_H23_WT201_FIXED = {(0x03, 0x67): 2, (0x04, 0x67): 2, (0x05, 0xE7): 1, (0x06, 0xE8): 1, (0x07, 0xBC): 1,
                    (0x08, 0x8E): 1, (0x09, 0x68): 1, (0x0A, 0x6E): 1, (0xFF, 0xCB): 3, (0x83, 0x67): 2,
                    (0xB3, 0x67): 1, (0xB9, 0x68): 1}


def history_wt201(b: bytes) -> list[tuple[int, dict]]:
    """WT201 (firmware v1) thermostat history."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_wt201_rec}, _H23_WT201_FIXED)


# ---- WT201 v2 / WT211 thermostat (0x20 0xCE: ts + packed u16 + 2 targets + temperature + humidity)
def _h23_wt201v2_rec(b: bytes, i: int):
    if not _need(b, i, 13):
        return None
    m = _u16le(b, i + 4)
    v: dict[str, Any] = {
        "system_status": bool(m & 1),
        "fan_mode": ("auto", "on", "circulate", "disable")[m >> 1 & 0x03],
        "fan_status": ("standby", "high speed", "low speed", "on")[m >> 3 & 0x03],
        "temperature_control_mode": ("heat", "em heat", "cool", "auto")[m >> 5 & 0x03],
        "temperature_control_status": _WT201_STATUS.get(m >> 7 & 0x0F, "unknown"),
        "target_temperature": _i16le(b, i + 6) / 10,
    }
    if _u16le(b, i + 8) != 0xFFFF:
        v["target_temperature_2"] = _i16le(b, i + 8) / 10
    v["temperature"] = _i16le(b, i + 10) / 10
    v["humidity"] = b[i + 12] / 2
    return 13, _u32le(b, i), v


_H23_WT201V2_FIXED = {**_H23_WT201_FIXED, (0x0B, 0x67): 2, (0x07, 0xE9): 1, (0x87, 0xE9): 2, (0x83, 0x67): 3,
                      (0xF9, 0x40): 7}


def history_wt201_v2(b: bytes) -> list[tuple[int, dict]]:
    """WT201 v2 / WT211 thermostat history."""
    return _h23_scan(b, {(0x20, 0xCE): _h23_wt201v2_rec}, _H23_WT201V2_FIXED)


# ---- WT102 radiator thermostat (command format: 0xED type ts(4) starts a record; the commands
#      that follow, up to the next 0xED, are that record's values) -------------------------------
def history_wt102(b: bytes) -> list[tuple[int, dict]]:
    """WT102 history: each 0xED marker opens a record filled by the following commands."""
    recs: list[tuple[int, dict]] = []
    cur: tuple[int, dict] | None = None
    i = 0
    while i < len(b):
        if b[i] == 0xED:
            if not _need(b, i, 6):
                break
            if cur is not None and cur[1]:
                recs.append(cur)
            cur = (_u32le(b, i + 2), {})
            i += 6
            continue
        out, n = _parse_wt102(b[i:])
        if n == 0:
            break
        if cur is not None:
            cur[1].update({k: v for k, v in out.items() if isinstance(v, (int, float))})
        i += n
    if cur is not None and cur[1]:
        recs.append(cur)
    return recs


def encode_fields(spec: dict, values: dict[str, Any]) -> bytes:
    """Multi-field setting: prefix + fields + suffix (see downlinks.json "settings").
    A field is a constant ({"const": hex}), an enum ({"map": {...}}, optionally derived from another field via
    "from" and shifted / OR-ed via "bits"), or a number ({"value": fmt, "scale": n})."""
    out = bytearray(bytes.fromhex(spec.get("prefix", "")))
    for f in spec["fields"]:
        if "const" in f:
            out += bytes.fromhex(f["const"])
            continue
        src = values.get(f.get("from", f["name"]))
        if "map" in f:
            if src not in f["map"]:
                raise ValueError(f"{f['name']}: {src!r} not one of {list(f['map'])}")
            raw = int(f["map"][src])
            bits = f.get("bits") or {}
            if bits:
                orv = bits.get("or", 0)
                raw = (raw << int(bits.get("shift", 0))) | (int(orv, 16) if isinstance(orv, str) else int(orv))
        else:
            if src is None:
                raise ValueError(f"{f['name']} required")
            lo, hi = f.get("min"), f.get("max")
            if (lo is not None and src < lo) or (hi is not None and src > hi):
                raise ValueError(f"{f['name']} {src} outside {lo}..{hi}")
            raw = round(float(src) * f.get("scale", 1))
        fmt = _TEMPLATE_FMT.get(f.get("value", "u8"))
        if fmt is None:
            fmt = {"i32le": "<i", "u24le": None}.get(f["value"])
        if f.get("value") == "u24le":
            out += int(raw).to_bytes(3, "little")
        else:
            out += struct.pack(fmt, int(raw))
    out += bytes.fromhex(spec.get("suffix", ""))
    return bytes(out)


def encode_template_fields(spec: dict, values: dict[str, Any]) -> bytes:
    """Templates with "fields" (e.g. fetch history start / end)."""
    return encode_fields(spec, values)
