"""Built-in network server, Home Assistant side: a UDP endpoint for the gateways' Semtech packet forwarders.

Gateway (Packet Forwarder → Multi-Destination → Semtech, server = Home Assistant, ports 1700) ─UDP→ here →
lns.server.NetworkServer (joins, MIC, de-duplication, frame counters) → the hub's normal uplink path (decoders,
entities, dashboards). Downlinks for devices joined here are queued in the network server and sent through the
best gateway in the device's RX1 window. Keys come from the device entries (lns_app_key) and stay in Home
Assistant's storage; logs and diagnostics never show them."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (CONF_DEVEUI, CONF_LNS_APP_KEY, CONF_LNS_FARM_ID, CONF_LNS_JOIN_EUI, CONF_LNS_PORT,
                    CONF_LNS_REGION, CONF_LNS_RX1_DELAY, DEFAULT_LNS_PORT, DEFAULT_LNS_RX1_DELAY, DOMAIN,
                    SIGNAL_GATEWAY, STORAGE_VERSION)
from .decoders import Uplink
from .lns import semtech
from .lns.region import REGIONS
from .lns.server import DeviceKeys, Event, NetworkServer, Settings

if TYPE_CHECKING:
    from .hub import Hub

_LOGGER = logging.getLogger(__name__)
SIGNAL_LNS = f"{DOMAIN}_lns_{{}}"          # .format(hub entry_id)
UNKNOWN_JOIN_REPEAT_S = 3600


def keys_from_entries(hass: HomeAssistant):
    """DevEUI → DeviceKeys from the device entries that have an AppKey for the built-in network server."""
    def lookup(dev_eui: str) -> DeviceKeys | None:
        entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, dev_eui.lower())
        key = (entry.data.get(CONF_LNS_APP_KEY) if entry is not None else None) or ""
        try:
            raw = bytes.fromhex(key)
        except ValueError:
            return None
        if len(raw) != 16:
            return None
        return DeviceKeys(dev_eui.lower(), raw, (entry.data.get(CONF_LNS_JOIN_EUI) or None))
    return lookup


def settings_from(cfg: dict[str, Any]) -> Settings:
    return Settings(region=REGIONS.get(cfg.get(CONF_LNS_REGION) or "EU868", REGIONS["EU868"]),
                    farm_id=int(cfg.get(CONF_LNS_FARM_ID) or 0) & 0x1FF,
                    rx1_delay=max(1, min(15, int(cfg.get(CONF_LNS_RX1_DELAY) or DEFAULT_LNS_RX1_DELAY))))


class LnsTransport(asyncio.DatagramProtocol):
    def __init__(self, hass: HomeAssistant, hub: "Hub", cfg: dict[str, Any]) -> None:
        self.hass, self.hub = hass, hub
        self.port = int(cfg.get(CONF_LNS_PORT) or DEFAULT_LNS_PORT)
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.lns_{hub.entry.entry_id}")
        self.server: NetworkServer | None = None
        self._cfg = cfg
        self._transport: asyncio.DatagramTransport | None = None
        self._addr: dict[str, tuple[tuple, int]] = {}     # gateway → (address, protocol version) for downlinks
        self._unknown: dict[str, float] = {}
        self.error: str | None = None
        self.last_events: list[dict[str, Any]] = []       # recent joins / rejections for diagnostics

    # ------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        state = await self.store.async_load() or {}
        self.server = NetworkServer(keys_from_entries(self.hass), settings_from(self._cfg), state)
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(lambda: self, local_addr=("0.0.0.0", self.port))
            self.error = None
            _LOGGER.info("Built-in LoRaWAN network server listening on UDP %s", self.port)
        except OSError as err:
            self.error = f"UDP port {self.port}: {err}"
            _LOGGER.error("Built-in network server could not open UDP port %s: %s", self.port, err)

    async def async_stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        if self.server is not None:
            await self.store.async_save(self.server.to_dict())

    def _save(self) -> None:
        if self.server is not None:
            self.store.async_delay_save(self.server.to_dict, 10)

    # ------------------------------------------------------------ UDP
    def datagram_received(self, data: bytes, addr: tuple) -> None:
        d = semtech.parse(data)
        if d is None or self.server is None:
            return
        reply = semtech.ack(d)
        if reply is not None and self._transport is not None:
            self._transport.sendto(reply, addr)
        now = time.time()
        if d.ident == semtech.PULL_DATA and d.gateway:
            self._addr[d.gateway] = (addr, d.version)
            if self.server.gateway_seen(d.gateway, now, pull=True):
                self._gateway_new(d.gateway)
        elif d.ident == semtech.PUSH_DATA and d.gateway:
            if self.server.gateway_seen(d.gateway, now):
                self._gateway_new(d.gateway)
            body = d.body or {}
            if isinstance(body.get("stat"), dict):
                st = body["stat"]
                self.hub.lns_notification({"kind": "gateway_stats", "gateway_id": d.gateway,
                                           "rx_ok": st.get("rxok"), "tx_emitted": st.get("txnb")})
            for rx in body.get("rxpk") or []:
                phy = self.server.receive(d.gateway, rx, now)
                if phy is not None:
                    self.hass.loop.call_later(self.server.cfg.dedup_s, self._process, phy)
        elif d.ident == semtech.TX_ACK and d.gateway:
            err = ((d.body or {}).get("txpk_ack") or {}).get("error")
            if err and err != "NONE":
                _LOGGER.warning("Gateway %s could not send a downlink: %s", d.gateway, err)
                self._remember({"kind": "tx_error", "gateway": d.gateway, "error": err})

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Network server UDP error: %s", exc)

    def _gateway_new(self, gw: str) -> None:
        self.hub.lns_notification({"kind": "gateway_info", "gateway_id": gw,
                                   "info": {"connection": "packet forwarder (Semtech UDP)"}})

    def _send(self, tx) -> bool:
        target = self._addr.get(tx.gateway)
        if target is None or self._transport is None:
            return False
        addr, version = target
        pk = semtech.txpk(tx.phy, tx.freq, tx.datr, tx.tmst, tx.power, tx.immediate)
        datagram, _token = semtech.pull_resp(pk, version)
        self._transport.sendto(datagram, addr)
        return True

    def _remember(self, item: dict[str, Any]) -> None:
        self.last_events = ([{"at": time.time(), **item}] + self.last_events)[:20]
        async_dispatcher_send(self.hass, SIGNAL_LNS.format(self.hub.entry.entry_id))

    # ------------------------------------------------------------ events
    def _process(self, phy: bytes) -> None:
        if self.server is None:
            return
        try:
            events = self.server.process(phy)
        except Exception:  # noqa: BLE001 - one bad frame must not stop the server
            _LOGGER.exception("Network server could not handle a frame")
            return
        for ev in events:
            self._event(ev)
        if any(ev.kind in ("tx", "join") for ev in events):
            # frame counters must never go back after a restart: save at once
            self.hass.async_create_task(self.store.async_save(self.server.to_dict()))
        elif events:
            self._save()

    def _event(self, ev: Event) -> None:
        k, eui = ev.kind, ev.dev_eui
        if k == "uplink":
            d = ev.data
            if d.get("fport") is None:
                return                                    # MAC-only frame: nothing to decode
            when = None
            if d.get("time"):
                try:
                    when = datetime.fromisoformat(str(d["time"]).replace("Z", "+00:00"))
                except ValueError:
                    when = None
            up = Uplink(deveui=eui, raw=d["payload"], fport=d["fport"], rssi=d.get("rssi"), snr=d.get("snr"),
                        time=when or datetime.now(timezone.utc), gateways=d.get("gateways") or [], sf=d.get("sf"),
                        frequency=d.get("frequency"), fcnt=d.get("fcnt"))
            up.extra["network_server"] = "built-in"
            self.hub.handle_uplink(up)
        elif k == "tx":
            tx = ev.data["tx"]
            if not self._send(tx):
                _LOGGER.warning("No route to gateway %s for a downlink to %s", tx.gateway, eui)
            elif tx.meta.get("kind") == "data" and ev.data.get("fport"):
                self.hub.count_downlink()
        elif k == "join":
            _LOGGER.info("Device %s joined the built-in network server (DevAddr %s)", eui, ev.data.get("dev_addr"))
            self._remember({"kind": "join", "deveui": eui, "dev_addr": ev.data.get("dev_addr")})
            self.hub.lns_notification({"kind": "join", "deveui": eui})
        elif k == "join_unknown":
            now = time.time()
            if now - self._unknown.get(eui, 0) < UNKNOWN_JOIN_REPEAT_S:
                return
            self._unknown[eui] = now
            if self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, eui):
                # usually a device of the gateway's own network server (the forwarder copies every packet)
                self._remember({"kind": "join_no_key", "deveui": eui})
                _LOGGER.debug("Join from %s heard; it has no built-in network server key (gateway's own "
                              "network server, or add one under Configure → Network server keys)", eui)
                return
            self._remember({"kind": "join_unknown", "deveui": eui, "join_eui": ev.data.get("join_eui")})
            self.hass.async_create_task(self.hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_DEVEUI: eui, "guess": None, "candidates": [], "device_name": None, "lns": True,
                      "join_eui": ev.data.get("join_eui")}))
        elif k == "join_rejected":
            _LOGGER.warning("Join of %s refused: %s", eui, ev.data.get("reason"))
            self._remember({"kind": "join_rejected", "deveui": eui, "reason": ev.data.get("reason")})
            self.hub.lns_notification({"kind": "error", "deveui": eui, "error": f"join refused: {ev.data.get('reason')}"})
        elif k == "mic_failed":
            self._remember({"kind": "mic_failed", "deveui": eui})
        elif k == "ack":
            self.hub.lns_notification({"kind": "ack", "deveui": eui, "acknowledged": ev.data.get("acknowledged")})
        elif k == "dropped" and not ev.data.get("info"):
            _LOGGER.info("Network server: %s – %s", eui, ev.data.get("reason"))
            self._remember({"kind": "dropped", "deveui": eui, "reason": ev.data.get("reason")})

    # ------------------------------------------------------------ downlinks
    def enqueue(self, deveui: str, payload: bytes, fport: int, confirmed: bool) -> bool:
        if self.server is None or not self.server.enqueue(deveui, fport, payload, confirmed):
            return False
        self._save()
        return True

    def handles(self, deveui: str) -> bool:
        return self.server is not None and self.server.has_session(deveui)

    def summary(self) -> dict[str, Any]:
        s = self.server
        now = time.time()
        gws = {} if s is None else {
            gw: {"connected": s.can_transmit(gw, now), "last_push": g.get("push"), "last_pull": g.get("pull"),
                 "downlink_airtime_s_last_hour": round(s.airtime_last_hour(gw, now) / 1000, 1)}
            for gw, g in s.gateways.items()}
        return {"port": self.port, "error": self.error, "region": s.cfg.region.name if s else None,
                "farm_id": s.cfg.farm_id if s else None, "rx1_delay": s.cfg.rx1_delay if s else None,
                "devices": {eui: s.session_info(eui) for eui in s.sessions} if s else {},
                "gateways": gws, "counters": dict(s.counters) if s else {}, "recent": self.last_events}


class NetworkServerSensor(SensorEntity):
    """Gateway: joined devices on the built-in network server; gateways, counters and recent joins as attributes."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Network server devices"
    _attr_icon = "mdi:server-network"
    _attr_native_unit_of_measurement = "devices"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self._attr_unique_id = f"{entry.entry_id}_lns_devices"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")})

    @property
    def _lns(self) -> LnsTransport | None:
        return getattr(getattr(self.entry, "runtime_data", None), "lns", None)

    @property
    def native_value(self) -> int | None:
        lns = self._lns
        if lns is None or lns.server is None:
            return None
        return sum(1 for eui in lns.server.sessions if lns.server.has_session(eui))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lns = self._lns
        return {"milesight_role": "network_server", **(lns.summary() if lns else {})}

    async def async_added_to_hass(self) -> None:
        for sig in (SIGNAL_LNS.format(self.entry.entry_id), SIGNAL_GATEWAY.format(self.entry.entry_id)):
            self.async_on_remove(async_dispatcher_connect(self.hass, sig, self.async_write_ha_state))
