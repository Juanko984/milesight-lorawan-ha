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


def pick_profile(profiles: list[dict[str, Any]], want_class_c: bool = False) -> dict[str, Any] | None:
    """A ClassA (or ClassC) OTAA profile from the gateway's profile list (GET /api/urprofiles result)."""
    best = None
    for p in profiles:
        pr = p.get("profile", p)
        if not pr.get("supportsJoin", True):                 # OTAA only (ABP profiles do not join)
            continue
        is_c = bool(pr.get("supportsClassC"))
        if is_c == want_class_c:
            return p
        best = best or p
    return best


def device_body(deveui: str, name: str, app_id: str, profile_id: str, app_key: str, join_eui: str = "",
                organization_id: str = "1") -> dict[str, Any]:
    """Register one device on the gateway's network server (POST /api/urdevices)."""
    eui = "".join(c for c in deveui.lower() if c in "0123456789abcdef")
    return {"devEUI": eui, "name": name or eui.upper(), "description": name or "", "applicationID": str(app_id),
            "deviceProfileID": str(profile_id), "organizationID": organization_id,
            "appKey": "".join(c for c in (app_key or "").lower() if c in "0123456789abcdef"),
            "appEUI": "".join(c for c in (join_eui or "").lower() if c in "0123456789abcdef") or "0000000000000000",
            "skipFCntCheck": False, "referenceAltitude": 0, "isDisabled": False}


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
        self.info: dict[str, Any] = {}

    def _headers(self, path: str) -> dict[str, str]:
        # The gateway authenticates its whole web origin with HTTP Basic auth (admin:password); the browser sends it
        # on every request, so /islogin, /cgi and the login endpoint need it. The network-server REST endpoints
        # (/api/... other than the login) are authorised with the JWT the login returns.
        import base64
        h = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01",
             "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        is_api = "/api/" in path and "internal/login" not in path
        if is_api and self.jwt:
            h["Authorization"] = f"Bearer {self.jwt}"
        else:
            token = base64.b64encode(f"{self.username}:{self._password}".encode("utf-8")).decode("ascii")
            h["Authorization"] = f"Basic {token}"
        return h

    async def _json(self, method: str, path: str, payload: Any = None, as_json: bool = False) -> Any:
        import asyncio
        import json as _json
        url = path if path.startswith("http") else f"{self.base}{path}"
        headers = self._headers(path)
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
                return _json.loads(text) if text.strip() else {}
        except asyncio.TimeoutError as err:
            raise GatewayError(f"{self.base} did not answer") from err
        except OSError as err:
            raise GatewayError(f"cannot reach {self.base}: {err}") from err

    async def login(self) -> None:
        # the password transform and the login content-type have varied across gateway firmware, so try the known
        # forms (encrypted / plain, form / json content-type) and keep the first that returns a token.
        last = "no token returned"
        for pw in (encrypt_password(self._password), self._password):
            for as_json in (False, True):
                try:
                    data = await self._json("POST", "/api/internal/login",
                                            {"username": self.username, "password": pw}, as_json=as_json)
                except GatewayError as err:
                    last = str(err)
                    continue
                if (data or {}).get("jwt"):
                    self.jwt = data["jwt"]
                    return
                last = "username or password not accepted"
        raise GatewayError(f"gateway login failed ({last})")

    async def _cgi(self, core: str, function: str, base: str, value: Any = None, index: int = 0) -> Any:
        v: dict[str, Any] = {"base": base}
        if value is not None:
            v["value"], v["index"] = value, index
        body = {"id": 1, "execute": 1, "core": core, "function": function, "values": [v]}
        data = await self._json("POST", "/cgi", body)
        if not isinstance(data, dict) or data.get("status") not in (0, None):
            raise GatewayError(f"gateway refused {core}.{function} ({base})")
        return data.get("result", [{}])[0] if data.get("result") else {}

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

    async def async_add_device(self, deveui: str, name: str, app_id: str, profile_id: str, app_key: str,
                               join_eui: str = "") -> None:
        await self._json("POST", "/api/urdevices",
                         device_body(deveui, name, app_id, profile_id, app_key, join_eui))
