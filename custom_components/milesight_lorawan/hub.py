"""Gateway hub: subscribes to the uplink topic and routes / discovers devices."""
from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.components import mqtt
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVEUI,
    CONF_DOWNLINK_FORMAT,
    CONF_DOWNLINK_TOPIC,
    CONF_EXTRA_TOPICS,
    CONF_GATEWAY_OFFLINE_MIN,
    DEFAULT_GATEWAY_OFFLINE_MIN,
    SIGNAL_GATEWAY,
    SIGNAL_GATEWAY_NEW,
    SIGNAL_NOTIFY,
    STORAGE_VERSION,
    CONF_PAYLOAD_ENCODING,
    CONF_TOPIC,
    DEFAULT_DOWNLINK_TOPIC,
    DOMAIN,
    DOWNLINK_CHIRPSTACK,
    DOWNLINK_FPORT,
    DOWNLINK_MILESIGHT,
    ENCODING_BASE64,
    SIGNAL_UPLINK,
)
from .decoders import Uplink, parse_envelope, parse_notification
from .link import GatewayStats
from .models import guess_from_name, guess_model

_LOGGER = logging.getLogger(__name__)


class Hub:
    """One gateway / MQTT uplink topic."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        cfg = {**entry.data, **entry.options}
        self.topic: str = cfg[CONF_TOPIC]
        self.encoding: str = cfg.get(CONF_PAYLOAD_ENCODING, ENCODING_BASE64)
        self.downlink_topic: str = cfg.get(CONF_DOWNLINK_TOPIC) or DEFAULT_DOWNLINK_TOPIC
        self.downlink_format: str = cfg.get(CONF_DOWNLINK_FORMAT, DOWNLINK_MILESIGHT)
        self.extra_topics: list[str] = [t.strip() for t in str(cfg.get(CONF_EXTRA_TOPICS) or "").split(",")
                                        if t.strip() and t.strip() != self.topic]
        self.offline_s: float = float(cfg.get(CONF_GATEWAY_OFFLINE_MIN, DEFAULT_GATEWAY_OFFLINE_MIN)) * 60
        self.last_uplink: dict[str, Uplink] = {}
        self._announced: set[str] = set()
        self._unsubs: list[Callable[[], None]] = []
        self.store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.hub_{entry.entry_id}")
        self.stats = GatewayStats()
        self._online: dict[str, bool | None] = {}
        self._last_push = 0.0

    async def async_start(self) -> None:
        self.stats = GatewayStats(await self.store.async_load())
        self._online = {gid: self.stats.online(gid, time.time(), self.offline_s) for gid in self.stats.gateways}
        for topic in [self.topic, *self.extra_topics]:
            self._unsubs.append(await mqtt.async_subscribe(self.hass, topic, self._message_received, qos=0))
            _LOGGER.debug("Subscribed to %s", topic)
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=60)))

    async def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        await self.store.async_save(self.stats.to_dict())

    def _day(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
                                      ).date().isoformat()

    def _changed(self, new: list[str] | bool = (), force: bool = False) -> None:
        """Refresh gateway entities – at most every 30 s for plain traffic (the 60 s tick catches up)."""
        for gid in new if isinstance(new, list) else []:
            async_dispatcher_send(self.hass, SIGNAL_GATEWAY_NEW.format(self.entry.entry_id), gid)
        now = time.monotonic()
        if force or new or now - self._last_push >= 30:
            self._last_push = now
            async_dispatcher_send(self.hass, SIGNAL_GATEWAY.format(self.entry.entry_id))
        self.store.async_delay_save(self.stats.to_dict, 60)

    @callback
    def _tick(self, _now: Any = None) -> None:
        ts = time.time()
        self.stats.count("uplinks", self._day(ts), 0)        # roll the day over at midnight
        for gid, g in self.stats.gateways.items():
            online = self.stats.online(gid, ts, self.offline_s)
            if online is not None and self._online.get(gid) is not None and online != self._online[gid]:
                self.hass.bus.async_fire(f"{DOMAIN}_gateway_{'online' if online else 'offline'}", {
                    "gateway_id": gid, "gateway": g.get("name"), "hub": self.entry.title})
            self._online[gid] = online
        self._changed(force=True)

    async def async_send_downlink(self, deveui: str, payload: bytes, fport: int = DOWNLINK_FPORT,
                                  confirmed: bool = False) -> None:
        """Queue a downlink via the gateway (Milesight or ChirpStack MQTT format)."""
        topic = (self.downlink_topic.replace("{deveui}", deveui.lower()).replace("{DEVEUI}", deveui.upper())
                 .replace("$deveui", deveui.lower()))
        msg = {"confirmed": bool(confirmed), "fPort": fport, "data": base64.b64encode(payload).decode()}
        if self.downlink_format == DOWNLINK_CHIRPSTACK:
            msg = {"devEui": deveui.lower(), **msg}
        _LOGGER.debug("Downlink to %s on %s: %s", deveui, topic, payload.hex())
        await mqtt.async_publish(self.hass, topic, json.dumps(msg), qos=0)
        self.stats.count("downlinks", self._day(time.time()))
        self._changed()

    def forget(self, deveui: str) -> None:
        """Allow a removed device to be discovered again."""
        self._announced.discard(deveui)

    def _notification(self, note: dict[str, Any]) -> None:
        ts = time.time()
        day = self._day(ts)
        kind = note["kind"]
        new: list[str] = []
        if kind in ("ack", "join", "error"):
            self.stats.count({"ack": "acks" if note.get("acknowledged") else "nacks", "join": "joins",
                              "error": "errors"}[kind], day)
            async_dispatcher_send(self.hass, SIGNAL_NOTIFY.format(note["deveui"]), note)
        elif kind == "gateway_info":
            if self.stats.info(note["gateway_id"], ts, note["info"]):
                new.append(note["gateway_id"])
        elif kind == "gateway_stats":
            if self.stats.stats(note["gateway_id"], ts, day, note.get("rx_ok") or note.get("rx_received"),
                                note.get("tx_emitted")):
                new.append(note["gateway_id"])
        elif kind == "gateway_state":
            if self.stats.state(note["gateway_id"], ts, note["online"]):
                new.append(note["gateway_id"])
        self._changed(new, force=True)

    @callback
    def _message_received(self, msg: mqtt.ReceiveMessage) -> None:
        note = parse_notification(msg.payload)
        if note is not None:
            self._notification(note)
            return
        up = parse_envelope(msg.payload, self.encoding)
        if up is None:
            return
        prev = self.last_uplink.get(up.deveui)
        duplicate = (prev is not None and up.fcnt is not None and prev.fcnt == up.fcnt
                     and prev.raw == up.raw and abs(time.time() - prev.extra.get("_rx", 0)) < 30)
        up.extra["_rx"] = time.time()
        self.last_uplink[up.deveui] = up
        self._changed(self.stats.uplink(self._day(up.extra["_rx"]), up.extra["_rx"], up.deveui, up.gateways,
                                        duplicate))

        if self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, up.deveui):
            async_dispatcher_send(self.hass, SIGNAL_UPLINK.format(up.deveui), up)
            return

        if up.deveui in self._announced:
            return
        self._announced.add(up.deveui)
        best, candidates = guess_model(up.raw)
        named = guess_from_name(up.device_name)
        if named:                        # model named in the gateway's device name wins
            best, candidates = named, [named] + [c for c in candidates if c != named]
        _LOGGER.info("Discovered new LoRaWAN device %s (guess: %s)", up.deveui, best)
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={
                    CONF_DEVEUI: up.deveui,
                    "guess": best,
                    "candidates": candidates,
                    "device_name": up.device_name,
                },
            )
        )
