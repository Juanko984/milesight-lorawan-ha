"""Finding Milesight gateways: from the network (DHCP, by the Milesight MAC prefix), from the first packet a gateway
forwards, or from a QR code / label scanned in the commissioning panel. Pure Python (unit-tested).

A Milesight gateway's EUI is its MAC address with FFFE in the middle (MAC 24:E1:24:FA:29:94 → EUI
24E124FFFEFA2994), so a gateway found on the network can be matched to the packets it forwards later."""
from __future__ import annotations

import json
import re
from typing import Any

MILESIGHT_OUI = "24e124"
_GW_MODEL = re.compile(r"\b(UG6[3579]|UG56|UG8[5-7]|SG50)\b", re.I)


def norm_hex(value: Any) -> str:
    return re.sub(r"[^0-9a-f]", "", str(value or "").lower())


def mac_to_eui(mac: Any) -> str | None:
    """MAC-48 → EUI-64 the way Milesight gateways form their gateway EUI."""
    m = norm_hex(mac)
    return f"{m[:6]}fffe{m[6:]}" if len(m) == 12 else None


def eui_to_mac(eui: Any) -> str | None:
    e = norm_hex(eui)
    if len(e) != 16 or e[6:10] != "fffe":
        return None
    return ":".join(e[:6][i:i + 2] for i in range(0, 6, 2)) + ":" + ":".join(e[10:][i:i + 2] for i in range(0, 6, 2))


def is_gateway_eui(eui: Any) -> bool:
    e = norm_hex(eui)
    return len(e) == 16 and e[6:10] == "fffe"


def is_milesight_mac(mac: Any) -> bool:
    return norm_hex(mac).startswith(MILESIGHT_OUI) and len(norm_hex(mac)) == 12


def default_name(eui: str, model: str | None = None) -> str:
    return f"{(model or 'Gateway').strip()} {norm_hex(eui)[-6:].upper()}"


def parse_gateway_code(text: str) -> dict[str, Any] | None:
    """A gateway's QR code or label text → {'eui', 'mac', 'sn', 'model'}; None when it is not a gateway.

    Accepts JSON ({"gateway_eui": …} / {"gweui": …} / {"mac": …, "model": "UG65"}), labelled text
    ('Gateway EUI: 24E124FFFEFA2994', 'MAC: 24:E1:24:FA:29:94', 'SN: …'), or a bare EUI with FFFE in the middle."""
    raw = (text or "").strip()
    if not raw:
        return None
    out: dict[str, Any] = {"eui": None, "mac": None, "sn": None, "model": None}
    data = None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        pass
    if isinstance(data, dict):
        low = {re.sub(r"[\s_\-]", "", str(k)).lower(): v for k, v in data.items()}
        for k in ("gatewayeui", "gweui", "gatewayid", "gwid"):
            if is_gateway_eui(low.get(k)):
                out["eui"] = norm_hex(low[k])
        if out["eui"] is None and is_gateway_eui(low.get("eui")):
            out["eui"] = norm_hex(low["eui"])
        if is_milesight_mac(low.get("mac")) or len(norm_hex(low.get("mac"))) == 12:
            out["mac"] = norm_hex(low.get("mac"))
        out["sn"] = str(low.get("sn") or low.get("serial") or "") or None
        if isinstance(low.get("model"), str):
            m = _GW_MODEL.search(low["model"])
            out["model"] = m.group(1).upper() if m else None
    else:
        m = re.search(r"(?:gateway\s*eui|gw\s*eui|gateway\s*id|\beui)\W{0,3}((?:[0-9a-f]{2}[\s:\-]?){8})", raw, re.I)
        if m and is_gateway_eui(m.group(1)):
            out["eui"] = norm_hex(m.group(1))
        m = re.search(r"\bmac\W{0,3}((?:[0-9a-f]{2}[\s:\-]?){6})", raw, re.I)
        if m:
            out["mac"] = norm_hex(m.group(1))
        m = re.search(r"(?:\bsn\b|s/n|serial(?:\s*number)?)\s*[:=#]?\s*([0-9A-Za-z\-]{6,24})", raw, re.I)
        if m:
            out["sn"] = m.group(1)
        m = _GW_MODEL.search(raw)
        out["model"] = m.group(1).upper() if m else None
        if out["eui"] is None:
            squeezed = norm_hex(raw) if re.fullmatch(r"[0-9a-fA-F\s:\-]+", raw) else ""
            if is_gateway_eui(squeezed):
                out["eui"] = squeezed
    if out["eui"] is None and out["mac"]:
        out["eui"] = mac_to_eui(out["mac"])
    if out["eui"] is None:
        return None
    if out["mac"] is None:
        out["mac"] = norm_hex(eui_to_mac(out["eui"]))
    return out


def match_expected(expected: dict[str, dict[str, Any]], gid: str, ip: str | None) -> str | None:
    """Which gateway announced beforehand (DHCP / QR) a newly heard gateway is: by EUI, else by IP address (a
    gateway may forward with an EUI from another of its MAC addresses, e.g. Wi-Fi instead of Ethernet)."""
    gid = norm_hex(gid)
    if gid in expected:
        return gid
    if ip:
        hits = [k for k, v in expected.items() if v.get("ip") == ip]
        if len(hits) == 1:
            return hits[0]
    return None
