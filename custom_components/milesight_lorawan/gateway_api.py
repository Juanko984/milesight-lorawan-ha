"""Milesight gateway web API (UG65 / UG67 / UG56 / UG63 …): log in over the LAN and configure the gateway so
Home Assistant can set it up without anyone opening the gateway's web page –

* point the gateway's packet forwarder at Home Assistant's built-in network server (a Semtech destination), and / or
* set up the gateway's own embedded network server: create an application and its MQTT data transmission (broker,
  topics) so uplinks reach Home Assistant, and register devices.

The pure request builders here are unit-tested against recorded gateway traffic; the thin async HTTP layer
(GatewayClient) is a direct translation of the gateway's own web page. The admin password is only sent to the
gateway, encrypted the same way its login page does, and is never stored or logged."""
from __future__ import annotations

import logging
from typing import Any

from .lns.crypto import aes_decrypt, aes_encrypt

_LOGGER = logging.getLogger(__name__)

# The gateway's web page encrypts the login password with a fixed key/IV baked into its JavaScript (AES-CBC, PKCS7,
# base64). This is obfuscation, not protection, but it is what the firmware expects, so we reproduce it exactly.
LOGIN_KEY = b"1111111111111111"
LOGIN_IV = b"2222222222222222"

BANDS = {       # frequency plan -> (band, region label the gateway stores)
    "EU868": ("EU868", "EU(Europe)"), "US915": ("US915", "US(United States)"), "AU915": ("AU915", "AU(Australia)"),
    "AS923": ("AS923", "AS(Asia)"), "IN865": ("IN865", "IN(India)"), "KR920": ("KR920", "KR(South Korea)"),
}


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    out, prev = b"", iv
    for i in range(0, len(data), 16):
        prev = aes_encrypt(key, _xor(data[i:i + 16], prev))
        out += prev
    return out


def _cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    out, prev = b"", iv
    for i in range(0, len(data), 16):
        out += _xor(aes_decrypt(key, data[i:i + 16]), prev)
        prev = data[i:i + 16]
    return out


def encrypt_password(password: str) -> str:
    """The password as the gateway's login page sends it (AES-CBC + base64)."""
    import base64
    return base64.b64encode(_cbc_encrypt(LOGIN_KEY, LOGIN_IV, password.encode("utf-8"))).decode("ascii")


def decrypt_password(token: str) -> str:
    """Inverse of encrypt_password (used only in tests)."""
    import base64
    data = _cbc_decrypt(LOGIN_KEY, LOGIN_IV, base64.b64decode(token))
    return data[:-data[-1]].decode("utf-8")


# --------------------------------------------------------------------------- packet forwarder (Semtech)
def semtech_destination(ha_ip: str, port: int = 1700, band: str = "EU868") -> dict[str, Any]:
    """One Semtech 'Multi-Destination' entry pointing at Home Assistant's built-in network server."""
    b, region = BANDS.get(band, BANDS["EU868"])
    return {"serv_type": "semtech", "serv_enabled": True, "serv_addr": ha_ip, "band": b, "region": region,
            "serv_port_up": int(port), "serv_port_down": int(port), "sync_freq_plan": False, "actility_platform": None}


def with_semtech(general_conf: dict[str, Any], ha_ip: str, port: int = 1700, band: str = "EU868") -> dict[str, Any]:
    """A gateway's general_conf with a Semtech destination to `ha_ip` added or updated, keeping the embedded
    destination and everything else as it is. Returns a new dict ready for set_general_conf."""
    conf = dict(general_conf)
    servs = [dict(s) for s in conf.get("servs", [])]
    new = semtech_destination(ha_ip, port, band)
    spot = next((i for i, s in enumerate(servs)
                 if s.get("serv_type") == "semtech" and s.get("serv_addr") in (ha_ip, "", None)), None)
    if spot is None:
        spot = next((i for i, s in enumerate(servs) if s.get("serv_type") == "semtech" and not s.get("serv_enabled")),
                    None)
    if spot is not None:
        servs[spot] = {**servs[spot], **new}
    else:
        new["id"] = max((s.get("id", -1) for s in servs), default=-1) + 1
        servs.append(new)
    conf["servs"] = servs
    return conf


def has_semtech(general_conf: dict[str, Any], ha_ip: str) -> bool:
    return any(s.get("serv_type") == "semtech" and s.get("serv_addr") == ha_ip and s.get("serv_enabled")
               for s in general_conf.get("servs", []))


