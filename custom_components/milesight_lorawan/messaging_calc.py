"""In-app team messaging: channels, messages, mentions and unread maths. Pure Python (no Home Assistant imports).

A channel and a message are plain dicts so they store as JSON on the gateway. The Home Assistant layer
(messaging.py) owns the store, the live push and the alert / job system messages; the websocket layer
(messaging_ws.py) is the card's read / send / subscribe API.
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable

HISTORY = 300          # messages kept per channel on the gateway store
PREVIEW = 120          # characters of the last message shown in the channel list
REPLY_ACTION = "MLW_CHAT_REPLY"   # companion-app notification action id for a text-input reply

# The channels every site has. Topic channels are free chat; "alerts" / "jobs" also receive system messages.
FIXED_CHANNELS: list[dict[str, Any]] = [
    {"id": "site", "kind": "topic", "title": "Site", "icon": "mdi:bullhorn-outline"},
    {"id": "maintenance", "kind": "topic", "title": "Maintenance", "icon": "mdi:wrench"},
    {"id": "washroom", "kind": "topic", "title": "Washroom", "icon": "mdi:human-male-female"},
    {"id": "alerts", "kind": "alerts", "title": "Alerts", "icon": "mdi:alert"},
    {"id": "jobs", "kind": "jobs", "title": "Jobs", "icon": "mdi:clipboard-check-outline"},
]


def now() -> float:
    return time.time()


def make_id(existing: Iterable[str] = (), prefix: str = "m") -> str:
    seen = set(existing)
    base = int(now() * 1000)
    n = base
    while f"{prefix}{n}" in seen:
        n += 1
    return f"{prefix}{n}"


def parse_mentions(text: str, names: Iterable[str]) -> list[str]:
    """Display names @mentioned in the text, matched on the first word of each known name (case-insensitive)."""
    tokens = {t.lower() for t in re.findall(r"@([\w'\-]+)", text or "")}
    out = []
    for nm in names:
        first = str(nm or "").strip().split(" ")[0].lower()
        if first and first in tokens and nm not in out:
            out.append(nm)
    return out


def new_message(channel: str, text: str, *, author: str, user_id: str | None = None, role: str = "",
                kind: str = "msg", mentions: list[str] | None = None, image: str | None = None,
                loc: dict | None = None, existing: Iterable[str] = (), ts: float | None = None,
                via: str = "") -> dict[str, Any]:
    msg = {
        "id": make_id(existing), "channel": channel, "ts": round(ts if ts is not None else now(), 3),
        "author": str(author), "user_id": user_id, "role": str(role or ""), "kind": kind,
        "text": str(text), "mentions": mentions or [],
    }
    if via:
        msg["via"] = str(via)
    if image:
        msg["image"] = str(image)
    if loc and loc.get("lat") is not None and loc.get("lon") is not None:
        msg["loc"] = {"lat": round(float(loc["lat"]), 6), "lon": round(float(loc["lon"]), 6)}
    return msg


def preview_text(m: dict[str, Any]) -> str:
    """One-line preview of a message for the channel list (handles photo / location with no text)."""
    if m.get("text"):
        return str(m["text"])
    if m.get("image"):
        return "📷 Photo"
    if m.get("loc"):
        return "📍 Location"
    return ""


def trim(msgs: list[dict[str, Any]], limit: int = HISTORY) -> list[dict[str, Any]]:
    return msgs[-limit:] if len(msgs) > limit else msgs


def unread_count(msgs: list[dict[str, Any]], last_read_ts: float, user_id: str | None) -> int:
    """Messages newer than the viewer's last read that they didn't write (system messages always count)."""
    return sum(1 for m in msgs if m.get("ts", 0) > last_read_ts
               and (m.get("kind") == "sys" or m.get("user_id") != user_id))


def channel_summary(channel: dict[str, Any], msgs: list[dict[str, Any]], last_read_ts: float,
                    user_id: str | None) -> dict[str, Any]:
    last = msgs[-1] if msgs else None
    preview = None
    if last is not None:
        who = "" if last.get("kind") == "sys" else f"{last.get('author', '')}: "
        preview = (who + preview_text(last))[:PREVIEW]
    return {**channel, "last_text": preview, "last_ts": last.get("ts") if last else None,
            "unread": unread_count(msgs, last_read_ts, user_id)}


def channel_readers(read_map: dict[str, float], users: dict[str, str], exclude_id: str | None) -> list[dict[str, Any]]:
    """Each other participant's last-read time in a channel, for read receipts (name + ts), most recent first."""
    out = [{"name": users.get(uid) or "Someone", "ts": ts}
           for uid, ts in (read_map or {}).items() if uid and uid != exclude_id and ts]
    out.sort(key=lambda r: -r["ts"])
    return out


def channel_sort_key(c: dict[str, Any]) -> tuple:
    # fixed topics first (in their listed order), then alert / job threads by most-recent activity
    order = {cid["id"]: i for i, cid in enumerate(FIXED_CHANNELS)}
    return (0, order[c["id"]]) if c["id"] in order else (1, -(c.get("last_ts") or 0))
