"""Commissioning mode for installers (pure helpers, unit-tested): read a device's QR code, summarise a walk test.
The Home Assistant side (panel, websocket commands) is in commissioning_ws.py."""
from __future__ import annotations

import json
import re
import statistics
from typing import Any

from .link import link_margin, link_quality

MILESIGHT_OUI = "24e124"
_HEX16 = re.compile(r"(?<![0-9a-f])([0-9a-f]{16})(?![0-9a-f])")
_HEX32 = re.compile(r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])")
_LABELS = {
    "deveui": r"(?:dev\s*_?eui|device\s*eui|\beui)",
    "app_key": r"(?:app\s*_?key|application\s*key|\bkey\b|\bak\b)",
    "join_eui": r"(?:app\s*_?eui|join\s*_?eui)",
    "sn": r"(?:\bsn\b|s/n|serial(?:\s*number)?)",
    "model": r"(?:\bmodel\b|\bpn\b|product)",
}


def _hex(value: Any, length: int) -> str | None:
    if not isinstance(value, str):
        return None
    v = re.sub(r"[\s:\-]", "", value).lower()
    return v if re.fullmatch(rf"[0-9a-f]{{{length}}}", v) else None


def parse_qr(text: str, guess_model=None) -> dict[str, Any]:
    """What a device label's QR code says: DevEUI, AppKey, JoinEUI, serial number and model (when present).
    Understands LoRa Alliance TR005 codes (LW:D0:…), JSON, 'DevEUI: … AppKey: …' text and bare hex.
    guess_model(text) -> model key, for model names written in the code."""
    raw = (text or "").strip()
    out: dict[str, Any] = {"raw": raw, "deveui": None, "app_key": None, "join_eui": None, "sn": None,
                           "model": None, "format": None}
    if not raw:
        return out
    if raw.upper().startswith("LW:"):                       # LoRa Alliance TR005
        parts = raw.split(":")
        if len(parts) >= 4:
            out.update(format="tr005", join_eui=_hex(parts[2], 16), deveui=_hex(parts[3], 16))
            for p in parts[5:]:
                if p[:1].upper() == "S" and len(p) > 1:
                    out["sn"] = p[1:]
    if out["deveui"] is None:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            low = {re.sub(r"[\s_\-]", "", str(k)).lower(): v for k, v in data.items()}
            out["format"] = "json"
            out["deveui"] = _hex(low.get("deveui") or low.get("eui") or low.get("deviceeui"), 16)
            out["app_key"] = _hex(low.get("appkey") or low.get("applicationkey"), 32)
            out["join_eui"] = _hex(low.get("joineui") or low.get("appeui"), 16)
            out["sn"] = str(low["sn"]) if low.get("sn") else (str(low["serial"]) if low.get("serial") else None)
            if isinstance(low.get("model"), str) and guess_model:
                out["model"] = guess_model(low["model"])
    low = raw.lower()
    if out["deveui"] is None:                               # labelled text: "DevEUI: 24E1… AppKey: …"
        for key, label in _LABELS.items():
            if out.get(key):
                continue
            n = 32 if key == "app_key" else 16
            if key in ("sn", "model"):
                m = re.search(label + r"\s*[:=#]?\s*([0-9A-Za-z\-]{4,24})", raw, re.I)
                if m and key == "sn":
                    out["sn"] = m.group(1)
                elif m and guess_model:
                    out["model"] = guess_model(m.group(1)) or out["model"]
                continue
            m = re.search(label + r"\W{0,3}((?:[0-9a-f]{2}[\s:\-]?){%d})" % (n // 2), low, re.I)
            if m:
                out[key] = _hex(m.group(1), n)
        if out["deveui"]:
            out["format"] = out["format"] or "text"
    if out["deveui"] is None:                               # bare hex: prefer a Milesight EUI
        squeezed = re.sub(r"[\s:\-]", "", low)
        if re.fullmatch(r"[0-9a-f]{16}", squeezed):
            out.update(deveui=squeezed, format=out["format"] or "hex")
        elif re.fullmatch(r"[0-9a-f]{48}", squeezed):         # DevEUI followed by AppKey
            out.update(deveui=squeezed[:16], app_key=squeezed[16:], format=out["format"] or "hex")
        else:
            euis = sorted(_HEX16.findall(low), key=lambda e: not e.startswith(MILESIGHT_OUI))
            if euis:
                out.update(deveui=euis[0], format=out["format"] or "hex")
            keys = _HEX32.findall(low)
            if keys and out["app_key"] is None:
                out["app_key"] = keys[0]
    if out["model"] is None and guess_model:
        out["model"] = guess_model(raw)
    return out


def sample(up: Any, duplicate: bool = False, now: float | None = None) -> dict[str, Any]:
    """One walk-test point from an uplink (decoders.Uplink)."""
    best = up.gateways[0] if getattr(up, "gateways", None) else {}
    rssi = up.rssi if up.rssi is not None else best.get("rssi")
    snr = up.snr if up.snr is not None else best.get("snr")
    return {"ts": now, "fcnt": up.fcnt, "rssi": rssi, "snr": snr, "sf": up.sf,
            "quality": link_quality(rssi, snr, up.sf), "margin": link_margin(snr, up.sf),
            "gateways": [{"name": g.get("name") or g.get("id"), "rssi": g.get("rssi"), "snr": g.get("snr")}
                         for g in (getattr(up, "gateways", None) or [])],
            "duplicate": duplicate}


ORDER = ["poor", "fair", "good", "excellent"]


def walk_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Best / worst / median of a walk test and a verdict (the worst point decides)."""
    pts = [s for s in samples if not s.get("duplicate") and (s.get("rssi") is not None or s.get("snr") is not None)]
    if not pts:
        return {"count": 0, "verdict": None}

    def stat(key: str) -> dict[str, float] | None:
        vals = [s[key] for s in pts if isinstance(s.get(key), (int, float))]
        if not vals:
            return None
        return {"min": min(vals), "max": max(vals), "median": round(statistics.median(vals), 1)}
    qualities = [s["quality"] for s in pts if s.get("quality") in ORDER]
    worst = min(qualities, key=ORDER.index) if qualities else None
    gateways = sorted({g["name"] for s in pts for g in s.get("gateways", []) if g.get("name")})
    sfs = sorted({s["sf"] for s in pts if s.get("sf")})
    return {"count": len(pts), "rssi": stat("rssi"), "snr": stat("snr"), "margin": stat("margin"),
            "spreading_factors": sfs, "gateways": gateways, "verdict": worst,
            "advice": {"excellent": "Strong link – mount it here.", "good": "Good link – mount it here.",
                       "fair": "Usable, little margin – try a higher or more open spot if you can.",
                       "poor": "Too weak – move the device, raise it, or add a gateway closer by.",
                       None: "No signal data yet."}[worst]}


def fast_interval(spec: dict[str, Any]) -> tuple[int, str]:
    """Shortest sensible reporting interval for a walk test (1 minute, or the device's minimum) and its unit."""
    unit = spec.get("unit", "s")
    want = 1 if unit == "min" else 60
    return max(int(spec.get("min", want) or want), want), unit


def default_interval(unit: str) -> int:
    """Milesight's usual factory reporting interval (10 minutes) in the spec's unit."""
    return 10 if unit == "min" else 600