# --------------------------------------------------------------------------- embedded NS: application + MQTT
def application_body(name: str, service_profile_id: str, description: str = "", organization_id: str = "1",
                     app_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"metadata": False, "metadataDetails": [], "name": name,
                            "description": description or name, "organizationID": organization_id,
                            "serviceProfileID": service_profile_id}
    if app_id is not None:
        body["id"] = str(app_id)
    return body


def mqtt_integration(app_id: str, host: str, port: int, username: str | None, password: str | None,
                     prefix: str = "milesight", ack: bool = True, join: bool = True) -> dict[str, Any]:
    """The application's MQTT data-transmission output. Topics match what the integration subscribes to; the device
    EUI is inside every payload, so no $deveui is needed in the topic."""
    p = prefix.rstrip("/")
    return {
        "id": str(app_id), "host": host, "port": int(port), "mode": 0, "TLSMode": 0, "useTLS": False,
        "useAuth": bool(username), "username": username or "", "password": password or "",
        "clientID": "", "keepAliveInterval": 60, "connectTimeout": 30, "retransmissionEnabled": True,
        "advanced": False, "sslSecurity": True,
        "uplinkTopic": f"{p}/uplink", "upQoS": 0, "uplinkRetain": False,
        "downlinkTopic": f"{p}/downlink", "downlinkQoS": 0,
        "ackTopic": f"{p}/ack" if ack else "", "ackQoS": 0, "ackRetain": False,
        "joinTopic": f"{p}/join" if join else "", "joinQoS": 0, "joinRetain": False,
        "errorTopic": f"{p}/error", "errorQoS": 0, "errorRetain": False,
        "requestTopic": f"{p}/request", "requestQoS": 0,
        "responseTopic": f"{p}/response", "responseQoS": 0, "responseRetain": False,
        "mcDownlinkTopic": "", "mcDownlinkQoS": 0,
        "customData": "{\n    \"devEUI\": \"%devEUI%\"\n}",
        "lastWillEnable": False, "lastWillTopic": "", "lastWillQoS": 0, "lastWillRetain": False, "lastWillPayload": "",
    }


def ha_topics(prefix: str = "milesight") -> dict[str, str]:
    """The topics to put in the Home Assistant gateway entry to match mqtt_integration()."""
    p = prefix.rstrip("/")
    return {"topic": f"{p}/uplink/#", "downlink_topic": f"{p}/downlink/{{deveui}}",
            "extra_topics": f"{p}/ack, {p}/join, {p}/gateway",
            "ns_request_topic": f"{p}/request", "ns_response_topic": f"{p}/response"}


# NB: device registration on the network server is done by provisioning.py / ns_api.py (over MQTT, keyed by
# `profileID`), not here. Earlier LAN-REST helpers for that (pick_profile / device_body / async_add_device, keyed
# by `deviceProfileID`) were never wired in and conflicted with that path, so they have been removed.


# --------------------------------------------------------------------------- async client (HA side)
class GatewayError(Exception):
    """A gateway web API call failed."""


