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
        self.costs = None       # costs.CostsTracker, set by the sensor platform
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
        from homeassistant.helpers.event import async_call_later as _later
        self._unsubs.append(_later(self.hass, 90, lambda _n: self.hass.async_create_task(self.async_scan_lan())))
        self._unsubs.append(async_track_time_interval(self.hass, self.async_scan_lan, timedelta(hours=6)))
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

    def registerable_gateways(self) -> list[tuple[str, dict]]:
        """Gateways that have their own embedded-network-server management channel set up, so a device can be
        registered on that gateway specifically. (eui, gateway-record) pairs."""
        out = []
        for eui, g in self.stats.gateways.items():
            ns = g.get("ns") or {}
            if ns.get("request") and ns.get("response"):
                out.append((eui, g))
        return out

    async def async_provision_on(self, eui: str, deveui: str, name: str | None = None,
                                 app_key: str | None = None, profile: str | None = None) -> str:
        """Register a device on ONE specific gateway's embedded network server (its own request/response channel),
        rather than the hub-wide default. 'added' or 'exists'. Falls back to the hub-wide ns when this gateway is
        the configured one and has no per-gateway channel yet."""
        from .gateway_discovery import norm_hex
        from .provisioning import NsApiClient
        eui = norm_hex(eui)
        g = self.stats.gateways.get(eui)
        ns = (g or {}).get("ns") or {}
        if not (ns.get("request") and ns.get("response")):
            if self.can_provision:            # no per-gateway channel: use the hub-wide ns (the config-flow gateway)
                return await self.async_provision(deveui, name, app_key, profile)
            raise ValueError("this gateway is not set up for device registration yet – Configure it "
                             "(Add devices to the gateway) first")
        client = NsApiClient(self.hass, ns["request"], ns["response"], eui)
        try:
            app, prof = ns.get("application"), profile or ns.get("profile")
            if not (app and prof):            # learn the gateway's application / device profile once, then cache
                ov = await client.async_overview()
                apps, profs = ov.get("applications") or {}, ov.get("profiles") or {}
                app = app or next((aid for aid, nm in apps.items() if nm == "Home Assistant"), None) \
                    or next(iter(apps), None)
                prof = prof or next(iter(profs), None)
                if not (app and prof):
                    raise ValueError("the gateway has no application or device profile to register into yet")
                ns["application"], ns["profile"] = str(app), str(prof)
                if g is not None:
                    g["ns"] = ns
                    self.store.async_delay_save(self.stats.to_dict, 1)
            result = await client.async_add_device(deveui, name or deveui.upper(), str(app), str(prof),
                                                    app_key or self.ns_app_key, self.ns_fport)
        finally:
            await client.async_stop()
        self.gateway_devices.setdefault("devices", [])
        if not any(d["deveui"] == deveui.lower() for d in self.gateway_devices["devices"]):
            self.gateway_devices["devices"].append({"deveui": deveui.lower(), "name": name, "active": None,
                                                    "last_seen": None, "application_id": str(ns.get("application"))})
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

    async def async_scan_lan(self, _now: Any = None, prime: bool = True) -> dict[str, list[str]]:
        """Look for Milesight gateways on the local network: wake the ARP table with one small UDP datagram to every
        address of Home Assistant's /24, then read it. Known gateways get their IP / MAC (web page link); unknown
        ones are offered under Discovered. Works where Home Assistant shares the host's network (Home Assistant
        OS, Docker with host networking)."""
        import asyncio
        import socket
        from .gateway_discovery import is_milesight_mac, mac_to_eui, parse_arp, subnet_hosts
        try:
            from homeassistant.components.network import async_get_source_ip
            own = await async_get_source_ip(self.hass)
        except Exception:  # noqa: BLE001
            own = None

        def _prime() -> None:
            if not prime or not own:
                return
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setblocking(False)
            try:
                for host in subnet_hosts(own):
                    try:
                        s.sendto(b"\x00", (host, 9))           # discard port: nothing answers, the ARP entry stays
                    except OSError:
                        pass
            finally:
                s.close()

        def _read() -> str:
            try:
                with open("/proc/net/arp", encoding="ascii", errors="ignore") as f:
                    return f.read()
            except OSError:
                return ""
        await self.hass.async_add_executor_job(_prime)
        if prime and own:
            await asyncio.sleep(3)
        found = [(ip, mac) for ip, mac in parse_arp(await self.hass.async_add_executor_job(_read)) if is_milesight_mac(mac)]
        known, offered = [], []
        for ip, mac in found:
            eui = mac_to_eui(mac)
            gid = eui if eui in self.stats.gateways else next(
                (k for k, g in self.stats.gateways.items() if g.get("ip") == ip or g.get("mac") == mac.replace(":", "")),
                None)
            if gid is not None:
                g = self.stats.gateways[gid]
                changed = g.get("ip") != ip
                g["ip"], g["mac"] = ip, g.get("mac") or mac.replace(":", "")
                g.setdefault("found", "traffic")
                g["lan_seen"] = time.time()
                known.append(gid)
                if changed:
                    self._rename_gateway_device(gid, {})
                    self._changed(force=True)
                continue
            if eui in self.stats.expected:
                self.stats.expected[eui]["ip"] = ip
                continue
            offered.append(eui)
            from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
            self.hass.async_create_task(self.hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={"lan": True, "mac": mac, "ip": ip, "hub_entry_id": self.entry.entry_id}))
        self.store.async_delay_save(self.stats.to_dict, 5)
        return {"known": known, "offered": offered}

    def forget_gateway(self, eui: str) -> bool:
        """Remove a gateway from the integration: its statistics, its 'announced' record and its Home Assistant
        device, so it can be discovered and set up again. Returns True when something was removed."""
        from .gateway_discovery import norm_hex
        eui = norm_hex(eui)
        had = self.stats.gateways.pop(eui, None) is not None
        had |= self.stats.expected.pop(eui, None) is not None
        self._online.pop(eui, None)
        if had:
            from homeassistant.helpers import device_registry as dr
            dreg = dr.async_get(self.hass)
            dev = dreg.async_get_device(identifiers={(DOMAIN, f"gw_{eui}")})
            if dev is not None:
                dreg.async_remove_device(dev.id)
            self.store.async_delay_save(self.stats.to_dict, 1)
            self._changed(force=True)
        return had

    def mark_connections(self, eui: str, kinds: list[str], replace: bool = False) -> bool:
        """Record how a gateway reaches Home Assistant: 'built-in' for the Semtech → HA network server, 'embedded'
        for the gateway's own MQTT. Used after the panel configures a gateway (so the label shows 'Semtech UDP +
        MQTT' right away, not only after the first uplink on each path), and — with replace=True — after a refresh
        that re-reads the gateway's real config, to set the label authoritatively."""
        from .gateway_discovery import norm_hex
        eui = norm_hex(eui)
        g = self.stats.gateways.get(eui) or self.stats.expected.get(eui)
        if g is None:
            return False
        changed = False
        if replace:
            new = list(dict.fromkeys(k for k in kinds if k))
            if new != g.get("conn"):
                g["conn"] = new
                if new:
                    g.setdefault("found", {"built-in": "semtech"}.get(new[0], "mqtt"))
                changed = True
        else:
            conns = g.setdefault("conn", [])
            for k in kinds:
                if k and k not in conns:
                    conns.append(k)
                    g.setdefault("found", {"built-in": "semtech"}.get(k, "mqtt"))
                    changed = True
        if changed:
            self.store.async_delay_save(self.stats.to_dict, 1)
            self._changed(force=True)
        return changed

    def mark_ns(self, eui: str, ns: dict[str, Any]) -> bool:
        """Record a gateway's own embedded-network-server management channel (request / response topics and,
        when known, the application and device profile a new device is added to), so Home Assistant can register
        a device on this gateway specifically. Merges, so a later refresh that omits application/profile keeps the
        learned ones."""
        from .gateway_discovery import norm_hex
        eui = norm_hex(eui)
        g = self.stats.gateways.get(eui) or self.stats.expected.get(eui)
        if g is None:
            return False
        cur = dict(g.get("ns") or {})
        for k in ("request", "response", "application", "profile"):
            v = ns.get(k)
            if v:
                cur[k] = v
        if cur == g.get("ns"):
            return False
        g["ns"] = cur
        self.store.async_delay_save(self.stats.to_dict, 1)
        self._changed(force=True)
        return True

    def set_gateway_location(self, eui: str, lat: float | None, lon: float | None,
                             alt: float | None = None) -> bool:
        """Record a gateway's physical location in Home Assistant (not on the gateway – many models have no
        location field). Pass lat/lon None to clear it. Stored on the gateway record and persisted."""
        from .gateway_discovery import norm_hex
        eui = norm_hex(eui)
        g = self.stats.gateways.get(eui) or self.stats.expected.get(eui)
        if g is None:
            return False
        if lat is None or lon is None:
            if "location" not in g:
                return False
            g.pop("location", None)
        else:
            loc = {"lat": round(float(lat), 6), "lon": round(float(lon), 6)}
            if alt is not None:
                loc["alt"] = round(float(alt), 1)
            if g.get("location") == loc:
                return False
            g["location"] = loc
        self.store.async_delay_save(self.stats.to_dict, 1)
        self._changed(force=True)
        return True

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
        ip = (self.stats.gateways.get(gid) or {}).get("ip")
        if ip and getattr(dev, "configuration_url", None) != f"http://{ip}":
            kw["configuration_url"] = f"http://{ip}"
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
        # delay must stay under the 60 s tick (which calls this), or the save is reset every tick and gateway
        # stats (packet counts, last-heard) only persist on a clean shutdown — lost on a crash.
        self.store.async_delay_save(self.stats.to_dict, 25)

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
            gid = note["gateway_id"]
            if self.stats.info(gid, ts, note["info"]):
                new.append(gid)
            if "Semtech" in str(note["info"].get("connection") or ""):
                self.stats.note_connection(gid, "built-in")
                g = self.stats.gateways.get(gid) or {}
                if note["info"].get("ip") and not g.get("ip"):
                    g["ip"] = note["info"]["ip"]
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
        new_gw = self.stats.uplink(self._day(up.extra["_rx"]), up.extra["_rx"], up.deveui, up.gateways, duplicate)
        conn_changed = False
        for rx in up.gateways or []:
            if rx.get("id"):
                conn_changed |= self.stats.note_connection(rx["id"], up.extra.get("network_server"))
        self._changed(new_gw, force=conn_changed)
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
