"""Uplink envelope parsing and Milesight payload decoders.

Pure Python (no Home Assistant imports) so it can be unit-tested on its own.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import struct
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
