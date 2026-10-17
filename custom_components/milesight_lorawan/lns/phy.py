"""LoRaWAN 1.0.x PHYPayload parsing and building (pure Python)."""
from __future__ import annotations

from dataclasses import dataclass, field

JOIN_REQUEST, JOIN_ACCEPT, UNCONF_UP, UNCONF_DOWN, CONF_UP, CONF_DOWN, REJOIN, PROPRIETARY = range(8)


class PhyError(ValueError):
    """Not a usable LoRaWAN frame."""


def mtype(phy: bytes) -> int:
    if not phy:
        raise PhyError("empty frame")
    return phy[0] >> 5


@dataclass
class JoinRequest:
    join_eui: str          # hex, big-endian as printed
    dev_eui: str
    dev_nonce: int
    dev_nonce_raw: bytes
    mic: bytes
    signed: bytes          # MHDR | JoinEUI | DevEUI | DevNonce


def parse_join_request(phy: bytes) -> JoinRequest:
    if len(phy) != 23 or mtype(phy) != JOIN_REQUEST:
        raise PhyError("not a join request")
    return JoinRequest(join_eui=phy[1:9][::-1].hex(), dev_eui=phy[9:17][::-1].hex(),
                       dev_nonce=int.from_bytes(phy[17:19], "little"), dev_nonce_raw=phy[17:19],
                       mic=phy[19:23], signed=phy[:19])


@dataclass
class DataFrame:
    mtype: int
    dev_addr: int
    adr: bool
    adr_ack_req: bool
    ack: bool
    fpending_or_classb: bool
    fcnt16: int
    fopts: bytes
    fport: int | None
    frm_payload: bytes
    mic: bytes
    signed: bytes          # everything before the MIC

    @property
    def uplink(self) -> bool:
        return self.mtype in (UNCONF_UP, CONF_UP)

    @property
    def confirmed(self) -> bool:
        return self.mtype in (CONF_UP, CONF_DOWN)


def parse_data(phy: bytes) -> DataFrame:
    mt = mtype(phy)
    if mt not in (UNCONF_UP, UNCONF_DOWN, CONF_UP, CONF_DOWN) or len(phy) < 12:
        raise PhyError("not a data frame")
    fctrl = phy[5]
    fopts_len = fctrl & 0x0F
    pos = 8 + fopts_len
    if len(phy) < pos + 4:
        raise PhyError("frame too short")
    body_end = len(phy) - 4
    fport = phy[pos] if body_end > pos else None
    frm = phy[pos + 1:body_end] if fport is not None else b""
    return DataFrame(mtype=mt, dev_addr=int.from_bytes(phy[1:5], "little"), adr=bool(fctrl & 0x80),
                     adr_ack_req=bool(fctrl & 0x40), ack=bool(fctrl & 0x20), fpending_or_classb=bool(fctrl & 0x10),
                     fcnt16=int.from_bytes(phy[6:8], "little"), fopts=phy[8:8 + fopts_len], fport=fport,
                     frm_payload=frm, mic=phy[body_end:], signed=phy[:body_end])


def build_data(mt: int, dev_addr: int, fcnt: int, *, ack: bool = False, adr: bool = False, fpending: bool = False,
               fopts: bytes = b"", fport: int | None = None, enc_payload: bytes = b"",
               adr_ack_req: bool = False) -> bytes:
    """Frame without MIC (the caller appends crypto.data_mic of it). enc_payload is already encrypted."""
    if len(fopts) > 15:
        raise PhyError("FOpts longer than 15 bytes")
    fctrl = (0x80 if adr else 0) | (0x40 if adr_ack_req else 0) | (0x20 if ack else 0) | (0x10 if fpending else 0) \
        | len(fopts)
    out = bytes([mt << 5]) + dev_addr.to_bytes(4, "little") + bytes([fctrl]) + (fcnt & 0xFFFF).to_bytes(2, "little") \
        + fopts
    if fport is not None:
        out += bytes([fport]) + enc_payload
    return out


def full_fcnt(last: int | None, fcnt16: int) -> int:
    """The 32-bit frame counter closest above the last one seen."""
    if last is None:
        return fcnt16
    cand = (last & 0xFFFF0000) | fcnt16
    if cand < last and last - cand > 0x8000:
        cand += 0x10000
    return cand


# ------------------------------------------------------------------ MAC commands
# uplink (device → server) command lengths, CID → payload bytes (LoRaWAN 1.0.3)
UP_MAC_LEN = {0x01: 1, 0x02: 0, 0x03: 1, 0x04: 0, 0x05: 1, 0x06: 2, 0x07: 1, 0x08: 0, 0x09: 0, 0x0A: 1, 0x0D: 0}
LINK_CHECK, DEVICE_TIME, DEV_STATUS = 0x02, 0x0D, 0x06


@dataclass
class MacCommand:
    cid: int
    payload: bytes = b""


def parse_mac(data: bytes) -> list[MacCommand]:
    out, i = [], 0
    while i < len(data):
        cid = data[i]
        n = UP_MAC_LEN.get(cid)
        if n is None:                       # unknown: the rest can't be parsed safely
            break
        out.append(MacCommand(cid, data[i + 1:i + 1 + n]))
        i += 1 + n
    return out


@dataclass
class TxRequest:
    """A downlink frame for one gateway (radio parameters for the Semtech txpk)."""
    gateway: str
    phy: bytes
    tmst: int | None
    freq: float
    datr: str
    immediate: bool = False
    power: int = 14
    meta: dict = field(default_factory=dict)
