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
        out["hardware_version"] = f"v{b[i]:x}.{b[i + 1] >> 4:x}"
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
            out["water"] = round(struct.unpack_from("<f", b, i + 4)[0], 2)
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
