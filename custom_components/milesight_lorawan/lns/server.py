"""A light LoRaWAN 1.0.x network server: OTAA joins, data frames, frame counters, de-duplication across gateways,
class A downlinks (RX1), LinkCheck and DeviceTime. Pure Python and synchronous – the Home Assistant side feeds it
the gateways' packets and sends the downlinks it returns (unit-tested without Home Assistant).

Keys never leave this module except in to_dict() (Home Assistant's storage); events carry no keys."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import crypto
from .phy import (CONF_DOWN, CONF_UP, DEVICE_TIME, JOIN_REQUEST, LINK_CHECK, UNCONF_DOWN, UNCONF_UP, PhyError,
                  TxRequest, build_data, full_fcnt, mtype, parse_data, parse_join_request, parse_mac)
from .region import EU868, Region, airtime_ms
from .semtech import rxpk_phy, rxpk_radio

GPS_EPOCH = 315964800          # 1980-01-06 in unix time
LEAP_SECONDS = 18              # GPS - UTC since 2017
REQUIRED_SNR = {7: -7.5, 8: -10, 9: -12.5, 10: -15, 11: -17.5, 12: -20}
MAX_MAC_PAYLOAD = (59, 59, 59, 123, 250, 250, 250)     # EU868 M per DR
DEVNONCE_MEMORY = 100
QUEUE_MAX = 32
TX_GATEWAY_FRESH_S = 90        # a gateway can transmit when it sent PULL_DATA this recently
RECENT_S = 1.5                 # late gateway copies; a device's own repeat (no ACK heard) comes later


@dataclass
class DeviceKeys:
    dev_eui: str               # hex lower-case
    app_key: bytes
    join_eui: str | None = None


@dataclass
class Settings:
    region: Region = EU868
    net_id: int = 0x000000     # experimental / private network
    farm_id: int = 0           # 0-511: the device address block of this site (DevAddr = farm << 16 | n)
    rx1_delay: int = 3         # seconds (sent to the device in the join-accept)
    rx1_dr_offset: int = 0
    rx2_dr: int = 0
    dedup_s: float = 0.25


@dataclass
class Event:
    kind: str                  # uplink / join / join_unknown / join_rejected / mic_failed / ack / tx / dropped / foreign
    dev_eui: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class NetworkServer:
    def __init__(self, keys: Callable[[str], DeviceKeys | None], settings: Settings | None = None,
                 state: dict[str, Any] | None = None, rand: Callable[[int], bytes] = os.urandom) -> None:
        self.keys, self.cfg, self._rand = keys, settings or Settings(), rand
        self.sessions: dict[str, dict[str, Any]] = dict((state or {}).get("sessions") or {})
        self.by_addr: dict[int, str] = {s["dev_addr"]: eui for eui, s in self.sessions.items() if "dev_addr" in s}
        self.gateways: dict[str, dict[str, Any]] = {}
        self._pending: dict[bytes, dict[str, Any]] = {}
        self._recent: dict[bytes, float] = {}
        self.counters: dict[str, int] = {"foreign": 0, "mic_failed": 0, "joins": 0, "uplinks": 0, "downlinks": 0}

    # ------------------------------------------------------------ state
    def to_dict(self) -> dict[str, Any]:
        return {"sessions": self.sessions}

    def has_session(self, dev_eui: str) -> bool:
        s = self.sessions.get(dev_eui.lower())
        return bool(s and s.get("nwk_s_key"))

    def forget(self, dev_eui: str) -> None:
        s = self.sessions.pop(dev_eui.lower(), None)
        if s and self.by_addr.get(s.get("dev_addr")) == dev_eui.lower():
            self.by_addr.pop(s["dev_addr"], None)

    def session_info(self, dev_eui: str) -> dict[str, Any] | None:
        """For diagnostics and entities: everything except the keys."""
        s = self.sessions.get(dev_eui.lower())
        if not s:
            return None
        return {"dev_addr": f"{s.get('dev_addr', 0):08x}", "fcnt_up": s.get("fcnt_up"), "fcnt_down": s.get("fcnt_down"),
                "joined_at": s.get("joined_at"), "queue": len(s.get("queue") or []), "last_gateway": s.get("last_gateway")}

    # ------------------------------------------------------------ gateways
    def gateway_seen(self, gw: str, now: float, pull: bool = False) -> bool:
        """Returns True for a gateway not seen before."""
        g = self.gateways.get(gw)
        new = g is None
        g = self.gateways.setdefault(gw, {"push": None, "pull": None, "airtime_ms": []})
        g["pull" if pull else "push"] = now
        return new

    def can_transmit(self, gw: str, now: float) -> bool:
        g = self.gateways.get(gw) or {}
        return g.get("pull") is not None and now - g["pull"] < TX_GATEWAY_FRESH_S

    def airtime_last_hour(self, gw: str, now: float) -> float:
        g = self.gateways.get(gw) or {}
        g["airtime_ms"] = [(t, ms) for t, ms in g.get("airtime_ms", []) if now - t < 3600]
        return sum(ms for _t, ms in g["airtime_ms"])

    # ------------------------------------------------------------ receive
    def receive(self, gw: str, rxpk: dict[str, Any], now: float) -> bytes | None:
        """A gateway heard a frame. Returns the frame when it is the first copy (call process() after
        settings.dedup_s), None for a copy from another gateway or an unusable packet."""
        phy = rxpk_phy(rxpk)
        if phy is None:
            return None
        for k, t in list(self._recent.items()):
            if now - t > RECENT_S:
                del self._recent[k]
        if phy in self._recent:
            return None                               # a late copy of a frame already handled
        radio = {"gateway": gw, **rxpk_radio(rxpk)}
        if phy in self._pending:
            self._pending[phy]["rx"].append(radio)
            return None
        self._pending[phy] = {"first": now, "rx": [radio]}
        return phy

    def process(self, phy: bytes, now: float | None = None) -> list[Event]:
        now = time.time() if now is None else now
        item = self._pending.pop(phy, None)
        if item is None:
            return []
        self._recent[phy] = now
        rx = sorted(item["rx"], key=lambda r: (r.get("snr") is None, -(r.get("snr") or 0), -(r.get("rssi") or -999)))
        try:
            mt = mtype(phy)
            if mt == JOIN_REQUEST:
                return self._join(phy, rx, now)
            if mt in (UNCONF_UP, CONF_UP):
                return self._uplink(phy, rx, now, item["first"])
        except PhyError:
            return []
        return []

    # ------------------------------------------------------------ join
    def _new_addr(self, dev_eui: str) -> int:
        old = (self.sessions.get(dev_eui) or {}).get("dev_addr")
        if old is not None and self.by_addr.get(old) == dev_eui:
            return old
        base = (self.cfg.farm_id & 0x1FF) << 16
        for _ in range(1000):
            addr = base | int.from_bytes(self._rand(2), "big")
            if addr not in self.by_addr and addr != base:
                return addr
        raise RuntimeError("no free device address in this farm's block")

    def _join(self, phy: bytes, rx: list[dict], now: float) -> list[Event]:
        jr = parse_join_request(phy)
        gws = _gateways(rx)
        keys = self.keys(jr.dev_eui)
        if keys is None:
            return [Event("join_unknown", jr.dev_eui, {"join_eui": jr.join_eui, "gateways": gws})]
        if crypto.join_request_mic(keys.app_key, jr.signed) != jr.mic:
            return [Event("join_rejected", jr.dev_eui, {"reason": "wrong AppKey (MIC check failed)", "gateways": gws})]
        s = self.sessions.setdefault(jr.dev_eui, {})
        nonces = s.setdefault("dev_nonces", [])
        if jr.dev_nonce in nonces:
            return [Event("join_rejected", jr.dev_eui, {"reason": f"DevNonce {jr.dev_nonce} used before (replay)",
                                                        "gateways": gws})]
        tx_rx = next((r for r in rx if self.can_transmit(r["gateway"], now)), None)
        if tx_rx is None:
            return [Event("join_rejected", jr.dev_eui, {"reason": "no gateway that can transmit heard the join "
                                                        "(check the packet forwarder's Port Down)", "gateways": gws})]
        nonces.append(jr.dev_nonce)
        del nonces[:-DEVNONCE_MEMORY]
        addr = self._new_addr(jr.dev_eui)
        join_nonce = (s.get("join_nonce", 0) + 1) & 0xFFFFFF
        jn, nid = join_nonce.to_bytes(3, "little"), self.cfg.net_id.to_bytes(3, "little")
        body = (jn + nid + addr.to_bytes(4, "little")
                + bytes([((self.cfg.rx1_dr_offset & 7) << 4) | (self.cfg.rx2_dr & 0x0F), self.cfg.rx1_delay & 0x0F])
                + self.cfg.region.cflist_bytes())
        accept = crypto.join_accept_encrypt(keys.app_key, b"\x20", body)
        nwk, app = crypto.session_keys(keys.app_key, jn, nid, jr.dev_nonce_raw)
        old_addr = s.get("dev_addr")
        if old_addr is not None and old_addr != addr:
            self.by_addr.pop(old_addr, None)
        s.update({"dev_addr": addr, "nwk_s_key": nwk.hex(), "app_s_key": app.hex(), "join_nonce": join_nonce,
                  "fcnt_up": None, "fcnt_down": 0, "pending_conf": None, "joined_at": now,
                  "last_gateway": tx_rx["gateway"], "rx1_delay": self.cfg.rx1_delay,
                  "rx1_dr_offset": self.cfg.rx1_dr_offset})
        s.setdefault("queue", [])
        self.by_addr[addr] = jr.dev_eui
        self.counters["joins"] += 1
        freq, datr = self.cfg.region.rx1(tx_rx["freq"], tx_rx["datr"], 0)
        tx = self._tx(tx_rx["gateway"], accept, tx_rx, self.cfg.region.join_delay1, freq, datr, now, kind="join_accept")
        if tx is None:
            return [Event("join_rejected", jr.dev_eui, {"reason": "gateway sent no timestamp (tmst)", "gateways": gws})]
        return [Event("join", jr.dev_eui, {"dev_addr": f"{addr:08x}", "join_eui": jr.join_eui, "gateways": gws}),
                Event("tx", jr.dev_eui, {"tx": tx})]

    # ------------------------------------------------------------ data
    def _uplink(self, phy: bytes, rx: list[dict], now: float, heard: float | None = None) -> list[Event]:
        df = parse_data(phy)
        dev_eui = self.by_addr.get(df.dev_addr)
        if dev_eui is None:
            self.counters["foreign"] += 1
            return [Event("foreign", None, {"dev_addr": f"{df.dev_addr:08x}"})]
        s = self.sessions[dev_eui]
        nwk, app = bytes.fromhex(s["nwk_s_key"]), bytes.fromhex(s["app_s_key"])
        last = s.get("fcnt_up")
        fcnt = full_fcnt(last, df.fcnt16)
        gws = _gateways(rx)
        if crypto.data_mic(nwk, df.signed, df.dev_addr, fcnt, True) != df.mic:
            self.counters["mic_failed"] += 1
            return [Event("mic_failed", dev_eui, {"gateways": gws})]
        events: list[Event] = []
        retransmission = last is not None and fcnt == last
        if last is not None and fcnt < last:        # replayed or reset without a new join: drop
            return [Event("dropped", dev_eui, {"reason": f"old frame counter {fcnt} (last {last}) – "
                                                         "re-join the device if it was reset"})]
        s["fcnt_up"] = fcnt
        best = rx[0]
        s["last_gateway"] = best["gateway"]

        # confirmation of our last confirmed downlink
        if s.get("pending_conf") is not None and not retransmission:
            events.append(Event("ack", dev_eui, {"acknowledged": df.ack, "id": s["pending_conf"]}))
            s["pending_conf"] = None

        payload = b""
        mac_in = parse_mac(df.fopts)
        if df.fport == 0:
            mac_in += parse_mac(crypto.crypt_payload(nwk, df.frm_payload, df.dev_addr, fcnt, True))
        elif df.fport is not None:
            payload = crypto.crypt_payload(app, df.frm_payload, df.dev_addr, fcnt, True)
        if not retransmission:
            self.counters["uplinks"] += 1
            sf = self.cfg.region.sf_of(best.get("datr") or "")
            events.append(Event("uplink", dev_eui, {
                "fport": df.fport, "payload": payload, "fcnt": fcnt, "confirmed": df.confirmed, "adr": df.adr,
                "gateways": gws, "rssi": best.get("rssi"), "snr": best.get("snr"), "sf": sf,
                "frequency": int(round((best.get("freq") or 0) * 1e6)) or None, "datr": best.get("datr"),
                "dev_addr": f"{df.dev_addr:08x}", "time": best.get("time")}))

        mac_out = b""
        for cmd in mac_in:
            ans = b""
            if cmd.cid == LINK_CHECK:
                sf = self.cfg.region.sf_of(best.get("datr") or "") or 12
                margin = int(max(0, min(254, (best.get("snr") or 0) - REQUIRED_SNR.get(sf, -20))))
                ans = bytes([LINK_CHECK, margin, min(255, len({r["gateway"] for r in rx}))])
            elif cmd.cid == DEVICE_TIME:
                gps = (heard if heard is not None else now) - GPS_EPOCH + LEAP_SECONDS
                ans = bytes([DEVICE_TIME]) + (int(gps) & 0xFFFFFFFF).to_bytes(4, "little") \
                    + bytes([int((gps % 1) * 256) & 0xFF])
            if ans and len(mac_out) + len(ans) <= 15:     # whole answers only, FOpts holds 15 bytes
                mac_out += ans
        queue = s.setdefault("queue", [])
        if not (df.confirmed or mac_out or queue or df.adr_ack_req):
            return events
        tx_rx = next((r for r in rx if self.can_transmit(r["gateway"], now)), None)
        if tx_rx is None:
            events.append(Event("dropped", dev_eui, {"reason": "no gateway that can transmit heard the device"}))
            return events
        delay = s.get("rx1_delay", self.cfg.rx1_delay)               # what the device was told at its join
        freq, datr = self.cfg.region.rx1(tx_rx["freq"], tx_rx["datr"], s.get("rx1_dr_offset", self.cfg.rx1_dr_offset))
        dr = self.cfg.region.dr_of(datr) or 0
        room = MAX_MAC_PAYLOAD[dr] - 8 - len(mac_out)
        if tx_rx.get("tmst") is None:
            events.append(Event("dropped", dev_eui, {"reason": "gateway sent no timestamp (tmst)"}))
            return events
        item = None
        while queue and item is None:
            if len(bytes.fromhex(queue[0]["payload"])) > room:
                bad = queue.pop(0)
                events.append(Event("dropped", dev_eui, {"reason": f"downlink of {len(bytes.fromhex(bad['payload']))} "
                                                         f"bytes too long for {datr}", "id": bad.get("id")}))
            else:
                item = queue.pop(0)
        fcnt_down = s.get("fcnt_down", 0)
        confirmed = bool(item and item.get("confirmed"))
        fport = item["fport"] if item else None
        enc = crypto.crypt_payload(app if fport else nwk, bytes.fromhex(item["payload"]), df.dev_addr, fcnt_down,
                                   False) if item else b""
        frame = build_data(CONF_DOWN if confirmed else UNCONF_DOWN, df.dev_addr, fcnt_down, ack=df.confirmed,
                           fpending=bool(queue), fopts=mac_out, fport=fport, enc_payload=enc)
        frame += crypto.data_mic(nwk, frame, df.dev_addr, fcnt_down, False)
        s["fcnt_down"] = fcnt_down + 1
        if confirmed:
            s["pending_conf"] = item.get("id")
        self.counters["downlinks"] += 1
        tx = self._tx(tx_rx["gateway"], frame, tx_rx, delay, freq, datr, now,
                      kind="data", id=item.get("id") if item else None, fcnt=fcnt_down)
        events.append(Event("tx", dev_eui, {"tx": tx, "id": item.get("id") if item else None,
                                            "fport": fport, "confirmed": confirmed}))
        return events

    def _tx(self, gw: str, phy: bytes, rx: dict, delay: int, freq: float, datr: str, now: float,
            **meta) -> TxRequest | None:
        tmst = rx.get("tmst")
        if tmst is None:
            return None
        sf = self.cfg.region.sf_of(datr) or 12
        ms = airtime_ms(sf, len(phy))
        self.gateways.setdefault(gw, {"push": None, "pull": None, "airtime_ms": []})["airtime_ms"].append((now, ms))
        return TxRequest(gateway=gw, phy=phy, tmst=tmst + delay * 1_000_000,
                         freq=freq, datr=datr, power=self.cfg.region.power, meta={"airtime_ms": round(ms, 1), **meta})

    # ------------------------------------------------------------ downlink queue
    def enqueue(self, dev_eui: str, fport: int, payload: bytes, confirmed: bool = False, item_id: str | None = None) -> bool:
        """Queue a downlink for the device's next uplink (class A). False when the device has not joined."""
        s = self.sessions.get(dev_eui.lower())
        if not s or not s.get("nwk_s_key"):
            return False
        if not 1 <= fport <= 223:
            raise ValueError("FPort must be 1–223")
        q = s.setdefault("queue", [])
        q.append({"fport": fport, "payload": payload.hex(), "confirmed": bool(confirmed),
                  "id": item_id or self._rand(4).hex()})
        del q[:-QUEUE_MAX]
        return True


def _gateways(rx: list[dict]) -> list[dict[str, Any]]:
    return [{"id": r["gateway"], "name": None, "rssi": r.get("rssi"), "snr": r.get("snr")} for r in rx]
