"""Radio link bookkeeping: downlink confirmation / retries and per-device signal quality.

Pure Python (no Home Assistant imports) so it can be unit-tested on its own.
"""
from __future__ import annotations

from typing import Any

RETRY_AFTER_UPLINKS = 2          # Class A: 1st uplink after a send delivers it, the 2nd should carry the answer
EXPIRE_S = 24 * 3600
FINAL = ("confirmed", "delivered", "sent", "failed")

# Demodulation floor (SNR in dB) per spreading factor – link margin = SNR - floor
SF_FLOOR = {6: -5.0, 7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}


class PendingCommands:
    """Downlinks waiting for an answer.

    A command is *confirmed* when the device answers it: it echoes the setting (Milesight devices reply with the
    same bytes on channel 0xFF / 0xFE), its status report shows the expected state (switches, outputs, thermostat
    target), or – DS3604 – it reports the display block as updated. With confirmed downlinks enabled, a network ACK
    makes it *delivered* (or *confirmed* when nothing else can be checked). Without an answer after
    RETRY_AFTER_UPLINKS uplinks the command is resent up to `retries` times, then *failed*. Commands nothing can
    check (device never echoes, no ACK) end as *sent*.
    """

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.items: dict[str, dict[str, Any]] = {}
        for name, p in (data.get("items") or {}).items():
            self.items[name] = p
        self.echoes: bool | None = data.get("echoes")
        self.last: dict[str, Any] | None = data.get("last")

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> "PendingCommands":
        """Load, migrating the 0.16/0.17 'pending' dict ({name: {hex, value, sent}})."""
        if "commands" in meta:
            return cls(meta["commands"])
        old = meta.pop("pending", None) or {}
        pc = cls()
        for name, p in old.items():
            pc.items[name] = _item(name, bytes.fromhex(p["hex"]), None, p.get("sent", 0), value=p.get("value"))
        return pc

    def to_dict(self) -> dict[str, Any]:
        return {"items": self.items, "echoes": self.echoes, "last": self.last}

    # ------------------------------------------------------------------ add
    def add(self, name: str, payload: bytes, fport: int | None, now: float, *, value: Any = None,
            state: dict[str, Any] | None = None, results: list[list[int]] | None = None, prev: dict | None = None,
            confirmed: bool = False, echo: bool = True, blocks: list | None = None) -> dict[str, Any]:
        """echo=False for commands a device never echoes (reboot, request update, time sync, display refresh)."""
        item = _item(name, payload, fport, now, value=value, state=state, results=results, prev=prev,
                     confirmed=confirmed, blocks=blocks)
        if not echo:
            item["no_echo"] = True
        self.items[name] = item
        self._set_last(item)
        return item

    def _set_last(self, item: dict[str, Any]) -> None:
        self.last = {"command": item["name"], "status": item["status"], "attempts": item["attempts"],
                     "detail": item.get("detail"), "time": item.get("done") or item["sent"]}

    def _finish(self, item: dict[str, Any], status: str, detail: str | None, now: float, done: list) -> None:
        item["status"], item["detail"], item["done"] = status, detail, now
        self.items.pop(item["name"], None)
        self._set_last(item)
        done.append(item)

    def _checkable(self, item: dict[str, Any]) -> bool:
        return bool(item.get("state") or item.get("results") or (self.echoes and not item.get("no_echo")))

    # ------------------------------------------------------------- uplinks
    def on_uplink(self, raw_hex: str, decoded: dict[str, Any], now: float, retries: int
                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Returns (to_resend, finished)."""
        resend: list[dict[str, Any]] = []
        done: list[dict[str, Any]] = []
        for item in sorted(self.items.values(), key=lambda p: p["sent"]):
            if now - item.get("first_sent", item["sent"]) > EXPIRE_S:
                self._finish(item, "failed", "no answer within 24 h", now, done)
                continue
            # 1. the device echoes the command bytes
            hx = item["hex"]
            if raw_hex and (_contains(raw_hex, hx) or (hx.startswith("ff") and _contains(raw_hex, "fe" + hx[2:]))):
                if hx.startswith(("ff", "fe")):
                    self.echoes = True
                self._finish(item, "confirmed", "device echoed the setting", now, done)
                continue
            # 2. DS3604 per-block update results
            failed = None
            if item.get("results"):
                for r in decoded.get("update_content_result") or []:
                    key = [r.get("template_id"), r.get("block_id")]
                    if key in item["results"]:
                        if r.get("result") == "success":
                            item["results"].remove(key)
                        else:
                            failed = f"{r.get('block_name') or key}: {r.get('result')}"
                if failed:
                    self._finish(item, "failed", failed, now, done)
                    continue
                if not item["results"]:
                    self._finish(item, "confirmed", "display updated", now, done)
                    continue
            # 3. the status report shows the expected state
            if item.get("state"):
                seen = {k: decoded[k] for k in item["state"] if k in decoded}
                if seen and all(_same(seen[k], item["state"][k]) for k in seen):
                    self._finish(item, "confirmed", "device reports the new state", now, done)
                    continue
            item["uplinks"] = item.get("uplinks", 0) + 1
            if item["uplinks"] < RETRY_AFTER_UPLINKS:
                continue
            if item.get("delivered") and not self._checkable(item):
                self._finish(item, "delivered", "acknowledged by the device", now, done)
            elif not self._checkable(item) and not item.get("confirmed"):
                if self.echoes is None and hx.startswith("ff") and not item.get("no_echo"):
                    self.echoes = False          # this device does not answer settings
                self._finish(item, "sent", "device does not confirm this command", now, done)
            elif item["attempts"] <= retries:
                item["attempts"] += 1
                item["uplinks"] = 0
                item.pop("delivered", None)          # the resend needs its own ACK
                item["sent"] = now
                item["status"] = "retrying"
                item["detail"] = f"no answer, attempt {item['attempts']} of {retries + 1}"
                self._set_last(item)
                resend.append(item)
            else:
                self._finish(item, "failed", f"no answer after {item['attempts']} attempts", now, done)
        return resend, done

    # ---------------------------------------------------------------- ACKs
    def on_ack(self, acknowledged: bool, now: float) -> list[dict[str, Any]]:
        """Network ACK for the oldest confirmed downlink still waiting for one."""
        done: list[dict[str, Any]] = []
        waiting = [p for p in self.items.values() if p.get("confirmed") and not p.get("delivered")]
        if not waiting:
            return done
        item = min(waiting, key=lambda p: p["sent"])
        if acknowledged:
            item["delivered"] = True
            if self._checkable(item):
                item["status"] = "delivered"
                item["detail"] = "acknowledged, waiting for the device's answer"
                self._set_last(item)
            else:
                self._finish(item, "confirmed", "acknowledged by the device", now, done)
        else:
            item["uplinks"] = RETRY_AFTER_UPLINKS - 1     # resend at the next uplink
            item["status"] = "not acknowledged"
            item["detail"] = "the device did not acknowledge, will retry"
            self._set_last(item)
        return done

    def summary(self) -> list[dict[str, Any]]:
        return [{"command": p["name"], "status": p["status"], "attempts": p["attempts"]}
                for p in sorted(self.items.values(), key=lambda p: p["sent"])]


def _item(name: str, payload: bytes, fport: int | None, now: float, **kw: Any) -> dict[str, Any]:
    item = {"name": name, "hex": payload.hex(), "fport": fport, "sent": now, "first_sent": now, "attempts": 1,
            "uplinks": 0, "status": "pending", "detail": None}
    item.update({k: v for k, v in kw.items() if v not in (None, False)})
    return item


def _contains(haystack: str, needle: str) -> bool:
    """Byte-aligned search in hex strings (a match half a byte off is not a match)."""
    i = haystack.find(needle)
    while i != -1:
        if i % 2 == 0:
            return True
        i = haystack.find(needle, i + 1)
    return False


def _same(a: Any, b: Any) -> bool:
    if isinstance(b, bool):
        if isinstance(a, str):
            return a.lower() in ("on", "open", "true", "enable", "enabled", "1") if b else \
                a.lower() in ("off", "close", "closed", "false", "disable", "disabled", "0")
        return bool(a) == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.051
    return a == b


# --------------------------------------------------------------------------
# Signal quality
# --------------------------------------------------------------------------
def link_margin(snr: float | None, sf: int | None) -> float | None:
    if snr is None or sf not in SF_FLOOR:
        return None
    return round(snr - SF_FLOOR[sf], 1)


def link_quality(rssi: float | None, snr: float | None, sf: int | None) -> str | None:
    """excellent / good / fair / poor from the link margin (SNR above the SF's demodulation floor) and RSSI."""
    if rssi is None and snr is None:
        return None
    margin = link_margin(snr, sf)
    order = ["poor", "fair", "good", "excellent"]
    if margin is not None:
        q = 3 if margin >= 15 else 2 if margin >= 10 else 1 if margin >= 5 else 0
    elif snr is not None:
        q = 3 if snr >= 7.5 else 2 if snr >= 2.5 else 1 if snr >= -2.5 else 0
    else:
        q = 3 if rssi >= -90 else 2 if rssi >= -105 else 1 if rssi >= -115 else 0
    if rssi is not None:
        q = min(q, 0 if rssi < -125 else 1 if rssi < -118 else 3)
    return order[q]


def link_advice(quality: str | None, sf: int | None, loss: float | None, gateways: int) -> str:
    tips = []
    if quality == "poor":
        tips.append("Weak link: move the sensor away from metal / concrete, raise the gateway antenna or add a gateway")
    elif quality == "fair":
        tips.append("Usable but little margin: expect lost uplinks in bad conditions")
    if sf is not None and sf >= 11:
        tips.append(f"SF{sf} uses a lot of airtime and battery – better coverage lets ADR move it to a faster rate")
    if loss is not None and loss >= 10:
        tips.append(f"{loss:.0f} % of today's uplinks were lost")
    if gateways == 1 and quality in ("poor", "fair"):
        tips.append("Only one gateway hears this device")
    return ". ".join(tips) + ("." if tips else "OK")


class LinkStats:
    """Daily uplink counts and packet loss (from frame-counter gaps) plus every gateway that heard the device."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        d = data or {}
        self.day: str | None = d.get("day")
        self.received: int = d.get("received", 0)
        self.expected: int = d.get("expected", 0)
        self.last_fcnt: int | None = d.get("last_fcnt")
        self.last_ts: float | None = d.get("last_ts")
        self.loss_yesterday: float | None = d.get("loss_yesterday")
        self.gateways: dict[str, dict[str, Any]] = d.get("gateways", {})

    def to_dict(self) -> dict[str, Any]:
        return {"day": self.day, "received": self.received, "expected": self.expected, "last_fcnt": self.last_fcnt,
                "last_ts": self.last_ts, "loss_yesterday": self.loss_yesterday, "gateways": self.gateways}

    def is_duplicate(self, fcnt: int | None, ts: float) -> bool:
        """Same frame forwarded twice (several gateways / network servers)."""
        return fcnt is not None and fcnt == self.last_fcnt and self.last_ts is not None and abs(ts - self.last_ts) < 30

    def update(self, day: str, ts: float, fcnt: int | None, gateways: list[dict[str, Any]]) -> None:
        if day != self.day:
            if self.day is not None:
                self.loss_yesterday = self.loss()
            self.day, self.received, self.expected = day, 0, 0
        if fcnt is not None:
            gap = fcnt - self.last_fcnt if self.last_fcnt is not None else None
            self.received += 1
            # a counter reset (rejoin) or a huge jump (> 1000 missed) is not counted as loss
            self.expected += gap if gap is not None and 0 < gap <= 1000 else 1
            self.last_fcnt = fcnt
        self.last_ts = ts
        for g in gateways:
            gid = g.get("id") or g.get("name")
            if not gid:
                continue
            self.gateways[gid] = {"name": g.get("name") or gid, "rssi": g.get("rssi"), "snr": g.get("snr"),
                                  "last_heard": ts}
        for gid in [k for k, v in self.gateways.items() if ts - v.get("last_heard", ts) > 7 * 86400]:
            del self.gateways[gid]

    def loss(self) -> float | None:
        if self.expected < 2:
            return None if self.expected == 0 else 0.0
        return round(100 * (1 - self.received / self.expected), 1)

    def heard_by(self, ts: float, within_s: float) -> list[dict[str, Any]]:
        out = [{"id": k, **v} for k, v in self.gateways.items() if ts - v.get("last_heard", 0) <= within_s]
        return sorted(out, key=lambda g: (g.get("rssi") is None, -(g.get("rssi") or 0)))


# --------------------------------------------------------------------------
# Gateway health (per hub)
# --------------------------------------------------------------------------
HUB_COUNTERS = ("uplinks", "duplicates", "downlinks", "joins", "acks", "nacks", "errors")


class GatewayStats:
    """Traffic per physical gateway (from the rxInfo of every uplink), the gateway's own status reports
    (Milesight gateway information, ChirpStack gateway stats / connection state) and network counters per day."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        d = data or {}
        self.day: str | None = d.get("day")
        self.counts: dict[str, int] = {k: 0 for k in HUB_COUNTERS} | d.get("counts", {})
        self.gateways: dict[str, dict[str, Any]] = d.get("gateways", {})
        self.expected: dict[str, dict[str, Any]] = d.get("expected", {})   # announced (DHCP / QR), not heard yet

    def to_dict(self) -> dict[str, Any]:
        return {"day": self.day, "counts": self.counts, "gateways": self.gateways, "expected": self.expected}

    def note_connection(self, gid: str, kind: str) -> bool:
        """How this gateway's data arrives (embedded / chirpstack / built-in). True when new for it."""
        g = self.gateways.get(gid)
        if g is None or not kind:
            return False
        conns = g.setdefault("conn", [])
        if kind in conns:
            return False
        conns.append(kind)
        g.setdefault("found", {"built-in": "semtech"}.get(kind, "mqtt"))
        return True

    def adopt(self, gid: str, info: dict[str, Any]) -> None:
        """A gateway the user confirmed: its name, area, address; it is no longer offered as new."""
        g = self.gateways.get(gid)
        if g is None:
            return
        g["approved"] = True
        for k in ("name", "area", "ip", "mac", "model", "found"):
            if info.get(k):
                g[k] = info[k]

    def _roll(self, day: str) -> None:
        if day == self.day:
            return
        self.day = day
        self.counts = {k: 0 for k in HUB_COUNTERS}
        for g in self.gateways.values():
            g["packets_today"] = 0
            g["devices_today"] = []
            g["rx_today"] = g["tx_today"] = 0

    def _gw(self, gid: str, ts: float, name: str | None = None) -> tuple[dict[str, Any], bool]:
        new = gid not in self.gateways
        g = self.gateways.setdefault(gid, {"name": name or gid, "first_seen": ts, "packets_today": 0,
                                           "devices_today": [], "rx_today": 0, "tx_today": 0, "hours": []})
        if name and g.get("name") in (None, gid):
            g["name"] = name
        return g, new

    def count(self, what: str, day: str, n: int = 1) -> None:
        self._roll(day)
        self.counts[what] = self.counts.get(what, 0) + n

    def uplink(self, day: str, ts: float, deveui: str, gateways: list[dict[str, Any]], duplicate: bool = False
               ) -> list[str]:
        """Count one received frame. Returns ids of gateways seen for the first time."""
        self._roll(day)
        self.counts["duplicates" if duplicate else "uplinks"] += 1
        new = []
        for rx in gateways:
            gid = rx.get("id")
            if not gid:
                continue
            g, is_new = self._gw(gid, ts, rx.get("name"))
            if is_new:
                new.append(gid)
            g["last_heard"] = ts
            g["packets_today"] += 1
            if deveui not in g["devices_today"]:
                g["devices_today"].append(deveui)
            hour = int(ts // 3600)
            hours = [h for h in g.get("hours", []) if h[0] > hour - 24]
            if hours and hours[-1][0] == hour:
                hours[-1][1] += 1
            else:
                hours.append([hour, 1])
            g["hours"] = hours
            if rx.get("rssi") is not None:
                g["last_rssi"] = rx["rssi"]
        return new

    def info(self, gid: str, ts: float, info: dict[str, Any]) -> bool:
        g, new = self._gw(gid, ts, info.get("model") and f"{info.get('model')} {gid[-6:]}")
        g["info"] = info
        g["info_ts"] = ts
        return new

    def stats(self, gid: str, ts: float, day: str, rx: Any, tx: Any) -> bool:
        self._roll(day)
        g, new = self._gw(gid, ts)
        g["stats_ts"] = ts
        g["rx_today"] += int(rx or 0)
        g["tx_today"] += int(tx or 0)
        return new

    def state(self, gid: str, ts: float, online: bool) -> bool:
        g, new = self._gw(gid, ts)
        g["state"] = online
        g["state_ts"] = ts
        return new

    def online(self, gid: str, ts: float, offline_s: float) -> bool | None:
        g = self.gateways.get(gid)
        if g is None:
            return None
        if g.get("state") is not None and g.get("state_ts", 0) >= max(g.get("last_heard", 0), g.get("stats_ts", 0)):
            return bool(g["state"])
        last = max(g.get("last_heard", 0), g.get("info_ts", 0), g.get("stats_ts", 0))
        return (ts - last) <= offline_s if last else None

    def packets_last_hour(self, gid: str, ts: float) -> int:
        g = self.gateways.get(gid) or {}
        hour = int(ts // 3600)
        return sum(n for h, n in g.get("hours", []) if h == hour)

    def hourly(self, gid: str, ts: float) -> list[int]:
        """Packets per hour for the last 24 hours (oldest first)."""
        g = self.gateways.get(gid) or {}
        hour = int(ts // 3600)
        per = {h: n for h, n in g.get("hours", [])}
        return [per.get(h, 0) for h in range(hour - 23, hour + 1)]
