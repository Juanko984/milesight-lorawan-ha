"""Compose a DS3604 e-ink 'guest welcome' card from a short-stay booking + the property's display settings.

The device renders text_1…text_10 + a QR block at the positions set in its template; this fills those blocks.
Pure (unit-tested) — the websocket layer pushes the result with runtime.async_display().

Default block mapping (template 1), matching a typical welcome layout:
  text_1  Welcome, <guest>!            (large title)
  text_2  <property name>              (top-right accent)
  text_3  Wi-Fi: <ssid>
  text_4  Pass: <password>
  text_5  Check-out <time>             (accent banner, above the QR)
  text_6  Help: <host contact>         (small, bottom-right)
  text_8  house rule 1
  text_9  house rule 2
  text_10 house rule 3
  qrcode  WIFI:…  (scan to join Wi-Fi)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

DISPLAY_BLOCKS = tuple(f"text_{n}" for n in range(1, 11)) + ("qrcode",)


def wifi_qr(ssid: str | None, password: str | None, auth: str = "WPA", hidden: bool = False) -> str | None:
    """A standard Wi-Fi join QR payload: WIFI:T:WPA;S:ssid;P:pass;;  (escaping \\ ; , : \" )."""
    if not ssid:
        return None
    def esc(s: str) -> str:
        out = s
        for ch in ("\\", ";", ",", ":", '"'):
            out = out.replace(ch, "\\" + ch)
        return out
    a = (auth or "WPA").upper()
    if not password:
        a = "nopass"
    parts = [f"T:{a}", f"S:{esc(ssid)}"]
    if password and a != "nopass":
        parts.append(f"P:{esc(password)}")
    if hidden:
        parts.append("H:true")
    return "WIFI:" + ";".join(parts) + ";;"


def _rules(raw: Any, limit: int = 3) -> list[str]:
    if isinstance(raw, list):
        lines = [str(x) for x in raw]
    else:
        lines = str(raw or "").replace("\r", "\n").split("\n")
    out = []
    for ln in lines:
        ln = ln.strip().lstrip("•-* ").strip()
        if ln:
            out.append(("• " + ln)[:40])
        if len(out) >= limit:
            break
    return out


def _time_of(iso: str | None) -> str | None:
    if not iso or "T" not in str(iso):
        return None
    try:
        return datetime.fromisoformat(str(iso)[:16]).strftime("%H:%M")
    except ValueError:
        return None


def build_welcome_template(booking: dict | None, config: dict | None) -> dict:
    """Return the full set of DS3604 blocks for a guest welcome card (empty string clears an unused block)."""
    b = booking or {}
    c = config or {}
    name = (b.get("name") or "").strip() or "Guest"
    checkout = (c.get("checkout_time") or "").strip() or _time_of(b.get("departure")) or ""
    ssid = (c.get("wifi_ssid") or "").strip()
    pw = (c.get("wifi_pass") or "").strip()
    host = (c.get("host_contact") or "").strip()
    prop = (c.get("property_name") or "").strip()
    rules = _rules(c.get("house_rules"))
    blocks = {k: "" for k in DISPLAY_BLOCKS}
    blocks["text_1"] = f"Welcome, {name}!"[:40]
    if prop:
        blocks["text_2"] = prop[:24]
    if ssid:
        blocks["text_3"] = f"Wi-Fi: {ssid}"[:40]
    if pw:
        blocks["text_4"] = f"Pass: {pw}"[:40]
    if checkout:
        blocks["text_5"] = f"Check-out {checkout}"[:24]
    if host:
        blocks["text_6"] = f"Help: {host}"[:40]
    for i, r in enumerate(rules):
        blocks[f"text_{8 + i}"] = r
    qr = wifi_qr(ssid, pw)
    if qr:
        blocks["qrcode"] = qr
    return blocks


def clean_display_config(raw: Any) -> dict | None:
    """Validate the per-property display settings the host enters."""
    if not isinstance(raw, dict):
        return None
    def s(k, n):
        v = raw.get(k)
        return v.strip()[:n] if isinstance(v, str) and v.strip() else None
    out = {
        "property_name": s("property_name", 40),
        "wifi_ssid": s("wifi_ssid", 60),
        "wifi_pass": s("wifi_pass", 60),
        "house_rules": s("house_rules", 400),
        "host_contact": s("host_contact", 60),
        "checkout_time": s("checkout_time", 12),
    }
    return {k: v for k, v in out.items() if v is not None} or None
