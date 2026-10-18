"""Milesight gateway network-server API over MQTT ("ns-api"): register devices on the gateway from Home
Assistant. Pure helpers (unit-tested); hub.NsApiClient does the MQTT request / response.

The gateway's application MQTT integration has a *Request Data* topic (we publish requests there) and a
*Response Data* topic (the gateway answers there). Request:
  {"type": "ns-api", "id": "<random>", "method": "POST", "url": "/api/urdevices", "gatewayEUI": "", "body": {…}}
Response: the same id / method / url plus body {"code": 200, "error": "", …}.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

DEFAULT_APP_KEY = "5572404c696e6b4c6f52613230313823"     # Milesight factory AppKey
DEFAULT_FPORT = 85
CODES = {
    200: "ok", 3: "parameter error", 5: "not found", 6: "already exists", 20: "could not parse the request",
    21: "type or url not supported", 24: "timed out on the gateway", 25: "gateway EUI does not match",
}
CODE_EXISTS = 6
CODE_NOT_FOUND = 5


class NsApiError(Exception):
    def __init__(self, code: int | None, error: str = "") -> None:
        self.code = code
        text = CODES.get(code, f"code {code}") if code is not None else "no answer"
        super().__init__(f"gateway: {text}{(' – ' + error) if error else ''}")


def build_request(method: str, url: str, body: dict | None = None, gateway_eui: str = "",
                  rid: str | None = None) -> tuple[str, str]:
    """(request id, JSON text)."""
    rid = rid or uuid.uuid4().hex[:16]
    msg: dict[str, Any] = {"type": "ns-api", "id": rid, "method": method.upper(), "url": url}
    if gateway_eui:
        msg["gatewayEUI"] = gateway_eui.lower()
    if body is not None:
        msg["body"] = body
    return rid, json.dumps(msg, separators=(",", ":"))


def parse_response(payload: str | bytes) -> tuple[str | None, int | None, str, dict[str, Any]] | None:
    """(id, code, error, body) of an ns-api answer, None for anything that is not one. Tolerant: gateway firmware
    differs in whether it echoes "type" / "id", so any JSON object with an id, a body or a code counts."""
    try:
        msg = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(msg, dict) or msg.get("type") not in (None, "ns-api"):
        return None
    if not (msg.get("id") or "body" in msg or "code" in msg):
        return None
    body = msg.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            body = {"raw": body}
    body = body if isinstance(body, dict) else {}
    code = body.get("code", msg.get("code"))
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    if not body and "code" in msg:
        body = {k: v for k, v in msg.items() if k not in ("type", "id", "method", "url", "gatewayEUI")}
    return (str(msg["id"]) if msg.get("id") else None), code, str(body.get("error") or msg.get("error") or ""), body


_SECRET_RE = re.compile(r'("(?:appKey|appSKey|nwkSKey)"\s*:\s*")[0-9a-fA-F]*(")')


def mask_secrets(text: str) -> str:
    """Hide AppKeys and session keys (the gateway's device list contains them) before logging or showing text."""
    return _SECRET_RE.sub(r"\1***\2", text)


def valid_key(key: str | None) -> bool:
    return bool(key) and re.fullmatch(r"[0-9a-fA-F]{32}", key) is not None


def device_body(deveui: str, name: str, application_id: str, profile_id: str, app_key: str | None = None,
                fport: int = DEFAULT_FPORT, description: str = "Added from Home Assistant") -> dict[str, Any]:
    """Body of POST /api/urdevices (OTAA)."""
    return {
        "name": (name or deveui)[:64],
        "description": description[:128],
        "devEUI": deveui.lower(),
        "profileID": str(profile_id),
        "applicationID": str(application_id),
        "appKey": (app_key or DEFAULT_APP_KEY).lower(),
        "fPort": int(fport),
        "skipFCntCheck": False,
        "payloadCodecID": "0",
    }


def parse_devices(body: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for d in body.get("deviceResult") or body.get("devices") or []:
        if not isinstance(d, dict) or not d.get("devEUI"):
            continue
        out.append({"deveui": str(d["devEUI"]).lower(), "name": d.get("name"),
                    "application_id": str(d.get("applicationID", "")), "profile": d.get("profileName"),
                    "active": d.get("active"),
                    "last_seen": next((v for v in (d.get("lastSeenAtTime"), d.get("lastSeenAt")) if v and v != "-"),
                                      None)})
    return out


def parse_applications(body: dict[str, Any]) -> dict[str, str]:
    """{applicationID: name} from a device-list or an application-list answer."""
    out = {}
    for a in body.get("appResult") or body.get("result") or body.get("applications") or []:
        if isinstance(a, dict):
            aid = a.get("applicationID", a.get("id"))
            if aid is not None and ("appName" in a or "name" in a or "applicationID" in a):
                out[str(aid)] = str(a.get("appName") or a.get("name") or aid)
    return out


def parse_profiles(body: dict[str, Any]) -> dict[str, str]:
    """{profileID: name} from GET /api/urprofiles (or the profileResult of a device list)."""
    out = {}
    for p in body.get("profileResult") or []:
        if isinstance(p, dict) and p.get("profileID"):
            out[str(p["profileID"])] = str(p.get("profileName") or p["profileID"])
    for p in body.get("result") or []:
        if not isinstance(p, dict):
            continue
        prof = p.get("profile") if isinstance(p.get("profile"), dict) else p
        pid = prof.get("profileID") or p.get("profileID")
        if pid:
            out[str(pid)] = str(p.get("name") or prof.get("name") or prof.get("profileName") or pid)
    return out


URL_DEVICES = "/api/urdevices"
URL_DEVICE_LIST = "/api/urdevices?applicationID=0&offset=0&limit=9999"
URL_PROFILES = "/api/urprofiles?limit=9999&offset=0"
URL_APPS = "/api/urapplications?limit=9999&offset=0"
