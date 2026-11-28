"""Compose a DS3604 e-ink 'guest welcome' card from a short-stay booking + the property's display settings.

The device renders its text elements + a QR block at the positions set in its template; this fills them.
Pure (unit-tested) — the websocket layer pushes the result with runtime.async_display().

Block mapping (template 1) — matched to the DS3604's real exported template (text element ids 0‑7), so a
block lands in the box the device drew it in instead of being shuffled. text_N in our downlink == text
element id N‑1 on the device:
  text_1  Welcome, <guest>!            (el 0 — large title)
  text_2  <property name>              (el 1 — top accent, red)
  text_3  Wi-Fi: <ssid>                (el 2)
  text_4  Pass: <password>             (el 3)
  text_5  Check-out                    (el 4 — red banner label, above the QR)
  text_6  Help: <host contact>         (el 5 — small, bottom)
  text_7  <house rules>                (el 6 — tall box; all rules in one wrapped block)
  text_8  <check-out time>             (el 7 — the time under the banner)
  qrcode  WIFI:…                       (scan to join Wi-Fi)

The device only has text elements 0‑7, so nothing is written to text_9 / text_10 (those "block id not
exist" and were what jumbled the earlier card).
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


def _rules(raw: Any, limit: int = 4) -> list[str]:
    if isinstance(raw, list):
        lines = [str(x) for x in raw]
    else:
        lines = str(raw or "").replace("\r", "\n").split("\n")
    out = []
    for ln in lines:
        ln = ln.strip().lstrip("•-* ").strip()
        if ln:
            out.append(ln[:40])
        if len(out) >= limit:
            break
    return out


def _num(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


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
    # Only the 8 text elements the device actually has (0‑7 → text_1‑text_8) + the QR.
    blocks = {k: "" for k in DISPLAY_BLOCKS if k in ("text_1", "text_2", "text_3", "text_4", "text_5", "text_6",
                                                     "text_7", "text_8", "qrcode")}
    blocks["text_1"] = f"Welcome, {name}!"[:40]        # el 0 title
    if prop:
        blocks["text_2"] = prop[:24]                   # el 1 property accent
    if ssid:
        blocks["text_3"] = f"Wi-Fi: {ssid}"[:40]       # el 2
    if pw:
        blocks["text_4"] = f"Pass: {pw}"[:40]          # el 3
    blocks["text_5"] = "Check-out"                     # el 4 banner label (time is its own element)
    if host:
        blocks["text_6"] = f"Help: {host}"[:40]        # el 5
    if rules:
        blocks["text_7"] = "\n".join(rules)[:160]      # el 6 tall box — all rules, one wrapped block
    if checkout:
        blocks["text_8"] = checkout[:12]               # el 7 the time
    qr = wifi_qr(ssid, pw)
    if qr:
        blocks["qrcode"] = qr
    return blocks


def build_warning_template(kind: str | None, value: Any = None, limit: Any = None, config: dict | None = None) -> dict:
    """Blocks for template 2 — the warning screen shown when noise / occupancy goes over the limit.

    Device template-2 text elements (set these up once in the Milesight tool to match):
      text_1  title banner        — "NOTICE" (white on red)
      text_2  headline            — "TOO MUCH NOISE" / "TOO MANY GUESTS"
      text_3  reading             — "82 dB  ·  limit 70"
      text_4  message             — host's note (quiet hours, max guests, …)
      text_5  help / host contact
    """
    c = config or {}
    k = (kind or "custom").lower()
    title = (c.get("warn_title") or "NOTICE").strip()[:18]
    host = (c.get("host_contact") or "").strip()
    msg = (c.get("warn_message") or "").strip()
    if k == "noise":
        headline = "TOO MUCH NOISE"
        reading = (f"{round(float(value))} dB" if value is not None else "")
        if limit is not None:
            reading = (reading + f"  ·  limit {round(float(limit))}").strip("  ·  ")
        if not msg:
            msg = "Please keep it down — quiet hours apply."
    elif k == "occupancy":
        headline = "TOO MANY GUESTS"
        reading = ""
        if value is not None:
            reading = f"{int(value)} inside"
        if limit is not None:
            reading = (reading + f"  ·  max {int(limit)}").strip("  ·  ")
        if not msg:
            msg = "This booking is over its guest limit."
    else:
        headline = (c.get("warn_headline") or "PLEASE TAKE NOTE").strip()[:24]
        reading = ""
    blocks = {k2: "" for k2 in ("text_1", "text_2", "text_3", "text_4", "text_5")}
    blocks["text_1"] = title
    blocks["text_2"] = headline[:24]
    blocks["text_3"] = reading[:28]
    if msg:
        blocks["text_4"] = msg[:120]
    if host:
        blocks["text_5"] = f"Help: {host}"[:40]
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
        "guest_notify": s("guest_notify", 80),    # notify.<service> to alert when the guest presses the button
        "button_target": s("button_target", 80),  # entity to turn on when the button is pressed (relay/chime/script/scene)
        # template 2 — the warning screen
        "warn_title": s("warn_title", 18),
        "warn_headline": s("warn_headline", 24),
        "warn_message": s("warn_message", 120),
        "noise_limit": _num(raw.get("noise_limit")),
        "max_guests": _num(raw.get("max_guests")),
        "noise_source": s("noise_source", 80),        # WS302 entity to watch for auto-switch (else any in the area)
        "warn_auto": 1 if raw.get("warn_auto") else None,  # auto switch to Template 2 when loud, back when quiet
    }
    return {k: v for k, v in out.items() if v is not None} or None
