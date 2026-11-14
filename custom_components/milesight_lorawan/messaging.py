"""In-app team messaging manager: channels + message history stored on the gateway, live push over a dispatcher
signal, optional push to phones, and system messages from the Alerts and Jobs engines. One per gateway hub."""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from . import messaging_calc as mc
from .const import DOMAIN, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

SIGNAL_CHAT = f"{DOMAIN}_chat_{{}}"       # .format(hub entry_id) – fired on every new message / channel change


class MessagingManager:
    """Channels, messages and read-state for one site, persisted to the gateway store."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.chat_{entry.entry_id}")
        self.channels: dict[str, dict[str, Any]] = {c["id"]: dict(c) for c in mc.FIXED_CHANNELS}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.read: dict[str, dict[str, float]] = {}        # user_id -> {channel_id: last_read_ts}
        self.users: dict[str, str] = {}                    # user_id -> display name (for read receipts)
        self._posted_alerts: set[str] = set()              # alert_ids already announced (avoid repeats on escalation)
        self._online: dict[str, dict[str, Any]] = {}       # user_id -> {name, n (open chat views), since} – live presence

    async def async_load(self) -> None:
        saved = await self.store.async_load() or {}
        for c in saved.get("channels", []):
            self.channels[c["id"]] = {**self.channels.get(c["id"], {}), **c}
        self.messages = {k: v for k, v in (saved.get("messages") or {}).items()}
        self.read = saved.get("read") or {}
        self.users = saved.get("users") or {}
        self._posted_alerts = set(saved.get("posted_alerts") or [])

    def _save(self) -> None:
        self.store.async_delay_save(lambda: {
            "channels": self._persist_channels(),
            "messages": self.messages, "read": self.read, "users": self.users,
            "posted_alerts": sorted(self._posted_alerts)[-500:],
        }, 15)

    def _persist_channels(self) -> list[dict[str, Any]]:
        """Persist every channel that isn't a pristine built-in: created channels (alert/job/device/custom topics)
        and any built-in that's been renamed, re-iconed or archived. Pristine built-ins are re-seeded on load."""
        fixed = {c["id"]: c for c in mc.FIXED_CHANNELS}
        out = []
        for c in self.channels.values():
            d = fixed.get(c["id"])
            if d is None or c.get("archived") or c.get("title") != d.get("title") or c.get("icon") != d.get("icon"):
                out.append(c)
        return out

    # ------------------------------------------------------------------ reads
    def _all_ids(self) -> set[str]:
        return {m["id"] for msgs in self.messages.values() for m in msgs}

    def worker_names(self) -> list[str]:
        team = getattr(getattr(self.entry, "runtime_data", None), "team", None)
        if team is None:
            return []
        return [w.get("name") for w in (team.data.get("workers") or []) if w.get("name")]

    def _channel_read(self, channel: str) -> dict[str, float]:
        return {uid: (self.read.get(uid, {}) or {}).get(channel, 0) for uid in self.users}

    def clocked_in_names(self) -> set[str]:
        """Worker names currently on-site per the Team clock-in / geofence (for the presence 'clocked-in' badge)."""
        team = getattr(getattr(self.entry, "runtime_data", None), "team", None)
        rows = (getattr(team, "data", {}) or {}).get("workers") or []
        return {r.get("name") for r in rows if r.get("on_site") and r.get("name")}

    def online_list(self) -> list[dict[str, Any]]:
        return [{"user_id": uid, "name": e["name"], "since": e["since"]} for uid, e in self._online.items()]

    def _roster(self) -> list[dict[str, Any]]:
        """Everyone who matters for presence: each worker with online + clocked-in flags, plus any online
        Home Assistant user who isn't a worker (a 'guest' — e.g. the manager on a laptop)."""
        online = self.online_list()
        online_names = {o["name"].lower() for o in online}
        clocked = self.clocked_in_names()
        workers = self.worker_names()
        roster = [{"name": n, "online": n.lower() in online_names, "clocked_in": n in clocked} for n in workers]
        wn = {n.lower() for n in workers}
        for o in online:
            if o["name"].lower() not in wn:
                roster.append({"name": o["name"], "online": True, "clocked_in": False, "guest": True})
        return roster

    def snapshot(self, user_id: str | None, channel: str | None = None, *, is_admin: bool = False) -> dict[str, Any]:
        chans = [mc.channel_summary(c, self.messages.get(c["id"], []),
                                    (self.read.get(user_id or "", {}) or {}).get(c["id"], 0), user_id)
                 for c in self.channels.values()
                 if is_admin or not c.get("archived")]        # archived channels are admin-only
        chans.sort(key=mc.channel_sort_key)
        out: dict[str, Any] = {"hub": self.entry.entry_id, "channels": chans,
                               "workers": self.worker_names(), "me": user_id,
                               "roster": self._roster(), "online": self.online_list(),
                               "can_manage": bool(is_admin)}
        if channel is not None:
            out["channel"] = channel
            out["messages"] = self.messages.get(channel, [])
            out["readers"] = mc.channel_readers(self._channel_read(channel), self.users, user_id)
        return out

    # ------------------------------------------------------------------ presence (who's in chat now) + typing
    def presence_add(self, user_id: str | None, name: str | None) -> None:
        if not user_id:
            return
        e = self._online.get(user_id)
        if e:
            e["n"] += 1
            if name:
                e["name"] = name
        else:
            self._online[user_id] = {"name": name or "User", "n": 1, "since": mc.now()}
            self._broadcast_presence()

    def presence_drop(self, user_id: str | None) -> None:
        e = self._online.get(user_id) if user_id else None
        if not e:
            return
        e["n"] -= 1
        if e["n"] <= 0:
            self._online.pop(user_id, None)
            self._broadcast_presence()

    def _broadcast_presence(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_CHAT.format(self.entry.entry_id),
                              {"presence": {"online": self.online_list(), "roster": self._roster()}})

    def typing(self, user_id: str | None, name: str, channel: str) -> None:
        """Ephemeral 'X is typing…' ping – broadcast live, never stored."""
        if channel not in self.channels:
            return
        async_dispatcher_send(self.hass, SIGNAL_CHAT.format(self.entry.entry_id),
                              {"typing": {"channel": channel, "user_id": user_id,
                                          "name": name or "Someone", "ts": mc.now()}})

    # ------------------------------------------------------------------ writes
    def ensure_channel(self, cid: str, *, kind: str, title: str, icon: str, meta: dict | None = None) -> dict[str, Any]:
        c = self.channels.get(cid)
        if c is None:
            c = {"id": cid, "kind": kind, "title": title, "icon": icon, **({"meta": meta} if meta else {})}
            self.channels[cid] = c
            self._save()
        return c

    def _unique_cid(self, kind: str, title: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-") or kind
        cid, i = f"{kind}:{base}", 2
        while cid in self.channels:
            cid, i = f"{kind}:{base}-{i}", i + 1
        return cid

    def _broadcast_channels(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_CHAT.format(self.entry.entry_id), {"channels_changed": True})

    def create_channel(self, title: str, *, icon: str = "mdi:pound", kind: str = "topic") -> dict[str, Any] | None:
        title = (title or "").strip()
        if not title:
            return None
        c = {"id": self._unique_cid(kind, title), "kind": kind, "title": title, "icon": icon}
        self.channels[c["id"]] = c
        self._save()
        self._broadcast_channels()
        return c

    def rename_channel(self, cid: str, title: str) -> dict[str, Any] | None:
        c, title = self.channels.get(cid), (title or "").strip()
        if c is None or not title:
            return None
        c["title"] = title
        self._save()
        self._broadcast_channels()
        return c

    def archive_channel(self, cid: str, archived: bool = True) -> dict[str, Any] | None:
        c = self.channels.get(cid)
        if c is None or c.get("kind") in ("alerts", "jobs"):   # the alert / job streams are never archived away
            return None
        if archived:
            c["archived"] = True
        else:
            c.pop("archived", None)
        self._save()
        self._broadcast_channels()
        return c

    def ensure_device_channel(self, device_id: str, name: str | None) -> dict[str, Any] | None:
        """Open (creating if needed) the discussion channel scoped to one device, from its 'Discuss' button."""
        device_id = str(device_id or "").strip()
        if not device_id:
            return None
        cid = f"dev:{device_id}"
        c = self.channels.get(cid)
        if c is None:
            c = {"id": cid, "kind": "device", "title": (name or device_id),
                 "icon": "mdi:radio-tower", "meta": {"device_id": device_id}}
            self.channels[cid] = c
            self._save()
            self._broadcast_channels()
        elif c.get("archived") or (name and c.get("title") != name):
            c.pop("archived", None)
            if name:
                c["title"] = name
            self._save()
            self._broadcast_channels()
        return c

    def post(self, channel: str, text: str, *, author: str, user_id: str | None = None, role: str = "",
             kind: str = "msg", push: bool = False, image: str | None = None,
             loc: dict | None = None, via: str = "") -> dict[str, Any] | None:
        text = (text or "").strip()
        if (not text and not image and not loc) or channel not in self.channels:
            return None
        if user_id:
            self.users[user_id] = author
        mentions = mc.parse_mentions(text, self.worker_names()) if kind == "msg" else []
        msg = mc.new_message(channel, text, author=author, user_id=user_id, role=role, kind=kind,
                             mentions=mentions, image=image, loc=loc, existing=self._all_ids(), via=via)
        self.messages.setdefault(channel, [])
        self.messages[channel] = mc.trim(self.messages[channel] + [msg])
        if user_id:                                        # the author has implicitly read their own channel
            self.read.setdefault(user_id, {})[channel] = msg["ts"]
        self._save()
        async_dispatcher_send(self.hass, SIGNAL_CHAT.format(self.entry.entry_id),
                              {"channel": channel, "message": msg, "channel_meta": self.channels[channel]})
        if kind == "msg":
            # Broadcast to every phone when asked; always ping the phones of anyone @mentioned.
            targets: list[str] = list(self._notify_targets()) if push else []
            for t in self._mention_targets(mentions):
                if t not in targets:
                    targets.append(t)
            if targets:
                self.hass.async_create_task(self._push(channel, author, mc.preview_text(msg), targets))
        return msg

    def mark_read(self, user_id: str, channel: str, name: str | None = None) -> None:
        if name:
            self.users[user_id] = name
        msgs = self.messages.get(channel) or []
        ts = msgs[-1]["ts"] if msgs else mc.now()
        self.read.setdefault(user_id, {})[channel] = ts
        self._save()
        async_dispatcher_send(self.hass, SIGNAL_CHAT.format(self.entry.entry_id),
                              {"read": {"channel": channel, "user_id": user_id,
                                        "name": self.users.get(user_id) or "Someone", "ts": ts}})

    async def save_image(self, data_url: str) -> str | None:
        """Decode a small base64 image from the composer, write it under config/www, return its /local URL."""
        import base64
        import os
        m = re.match(r"data:image/(png|jpe?g|webp);base64,(.+)$", data_url or "", re.S)
        if not m:
            return None
        ext = "jpg" if m.group(1).startswith("jpe") else m.group(1)
        try:
            raw = base64.b64decode(m.group(2))
        except Exception:  # noqa: BLE001
            return None
        if len(raw) > 4_000_000:                           # cap at ~4 MB after client-side downscale
            return None
        name = f"{mc.make_id(prefix='img')}.{ext}"
        folder = self.hass.config.path("www", "milesight_chat")

        def _write() -> None:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, name), "wb") as f:
                f.write(raw)

        await self.hass.async_add_executor_job(_write)
        return f"/local/milesight_chat/{name}"

    # ------------------------------------------------------------------ push to phones
    async def _push(self, channel: str, author: str, text: str, targets: list[str]) -> None:
        """Send an actionable push to each target so a reply typed on the phone comes straight back into the thread."""
        title = f"{author} · {self.channels.get(channel, {}).get('title', 'Team chat')}"
        data = {
            "chat_channel": channel,                   # echoed back on the notification action, routes the reply
            "chat_hub": self.entry.entry_id,
            "tag": f"mlw-chat-{channel}",              # replies to the same channel collapse into one thread
            "group": f"mlw-chat-{self.entry.entry_id}",
            "actions": [{"action": mc.REPLY_ACTION, "title": "Reply",
                         "behavior": "textInput", "textInputButtonTitle": "Send"}],
            "push": {"category": mc.REPLY_ACTION},     # iOS: dynamic reply category
        }
        for service in targets:
            try:
                await self.hass.services.async_call(
                    "notify", service.removeprefix("notify."),
                    {"title": title, "message": text, "data": data}, blocking=False)
            except Exception:  # noqa: BLE001 - a missing phone target must not drop the message
                _LOGGER.debug("Could not push chat to %s", service, exc_info=True)

    def _notify_targets(self) -> list[str]:
        """Every registered mobile-app notifier (so a team broadcast reaches everyone's phone)."""
        try:
            return [f"notify.{s}" for s in self.hass.services.async_services().get("notify", {})
                    if s.startswith("mobile_app_")]
        except Exception:  # noqa: BLE001
            return []

    def _mention_targets(self, mentions: list[str]) -> list[str]:
        """Resolve @mentioned workers to their push targets, so a mention pings that person even with push off."""
        if not mentions:
            return []
        try:
            from .jobs import _assignable_people
            by_name = {p["name"].lower(): p.get("notify")
                       for p in _assignable_people(self.hass, self.entry)}
        except Exception:  # noqa: BLE001
            return []
        out: list[str] = []
        for m in mentions:
            t = by_name.get(str(m).strip().lower())
            if t and t not in out:
                out.append(t)
        return out

    # ------------------------------------------------------------------ reply from the phone (2-way push)
    @callback
    def on_mobile_action(self, event) -> None:
        """A companion-app notification reply: post it into its channel as the phone's owner."""
        d = event.data or {}
        if d.get("action") != mc.REPLY_ACTION:
            return
        if d.get("chat_hub") not in (None, self.entry.entry_id):
            return                                      # a different site's hub owns this notification
        reply = str(d.get("reply_text") or d.get("reply") or "").strip()
        channel = d.get("chat_channel")
        if not reply or not channel or channel not in self.channels:
            return
        uid = getattr(getattr(event, "context", None), "user_id", None)
        self.hass.async_create_task(self._post_phone_reply(channel, reply, uid))

    async def _post_phone_reply(self, channel: str, reply: str, uid: str | None) -> None:
        author, user_id = "Phone", None
        if uid:
            try:
                user = await self.hass.auth.async_get_user(uid)
                if user and user.name:
                    author, user_id = user.name, uid
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Could not resolve phone reply author %s", uid, exc_info=True)
        self.post(channel, reply, author=author, user_id=user_id, kind="msg", push=True, via="phone")

    # ------------------------------------------------------------------ system messages from alerts / jobs
    @callback
    def on_alert(self, event) -> None:
        d = event.data or {}
        aid = d.get("alert_id")
        if not aid or aid in self._posted_alerts:
            return
        self._posted_alerts.add(aid)
        title = d.get("title") or d.get("key") or "Alert"
        sev = d.get("severity") or d.get("kind") or ""
        self.post("alerts", f"{title}{(' · ' + sev) if sev else ''}", author="Alerts", kind="sys")

    @callback
    def on_job(self, title: str) -> None:
        self.post("jobs", title, author="Jobs", kind="sys")
