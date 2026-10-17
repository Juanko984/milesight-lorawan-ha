"""Program Modbus channels on a Milesight UC100 over LoRaWAN (no ToolBox needed).

Byte formats from Milesight's own encoders (SensorDecoders uc100-encoder.js / uc100-v2-encoder.js), fPort 85:
* add / change channel   ff ef 01 <ch> <slave> <address u16le> <type> <quantity | signed << 4>
* channel name           ff ef 02 <ch> <len> <ascii>
* remove channel         ff ef 00 <ch>
* RS485 port (v2 only)   f9 78 <baud u32le> <data bits> <stop bits> <parity 0 none / 1 odd / 2 even>
The UC100 echoes each command in its next uplink, which confirms it. The UC300 and UC50x have no Modbus
downlinks in Milesight's protocol: their channels are set up in ToolBox. Pure Python (unit-tested)."""
from __future__ import annotations

FPORT = 85
MAX_FRAME = 50                 # bytes per downlink (fits DR0 / SF12 in EU868 / AS923)
PUSH_MODELS = {"UC100": 32, "UC100-V2": 32}   # models that accept Modbus channel downlinks -> channels
SERIAL_MODELS = ("UC100-V2",)
NAME_MAX = 16

# register type codes (MB_REG_*)
_INPUT = {("int16", "AB"): 2, ("int16", "BA"): 3, ("int32", "ABCD"): 4, ("int32", "BADC"): 5, ("int32", "CDAB"): 6,
          ("int32", "DCBA"): 7, ("float", "ABCD"): 10, ("float", "BADC"): 11, ("float", "CDAB"): 12,
          ("float", "DCBA"): 13}
_HOLD = {("int16", "AB"): 14, ("int16", "BA"): 15, ("int32", "ABCD"): 16, ("int32", "BADC"): 17, ("int32", "CDAB"): 18,
         ("int32", "DCBA"): 19, ("float", "ABCD"): 22, ("float", "BADC"): 23, ("float", "CDAB"): 24,
         ("float", "DCBA"): 25}
COIL, DISCRETE = 0, 1


def can_push(model_key: str | None) -> bool:
    return (model_key or "") in PUSH_MODELS


def register_type(kind: str, words: int, byte_order: str, is_float: bool = False) -> int:
    """kind: 'input' / 'holding' / 'coil' / 'discrete'."""
    if kind == "coil":
        return COIL
    if kind == "discrete":
        return DISCRETE
    size = "float" if is_float else ("int32" if words == 2 else "int16")
    order = byte_order if size != "int16" else ("BA" if byte_order == "BA" else "AB")
    table = _INPUT if kind == "input" else _HOLD
    if (size, order) not in table:
        raise ValueError(f"unsupported register type {kind} {size} {order}")
    return table[(size, order)]


def kind_of(type_text: str) -> str:
    """ToolBox type text ('Input Register(INT16)', 'Holding Register(INT32)', 'Coil' …) → kind."""
    t = type_text.lower()
    if t.startswith("input"):
        return "input"
    if t.startswith("hold"):
        return "holding"
    return "coil" if t.startswith("coil") else "discrete" if t.startswith("discrete") else "holding"


def channel_cmd(ch: int, slave: int, address: int, rtype: int, quantity: int = 1, signed: bool = False) -> bytes:
    if not 1 <= ch <= 32:
        raise ValueError("channel must be 1–32")
    if not 0 <= slave <= 255 or not 0 <= address <= 0xFFFF or not 1 <= quantity <= 2:
        raise ValueError("slave 0–255, address 0–65535, quantity 1–2")
    return bytes([0xFF, 0xEF, 0x01, ch, slave]) + address.to_bytes(2, "little") + bytes(
        [rtype, (0x10 if signed else 0) | quantity])


def name_cmd(ch: int, name: str) -> bytes:
    raw = "".join(c if 32 <= ord(c) < 127 else "_" for c in name)[:NAME_MAX].encode("ascii")
    return bytes([0xFF, 0xEF, 0x02, ch, len(raw)]) + raw


