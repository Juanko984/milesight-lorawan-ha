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
    CONF_NS_APP_KEY,
    CONF_NS_APPLICATION,
    CONF_NS_FPORT,
    CONF_NS_GATEWAY_EUI,
    CONF_NS_PROFILE,
    CONF_NS_REQUEST_TOPIC,
    CONF_NS_RESPONSE_TOPIC,
    DEFAULT_GATEWAY_OFFLINE_MIN,
    SIGNAL_GATEWAY,
    SIGNAL_GATEWAY_NEW,
    SIGNAL_HEARD,
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
        self.areas = None       # fleet.AreaTracker, set by the sensor platform
        self.building = None    # building.BuildingTracker
        self.ns = None          # provisioning.NsApiClient when the ns-api topics are set
        if cfg.get(CONF_NS_REQUEST_TOPIC) and cfg.get(CONF_NS_RESPONSE_TOPIC):
            from .provisioning import NsApiClient
            self.ns = NsApiClient(hass, cfg[CONF_NS_REQUEST_TOPIC], cfg[CONF_NS_RESPONSE_TOPIC],
                                  cfg.get(CONF_NS_GATEWAY_EUI) or "")
        self.ns_application: str = str(cfg.get(CONF_NS_APPLICATION) or "")
        self.ns_profile: str = str(cfg.get(CONF_NS_PROFILE) or "")
        self.ns_app_key: str | None = cfg.get(CONF_NS_APP_KEY) or None
        self.ns_fport: int = int(cfg.get(CONF_NS_FPORT) or DOWNLINK_FPORT)
        self.gateway_devices: dict[str, Any] = {}   # last sync: {devices, applications, profiles, at, error}
        from .escalation import AlertManager
        from .irrigation_ha import IrrigationManager
        self.alerts = AlertManager(hass, entry, self)
        self.irrigation = IrrigationManager(hass, entry)
        from .compliance_ha import ComplianceManager
        self.compliance = ComplianceManager(hass, entry)
        self.lns = None         # lns_ha.LnsTransport: built-in network server (Semtech packet forwarder)
        from .const import CONF_LNS_ENABLED
        if cfg.get(CONF_LNS_ENABLED):
            from .lns_ha import LnsTransport
            self.lns = LnsTransport(hass, self, cfg)

    async def async_start(self) -> None:
        self.stats = GatewayStats(await self.store.async_load())
        for eui, info in (self.entry.options.get("pending_gateways") or {}).items():   # announced in the set-up
            if not self.gateway_known(eui):
                self.stats.expected[eui] = dict(info)
        self._online = {gid: self.stats.online(gid, time.time(), self.offline_s) for gid in self.stats.gateways}
        for topic in [self.topic, *self.extra_topics] if self.topic else []:
            try:
                self._unsubs.append(await mqtt.async_subscribe(self.hass, topic, self._message_received, qos=0))
                _LOGGER.debug("Subscribed to %s", topic)
            except Exception:  # noqa: BLE001 - MQTT not set up: the built-in network server still works
                if self.lns is None:
                    raise
                _LOGGER.warning("Could not subscribe to %s – only the built-in network server is used", topic)
        if self.lns is not None:
            await self.lns.async_start()
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=60)))
        if self.ns is not None:
            # read the gateway's device list shortly after start and every 6 hours, so 'Devices on gateway'
            # is never empty just because nobody pressed Sync
            from homeassistant.helpers.event import async_call_later
            self._unsubs.append(async_call_later(self.hass, 45, self._auto_sync))
            self._unsubs.append(async_track_time_interval(self.hass, self._auto_sync, timedelta(hours=6)))
        await self.alerts.async_start()
        await self.irrigation.async_start()
        await self.compliance.async_start()

    async def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        await self.alerts.async_stop()
        await self.irrigation.async_stop()
        await self.compliance.async_stop()
        if self.lns is not None:
            await self.lns.async_stop()
        if self.ns is not None:
            await self.ns.async_stop()
        await self.store.async_save(self.stats.to_dict())

    # ------------------------------------------------------- provisioning
    @property
    def can_provision(self) -> bool:
        return self.ns is not None and bool(self.ns_application) and bool(self.ns_profile)

    async def async_provision(self, deveui: str, name: str | None, app_key: str | None = None,
                              profile: str | None = None) -> str:
        """Register a device on the gateway: 'added' or 'exists'. Raises ns_api.NsApiError / ValueError."""
        if not self.can_provision:
            raise ValueError("gateway provisioning is not set up (gateway → Configure → Add devices to the gateway)")
        result = await self.ns.async_add_device(deveui, name or deveui.upper(), self.ns_application,
                                                profile or self.ns_profile, app_key or self.ns_app_key, self.ns_fport)
        self.gateway_devices.setdefault("devices", [])
        if not any(d["deveui"] == deveui.lower() for d in self.gateway_devices["devices"]):
            self.gateway_devices["devices"].append({"deveui": deveui.lower(), "name": name, "active": None,
                                                    "last_seen": None, "application_id": self.ns_application})
        async_dispatcher_send(self.hass, SIGNAL_GATEWAY.format(self.entry.entry_id))
        return result

    async def _auto_sync(self, _now: Any = None) -> None:
        try:
            await self.async_sync_devices(discover=False)
        except Exception:  # noqa: BLE001 - shown on the sensor as 'error'
            _LOGGER.debug("Automatic sync with the gateway failed", exc_info=True)

    async def async_sync_devices(self, discover: bool = True) -> dict[str, Any]:
        """Read the gateway's device list; devices that Home Assistant does not know yet are offered for adding."""
        if self.ns is None:
            raise ValueError("gateway provisioning is not set up")
        try:
            data = await self.ns.async_overview()
        except Exception as err:
            self.gateway_devices = {**self.gateway_devices, "error": str(err), "at": time.time()}
            async_dispatcher_send(self.hass, SIGNAL_GATEWAY.format(self.entry.entry_id))
            raise
        self.gateway_devices = {**data, "at": time.time(), "error": None}
        if discover:
            for d in data["devices"]:
                if self.ns_application and d.get("application_id") not in ("", self.ns_application):
                    continue                     # only offer the gateway application Home Assistant uses
                eui = d["deveui"]
                if self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, eui) or eui in self._announced:
                    continue
                self._announced.add(eui)
                named = guess_from_name(d.get("name"))
                self.hass.async_create_task(self.hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY},
                    data={CONF_DEVEUI: eui, "guess": named, "candidates": [named] if named else [],
                          "device_name": d.get("name")}))
        async_dispatcher_send(self.hass, SIGNAL_GATEWAY.format(self.entry.entry_id))
        return data

    def _day(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
                                      ).date().isoformat()

    # ------------------------------------------------------------ gateway discovery
    def _gateways_found(self, new: list[str]) -> None:
        """Gateways heard for the first time: adopt the ones announced beforehand (network discovery or QR
        scan), offer the others under Discovered."""
        from .gateway_discovery import match_expected
        for gid in new:
            g = self.stats.gateways.get(gid) or {}
            if g.get("approved"):
                continue
            ip = (g.get("info") or {}).get("ip")
            key = match_expected(self.stats.expected, gid, ip)
            if key is not None:
                info = self.stats.expected.pop(key)
                self.stats.adopt(gid, {**info, "ip": ip or info.get("ip")})
                self._close_gateway_cards(gid, key)
                from homeassistant.components import persistent_notification
                persistent_notification.async_create(
                    self.hass, f"**{info.get('name') or gid}** is sending to Home Assistant"
                               f"{(' (' + str(info['area']) + ')') if info.get('area') else ''}. "
                               "Devices it hears now show up under Settings → Devices & services → Discovered.",
                    title="Milesight LoRaWAN: gateway connected", notification_id=f"{DOMAIN}_gateway_{gid}")
                self.hass.bus.async_fire(f"{DOMAIN}_gateway_connected", {"gateway_id": gid,
                                                                       "gateway": info.get("name"), "hub": self.entry.title})
            else:
                self._offer_gateway(gid, ip)

    def _offer_gateway(self, gid: str, ip: str | None) -> None:
        from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
        g = self.stats.gateways.get(gid) or {}
        self.hass.async_create_task(self.hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={"gateway_id": gid, "hub_entry_id": self.entry.entry_id, "ip": ip,
                  "model": (g.get("info") or {}).get("model"),
                  "connection": (g.get("info") or {}).get("connection")}))

    def _close_gateway_cards(self, *euis: str) -> None:
        ids = {f"gateway:{e}" for e in euis if e}
        for flow in self.hass.config_entries.flow.async_progress_by_handler(DOMAIN):
            if (flow.get("context") or {}).get("unique_id") in ids:
                self.hass.config_entries.flow.async_abort(flow["flow_id"])

    def gateway_known(self, eui: str) -> bool:
        """Confirmed or announced already."""
        return bool((self.stats.gateways.get(eui) or {}).get("approved")) or eui in self.stats.expected

    def expect_gateway(self, eui: str, info: dict[str, Any]) -> str:
        """A gateway announced by network discovery or a QR scan. 'connected' when it already sends to Home
        Assistant (it is named now), else 'waiting' (it is adopted from its first packet)."""
        from .gateway_discovery import match_expected
        info = {k: v for k, v in info.items() if v not in (None, "")}
        heard = {gid: g for gid, g in self.stats.gateways.items() if not g.get("approved")}
        gid = eui if eui in self.stats.gateways else None
        if gid is None and info.get("ip"):
            by_ip = [k for k, g in heard.items() if (g.get("info") or {}).get("ip") == info["ip"]]
            gid = by_ip[0] if len(by_ip) == 1 else None
        self._close_gateway_cards(eui, gid or "")
        if gid is not None:
            self.stats.adopt(gid, info)
            self._rename_gateway_device(gid, info)
            self._changed(force=True)
            return "connected"
        self.stats.expected[eui] = info
        self.store.async_delay_save(self.stats.to_dict, 1)
        return "waiting"

    def _rename_gateway_device(self, gid: str, info: dict[str, Any]) -> None:
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr
        dreg = dr.async_get(self.hass)
        dev = dreg.async_get_device(identifiers={(DOMAIN, f"gw_{gid}")})
        if dev is None:
            return
        kw: dict[str, Any] = {}
        if info.get("name") and not dev.name_by_user:
            kw["name"] = info["name"]
        if info.get("area") and not dev.area_id:
            kw["area_id"] = ar.async_get(self.hass).async_get_or_create(str(info["area"])).id
        if kw:
            dreg.async_update_device(dev.id, **kw)

    def _changed(self, new: list[str] | bool = (), force: bool = False) -> None:
        """Refresh gateway entities – at most every 30 s for plain traffic (the 60 s tick catches up)."""
        if isinstance(new, list) and new:
            self._gateways_found(new)
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
        """Queue a downlink via the built-in network server (devices joined there) or the gateway (Milesight or
        ChirpStack MQTT format)."""
        if self.lns is not None and self.lns.handles(deveui):
            if not self.lns.enqueue(deveui, payload, fport, confirmed):
                raise RuntimeError(f"{deveui.upper()} has not joined the built-in network server yet")
            _LOGGER.debug("Downlink to %s queued on the built-in network server: %s", deveui, payload.hex())
            return
        topic = (self.downlink_topic.replace("{deveui}", deveui.lower()).replace("{DEVEUI}", deveui.upper())
                 .replace("$deveui", deveui.lower()))
        msg = {"confirmed": bool(confirmed), "fPort": fport, "data": base64.b64encode(payload).decode()}
        if self.downlink_format == DOWNLINK_CHIRPSTACK:
            msg = {"devEui": deveui.lower(), **msg}
        _LOGGER.debug("Downlink to %s on %s: %s", deveui, topic, payload.hex())
        await mqtt.async_publish(self.hass, topic, json.dumps(msg), qos=0)
        self.stats.count("downlinks", self._day(time.time()))
        self._changed()

    def count_downlink(self) -> None:
        self.stats.count("downlinks", self._day(time.time()))
        self._changed()

    def forget(self, deveui: str) -> None:
        """Allow a removed device to be discovered again (and drop its network server session)."""
        self._announced.discard(deveui)
        if self.lns is not None and self.lns.server is not None:
            self.lns.server.forget(deveui)

    def lns_notification(self, note: dict[str, Any]) -> None:
        """Join / ACK / error / gateway status from the built-in network server."""
        self._notification(note)

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
        self.handle_uplink(up)

    @callback
    def handle_uplink(self, up: Uplink) -> None:
        """An uplink from the gateway's MQTT feed or the built-in network server."""
        up.extra.setdefault("network_server", "chirpstack" if self.downlink_format == DOWNLINK_CHIRPSTACK else "embedded")
        prev = self.last_uplink.get(up.deveui)
        duplicate = (prev is not None and up.fcnt is not None and prev.fcnt == up.fcnt
                     and prev.raw == up.raw and abs(time.time() - prev.extra.get("_rx", 0)) < 30)
        up.extra["_rx"] = time.time()
        self.last_uplink[up.deveui] = up
        self._changed(self.stats.uplink(self._day(up.extra["_rx"]), up.extra["_rx"], up.deveui, up.gateways,
                                        duplicate))
        async_dispatcher_send(self.hass, SIGNAL_HEARD, up, duplicate)      # commissioning walk test

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
