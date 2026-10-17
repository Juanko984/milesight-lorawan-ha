"""Semtech UDP packet-forwarder protocol (v1 / v2), as spoken by Milesight, RAK, Kerlink … gateways."""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

PUSH_DATA, PUSH_ACK, PULL_DATA, PULL_RESP, PULL_ACK, TX_ACK = range(6)


@dataclass
class Datagram:
    version: int
    token: bytes
    ident: int
    gateway: str | None = None          # gateway EUI, hex lower-case
    body: dict[str, Any] | None = None


def parse(data: bytes) -> Datagram | None:
    if len(data) < 4 or data[0] not in (1, 2):
        return None
    d = Datagram(version=data[0], token=data[1:3], ident=data[3])
    rest = data[4:]
    if d.ident in (PUSH_DATA, PULL_DATA, TX_ACK):
        if len(rest) < 8:
            return None
        d.gateway, rest = rest[:8].hex(), rest[8:]
    if rest and d.ident in (PUSH_DATA, TX_ACK, PULL_RESP):
        try:
            d.body = json.loads(rest.rstrip(b"\x00").decode("utf-8", "replace"))
        except ValueError:
            d.body = None if d.ident != PUSH_DATA else {}
    return d


def ack(d: Datagram) -> bytes | None:
    """PUSH_ACK / PULL_ACK for a PUSH_DATA / PULL_DATA."""
    if d.ident == PUSH_DATA:
        return bytes([d.version]) + d.token + bytes([PUSH_ACK])
    if d.ident == PULL_DATA:
        return bytes([d.version]) + d.token + bytes([PULL_ACK])
    return None


def pull_resp(txpk: dict[str, Any], version: int = 2, token: bytes | None = None) -> tuple[bytes, bytes]:
    token = token or os.urandom(2)
    return bytes([version]) + token + bytes([PULL_RESP]) + json.dumps({"txpk": txpk}, separators=(",", ":")).encode(), token


def txpk(phy: bytes, freq: float, datr: str, tmst: int | None, power: int = 14, immediate: bool = False) -> dict[str, Any]:
    pk: dict[str, Any] = {"imme": bool(immediate), "freq": round(freq, 6), "rfch": 0, "powe": power, "modu": "LORA",
                          "datr": datr, "codr": "4/5", "ipol": True, "size": len(phy),
                          "data": base64.b64encode(phy).decode()}
    if not immediate and tmst is not None:
        pk["tmst"] = tmst & 0xFFFFFFFF
    return pk


def rxpk_phy(rx: dict[str, Any]) -> bytes | None:
    """The frame of a CRC-good LoRa rxpk, else None."""
    if rx.get("stat", 1) != 1 or rx.get("modu", "LORA") != "LORA" or not rx.get("data"):
        return None
    try:
        return base64.b64decode(rx["data"])
    except ValueError:
        return None


def rxpk_radio(rx: dict[str, Any]) -> dict[str, Any]:
    """rssi / snr / freq / datr / tmst of an rxpk (v2 'rsig' arrays too)."""
    rssi, snr = rx.get("rssi"), rx.get("lsnr")
    sig = (rx.get("rsig") or [{}])[0] if isinstance(rx.get("rsig"), list) else {}
    rssi = rssi if rssi is not None else sig.get("rssic")
    snr = snr if snr is not None else sig.get("lsnr")
    return {"rssi": rssi, "snr": snr, "freq": rx.get("freq"), "datr": rx.get("datr"), "tmst": rx.get("tmst"),
            "time": rx.get("time"), "chan": rx.get("chan"), "rfch": rx.get("rfch", 0)}