def remove_cmd(ch: int) -> bytes:
    return bytes([0xFF, 0xEF, 0x00, ch])


def serial_cmd(baud: int, data_bits: int = 8, stop_bits: int = 1, parity: str = "N") -> bytes:
    if baud not in (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200):
        raise ValueError("unsupported baud rate")
    p = {"N": 0, "O": 1, "E": 2}[parity.upper()[:1]]
    return bytes([0xF9, 0x78]) + baud.to_bytes(4, "little") + bytes([data_bits, stop_bits, p])


def parse_serial(serial: str) -> tuple[int, str, int]:
    """'8N1' → (8, 'N', 1)."""
    s = (serial or "8N1").upper()
    return int(s[0]), s[1], int(s[2])


def template_commands(rows: list[dict], names: bool = True) -> list[tuple[str, bytes]]:
    """(label, command) per channel of an applied template (rows from modbus_templates.plan)."""
    out: list[tuple[str, bytes]] = []
    for r in rows:
        rtype = register_type(kind_of(r["type"]), int(r.get("quantity", 1)), r.get("byte_order", "AB"),
                              "float" in r["type"].lower())
        out.append((f"modbus_channel_{r['channel']}",
                    channel_cmd(r["channel"], r["slave_id"], r["address"], rtype, int(r.get("quantity", 1)),
                                bool(r.get("signed")))))
        if names:
            out.append((f"modbus_name_{r['channel']}", name_cmd(r["channel"], r["toolbox_name"])))
    return out


def remove_commands(first: int, last: int) -> list[tuple[str, bytes]]:
    return [(f"modbus_remove_{c}", remove_cmd(c)) for c in range(first, last + 1)]


def pack(commands: list[tuple[str, bytes]], limit: int = MAX_FRAME) -> list[list[tuple[str, bytes]]]:
    """Group commands into downlinks of at most `limit` bytes (order kept)."""
    frames: list[list[tuple[str, bytes]]] = []
    cur: list[tuple[str, bytes]] = []
    size = 0
    for label, cmd in commands:
        if cur and size + len(cmd) > limit:
            frames.append(cur)
            cur, size = [], 0
        cur.append((label, cmd))
        size += len(cmd)
    if cur:
        frames.append(cur)
    return frames


def parse_echo(b: bytes, i: int) -> tuple[dict, int] | None:
    """The UC100's answer to a channel command (fe/ff ef …) from index i (after the 2 header bytes).
    Returns (info, next index) or None."""
    if i >= len(b):
        return None
    op = b[i]
    if op == 0x00 and i + 1 < len(b):
        n = min(len(b), i + 4) if len(b) >= i + 4 else i + 2
        return {"modbus_channel_removed": b[i + 1]}, n
    if op == 0x01 and i + 7 <= len(b):
        ch, slave = b[i + 1], b[i + 2]
        addr = int.from_bytes(b[i + 3:i + 5], "little")
        return {"modbus_channel_set": {"channel": ch, "slave_id": slave, "address": addr, "type": b[i + 5],
                                       "quantity": b[i + 6] & 0x0F, "signed": bool(b[i + 6] & 0x10)}}, i + 7
    if op == 0x02 and i + 3 <= len(b):
        ln = b[i + 2]
        if i + 3 + ln <= len(b):
            return {"modbus_channel_named": {"channel": b[i + 1],
                                             "name": b[i + 3:i + 3 + ln].decode("ascii", "replace")}}, i + 3 + ln
    return None


def changed_commands(new: list[tuple[str, bytes]], sent: dict[str, str] | None) -> list[tuple[str, bytes]]:
    """Editing a template: only the commands that differ from what the controller already got."""
    sent = sent or {}
    return [(label, cmd) for label, cmd in new if sent.get(label) != cmd.hex()]
