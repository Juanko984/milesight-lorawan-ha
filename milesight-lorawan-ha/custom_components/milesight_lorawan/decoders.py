"""Uplink envelope parsing and Milesight payload decoders.

Pure Python (no Home Assistant imports) so it can be unit-tested on its own.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
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
# --------------------------------------------------------------------------
def decode_em300(b: bytes) -> dict[str, Any]:
    """Decode an EM300-family uplink.

    Channel 0x06/0x00 is the 'status' input: magnet on EM300-MCS, leak on SLD/ZLD.
    It is returned as ``status_input`` (0/1); the model maps it to a meaning.
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
        elif cid == 0x83 and ctype == 0x67 and _need(b, i, 3):   # temperature with alarm flag
            out["temperature"] = _i16le(b, i) / 10
            out["temperature_alarm"] = b[i + 2]
            i += 3
        elif cid == 0x04 and ctype == 0x68 and _need(b, i, 1):
            out["humidity"] = b[i] / 2
            i += 1
        elif cid == 0x06 and ctype == 0x00 and _need(b, i, 1):
            out["status_input"] = 1 if b[i] else 0
            i += 1
        elif cid == 0x05 and ctype == 0x00 and _need(b, i, 1):  # EM300-DI GPIO
            out["gpio"] = 1 if b[i] else 0
            i += 1
        elif cid == 0x05 and ctype == 0xC8 and _need(b, i, 4):  # EM300-DI pulse counter
            out["pulse_count"] = _u32le(b, i)
            i += 4
        elif cid == 0x20 and ctype == 0xCE and _need(b, i, 8):  # history record
            out.setdefault("history", []).append({
                "timestamp": _u32le(b, i),
                "temperature": _i16le(b, i + 4) / 10,
                "humidity": b[i + 6] / 2,
                "status_input": 1 if b[i + 7] else 0,
            })
            i += 8
        else:
            break  # unknown channel / downlink response – stop safely
    return out