class GatewayClient:
    """Talks to one gateway's web API with aiohttp (Home Assistant's shared session). Logs in for a JWT, then uses
    the gateway's `/cgi` core calls (packet forwarder) and its `/api/...` REST endpoints (network server)."""

    def __init__(self, session: Any, host: str, username: str, password: str, timeout: float = 15.0) -> None:
        self.base = f"http://{host}".rstrip("/")
        self.session = session
        self.username, self._password = username, password
        self.timeout = timeout
        self.jwt: str | None = None
        self.cgi_cookie: str | None = None     # the router-OS web session (td cookie) that /cgi needs
        self.info: dict[str, Any] = {}

    def _headers(self, path: str, auth: str | None = None) -> dict[str, str]:
        # Two separate sessions on the gateway:
        #  * The router OS (/cgi, the yruo_* calls) authenticates with a `td` session cookie set by the web login
        #    (core 'user', function 'login'); the request itself carries no Authorization header.
        #  * The embedded network server (/api/... other than the login) authorises with the JWT the login returns.
        # `auth` forces one scheme ("none" / "basic" / "bearer") so a call can be retried with another when an older
        # firmware disagrees. The td cookie is sent on every request once we have it (as the browser does).
        import base64
        h = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01",
             "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if self.cgi_cookie:
            h["Cookie"] = self.cgi_cookie
        if auth is None:
            is_api = "/api/" in path and "internal/login" not in path
            auth = "bearer" if (is_api and self.jwt) else "none"
        if auth == "none":
            return h
        if auth == "bearer" and self.jwt:
            h["Authorization"] = f"Bearer {self.jwt}"
        else:
            token = base64.b64encode(f"{self.username}:{self._password}".encode("utf-8")).decode("ascii")
            h["Authorization"] = f"Basic {token}"
        return h

    async def _json(self, method: str, path: str, payload: Any = None, as_json: bool = False,
                    auth: str | None = None) -> Any:
        import asyncio
        import json as _json
        url = path if path.startswith("http") else f"{self.base}{path}"
        headers = self._headers(path, auth)
        if as_json:                                        # some firmware wants a real JSON content-type
            headers["Content-Type"] = "application/json; charset=UTF-8"
        body = _json.dumps(payload) if payload is not None else None
        try:
            async with self.session.request(method, url, data=body, headers=headers,
                                            timeout=__import__("aiohttp").ClientTimeout(total=self.timeout)) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise GatewayError("login expired")
                if resp.status >= 400:
                    raise GatewayError(f"{method} {path} -> HTTP {resp.status}")
                if not text.strip():
                    return {}
                try:
                    return _json.loads(text)
                except ValueError as err:                  # an HTML login page instead of JSON = wrong auth / endpoint
                    snippet = " ".join(text.split())[:80]
                    raise GatewayError(f"{path} did not return JSON ({snippet!r})") from err
        except asyncio.TimeoutError as err:
            raise GatewayError(f"{self.base} did not answer") from err
        except OSError as err:
            raise GatewayError(f"cannot reach {self.base}: {err}") from err

    async def _web_login(self) -> bool:
        """Log in to the router OS: POST /cgi core 'user' function 'login' with the AES-encrypted password. On success
        the gateway sets a `td` session cookie (returned both as Set-Cookie and in the body) that every /cgi call then
        needs. Returns True when the session is established. Raises on a genuine wrong-password so we stop before the
        firmware locks the account; returns False when the endpoint is absent (older firmware that uses another scheme).
        """
        enc = encrypt_password(self._password)
        body = {"id": "1", "execute": 1, "core": "user", "function": "login",
                "values": [{"username": self.username, "password": enc, "base": "web_login"}]}
        try:
            data = await self._json("POST", "/cgi", body, auth="none")
        except GatewayError:
            return False
        if not isinstance(data, dict):
            return False
        res = data.get("result") or []
        row = res[0] if res and isinstance(res[0], dict) else {}
        if self._cgi_ok(data) and row.get("td"):
            name = row.get("username") or self.username
            self.cgi_cookie = f"loginname={name}; td={row['td']}"
            return True
        # a wrong password comes back as status -2 with a remaining-chance / lock-time hint
        if isinstance(row, dict) and ("chance" in row or "locktime" in row or "lock_time" in row):
            raise GatewayError("gateway login failed (username or password not accepted)")
        return False

    async def login(self) -> None:
        # Establish BOTH sessions: the router-OS web session (td cookie, for the yruo_* /cgi calls) and the embedded
        # network-server JWT (for the /api/... REST calls). The password is AES-encrypted exactly as the login page
        # does it. Keep attempts few so a genuinely wrong password cannot trip the account lock.
        enc = encrypt_password(self._password)
        got_cgi = await self._web_login()          # raises on a real wrong-password
        last = "no token returned"
        for auth in ("none", "basic"):
            try:
                data = await self._json("POST", "/api/internal/login",
                                        {"username": self.username, "password": enc}, auth=auth)
            except GatewayError as err:
                last = str(err)
                continue
            if (data or {}).get("jwt"):
                self.jwt = data["jwt"]
                return
            err_txt = (str((data or {}).get("error", "")) + str((data or {}).get("message", ""))).lower()
            last = "username or password not accepted" if "password" in err_txt else "no token returned"
        # the network-server login can be unavailable (NS disabled); the router session alone still lets /cgi work
        if got_cgi:
            return
        raise GatewayError(f"gateway login failed ({last})")

    @staticmethod
    def _cgi_ok(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        status = data.get("status")
        try:                                               # some firmware returns the status as a string ("0")
            return status is None or int(status) == 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _cgi_reason(data: Any) -> str:
        if not isinstance(data, dict):
            return f"unexpected reply {str(data)[:60]!r}"
        bits = [f"status={data.get('status')}"]
        for key in ("msg", "message", "error", "errMsg", "info"):
            if data.get(key):
                bits.append(f"{key}={str(data[key])[:80]}")
        res = data.get("result")
        if isinstance(res, list) and res:
            if isinstance(res[0], dict):
                for key in ("error", "msg", "message"):
                    if res[0].get(key):
                        bits.append(f"result.{key}={str(res[0][key])[:80]}")
            else:                                          # e.g. [-32001, "Session not found"]
                bits.append("result=" + ", ".join(str(x)[:60] for x in res[:3]))
        return ", ".join(bits)

    async def _cgi(self, core: str, function: str, base: str, value: Any = None, index: int = 0) -> Any:
        v: dict[str, Any] = {"base": base}
        if value is not None:
            v["value"], v["index"] = value, index
        body = {"id": 1, "execute": 1, "core": core, "function": function, "values": [v]}
        # firmware disagrees on how /cgi is authorised: current units use NO header (the server-side session from the
        # login carries it), older ones wanted Basic (admin:password) or the login JWT. Try no-header first.
        schemes = ["none", "basic"] + (["bearer"] if self.jwt else [])
        data: Any = None
        last_err: GatewayError | None = None
        for scheme in schemes:
            try:
                data = await self._json("POST", "/cgi", body, auth=scheme)
            except GatewayError as err:
                last_err = err
                continue
            if self._cgi_ok(data):
                return data.get("result", [{}])[0] if data.get("result") else {}
        if last_err is not None and data is None:
            raise GatewayError(f"gateway refused {core}.{function} ({base}): {last_err}")
        raise GatewayError(f"gateway refused {core}.{function} ({base}): {self._cgi_reason(data)}")

    async def async_read_info(self) -> dict[str, Any]:
        res = await self._cgi("yruo_status", "get", "summary")
        for item in res.get("get", []):
            if item.get("type") == "system":
                v = item["value"]
                self.info = {"model": v.get("model"), "sn": v.get("sn"), "firmware": v.get("firmware_ver"),
                             "hardware": v.get("hardware_ver"), "eui": None}
        gw = await self._cgi("yruo_loragw", "get", "general_conf")
        for item in gw.get("get", []):
            if item.get("type") == "general_conf":
                self.info["eui"] = item["value"].get("gateway_eui") or item["value"].get("gateway_id")
        return self.info

    # ---- packet forwarder: point the gateway at Home Assistant's built-in network server
    async def async_point_at_home_assistant(self, ha_ip: str, port: int = 1700, band: str = "EU868") -> bool:
        gw = await self._cgi("yruo_loragw", "get", "general_conf")
        conf = next((it["value"] for it in gw.get("get", []) if it.get("type") == "general_conf"), None)
        if conf is None:
            raise GatewayError("could not read the gateway's packet forwarder settings")
        if has_semtech(conf, ha_ip):
            return False
        await self._cgi("yruo_loragw", "set", "general_conf", with_semtech(conf, ha_ip, port, band))
        return True

    # ---- embedded network server: application + MQTT so uplinks reach Home Assistant over the broker
    async def async_setup_mqtt(self, broker_ip: str, mqtt_user: str | None, mqtt_password: str | None,
                               prefix: str = "milesight", app_name: str = "Home Assistant") -> dict[str, Any]:
        apps = (await self._json("GET", "/api/urapplications?limit=999") or {}).get("result", [])
        existing = next((a for a in apps if a.get("name") == app_name), None)
        if existing is not None:
            app_id, svc = str(existing["id"]), existing.get("serviceProfileID")
        else:
            svc = (apps[0].get("serviceProfileID") if apps else None)
            if not svc:
                raise GatewayError("the gateway has no service profile; enable its network server first")
            created = await self._json("POST", "/api/urapplications",
                                       application_body(app_name, svc, "Milesight LoRaWAN for Home Assistant"))
            app_id = str(created["id"])
        await self._json("POST", f"/api/urapplications/{app_id}/integrations/mqtt",
                         mqtt_integration(app_id, broker_ip, 1883, mqtt_user, mqtt_password, prefix))
        return {"application_id": app_id, "service_profile_id": svc, **ha_topics(prefix)}

    async def async_profiles(self) -> list[dict[str, Any]]:
        return (await self._json("GET", "/api/urprofiles?limit=999") or {}).get("result", [])

    async def async_read_connections(self, ha_ip: str, broker: str) -> dict[str, bool]:
        """What the gateway actually forwards to Home Assistant right now: whether its Semtech packet forwarder
        points at HA, and whether any of its applications has an MQTT integration to HA's broker."""
        semtech = False
        try:
            gw = await self._cgi("yruo_loragw", "get", "general_conf")
            conf = next((it["value"] for it in gw.get("get", []) if it.get("type") == "general_conf"), {})
            semtech = has_semtech(conf, ha_ip)
        except GatewayError:
            pass
        mqtt = False
        try:
            apps = (await self._json("GET", "/api/urapplications?limit=999") or {}).get("result", [])
            for a in apps:
                try:
                    integ = await self._json("GET", f"/api/urapplications/{a['id']}/integrations/mqtt")
                except GatewayError:
                    continue
                host = str((integ or {}).get("host") or "")
                if host and host in (ha_ip, broker):
                    mqtt = True
                    break
        except GatewayError:
            pass
        return {"semtech": semtech, "mqtt": mqtt}


async def read_gateway_connections(hass: Any, host: str, username: str, password: str) -> dict[str, Any]:
    """Log into a gateway and read what is actually configured, to reconcile its connection label with reality.
    Returns {gateway, semtech, mqtt, home_assistant_ip}. Raises GatewayError on failure."""
    from urllib.parse import urlparse

    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.network import get_url
    try:
        from homeassistant.components.network import async_get_source_ip
        ha_ip = await async_get_source_ip(hass, target_ip=host)
    except Exception:  # noqa: BLE001
        ha_ip = urlparse(get_url(hass, allow_external=False)).hostname
    broker = ha_ip
    for e in hass.config_entries.async_entries("mqtt"):
        md = {**e.data, **e.options}
        if md.get("broker"):
            broker = md["broker"] if md["broker"] not in ("localhost", "127.0.0.1", "core-mosquitto") else ha_ip
            break
    client = GatewayClient(async_get_clientsession(hass), host, username, password)
    await client.login()
    info = await client.async_read_info()
    conns = await client.async_read_connections(ha_ip, broker)
    return {"gateway": info, "home_assistant_ip": ha_ip, **conns}


async def run_gateway_config(hass: Any, host: str, username: str, password: str, mode: str = "lns",
                             band: str = "EU868", mqtt_user: str | None = None,
                             mqtt_password: str | None = None) -> dict[str, Any]:
    """Configure one gateway over the LAN exactly as the config flow / service does, and adopt it into the hub:
    log in, optionally point the Semtech packet forwarder at Home Assistant, and optionally set up the embedded
    network server's MQTT application. Shared by the configure_gateway service and the commissioning panel so both
    use the one verified path. Returns {gateway, done, home_assistant_ip, topics}. Raises GatewayError on failure.
    """
    from urllib.parse import urlparse

    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.network import get_url

    try:
        from homeassistant.components.network import async_get_source_ip
        ha_ip = await async_get_source_ip(hass, target_ip=host)
    except Exception:  # noqa: BLE001 - fall back to the configured URL's host
        ha_ip = urlparse(get_url(hass, allow_external=False)).hostname

    client = GatewayClient(async_get_clientsession(hass), host, username, password)
    done: list[str] = []
    await client.login()
    info = await client.async_read_info()
    if mode in ("lns", "both"):
        done.append("semtech" if await client.async_point_at_home_assistant(ha_ip, band=band) else "semtech_already")
    topics: dict[str, Any] = {}
    if mode in ("mqtt", "both"):
        mu, mp, broker = mqtt_user, mqtt_password, ha_ip
        for e in hass.config_entries.async_entries("mqtt"):     # default to Home Assistant's own broker login
            md = {**e.data, **e.options}
            if md.get("broker"):
                mu = mu or md.get("username")
                mp = mp or md.get("password")
                broker = md["broker"] if md["broker"] not in ("localhost", "127.0.0.1", "core-mosquitto") else ha_ip
                break
        topics = await client.async_setup_mqtt(broker, mu or None, mp or None)
        done.append("mqtt")
    # adopt the gateway into the hub so it shows up and is tracked
    from .const import DOMAIN
    hubs = list(hass.data.get(DOMAIN, {}).get("hubs", {}).values())
    hub = hubs[0] if hubs else None
    if hub is not None and info.get("eui") and hasattr(hub, "expect_gateway"):
        from .gateway_discovery import norm_hex
        hub.expect_gateway(norm_hex(info["eui"]),
                           {"name": info.get("model"), "ip": host, "model": info.get("model")})
        # record the paths we just set up so the connection label is right away (not only after the first uplink
        # on each path arrives): Semtech → HA network server = "built-in", the gateway's own MQTT = "embedded".
        kinds = (["built-in"] if any(d in done for d in ("semtech", "semtech_already")) else []) \
            + (["embedded"] if "mqtt" in done else [])
        if kinds and hasattr(hub, "mark_connections"):
            hub.mark_connections(norm_hex(info["eui"]), kinds)
    return {"gateway": info, "done": done, "home_assistant_ip": ha_ip, "topics": topics}
