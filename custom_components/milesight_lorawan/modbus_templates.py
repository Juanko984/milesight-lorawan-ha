"""Ready-made sensor templates for RS485 / Modbus probes on Milesight controllers (UC300, UC50x, UC11xx …).

A template knows the probe's registers (address, scale, unit, data type). Applying it to a controller assigns the
registers to consecutive Modbus channels, writes the matching lines into the device's channel map, and lists what
to enter in Milesight ToolBox (slave ID, register address, data type) for each channel – the controller reads the
registers itself and only reports raw numbers. Pure Python (unit-tested)."""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_CHANNELS = 16          # Modbus channels on the UC300 / UC50x


@dataclass(frozen=True)
class Reg:
    key: str               # short id inside the template
    address: int           # register address (0-based, as in the probe's manual)
    name: str
    unit: str | None = None
    scale: str = "1"       # channel-map scale column (multiplier or range)
    offset: float = 0
    device_class: str | None = None
    decimals: int | None = None
    state_class: str | None = None
    signed: bool = False   # INT16 in ToolBox (the integration also accepts it read as UINT16)
    invalid: int | None = None
    optional: bool = False  # not ticked by default
    note: str = ""


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    vendor: str
    slave_id: int
    baud: int
    serial: str            # data bits / parity / stop bits
    function: str          # function code to set in ToolBox
    regs: tuple[Reg, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def defaults(self) -> list[str]:
        return [r.key for r in self.regs if not r.optional]


TEMPLATES: dict[str, Template] = {t.key: t for t in (
    Template(
        "ecowitt_ws90", "Ecowitt WS90 / WN90LP weather station (RS485)", "Ecowitt", 0x90, 9600, "8N1",
        "03 (holding register)",
        (
            Reg("light", 0x0165, "Light", "lx", "10", 0, "illuminance", 0, invalid=0xFFFF),
            Reg("uvi", 0x0166, "UV index", "UV index", "0.1", 0, None, 1, invalid=0xFFFF),
            Reg("temperature", 0x0167, "Temperature", "°C", "0.1", -40, "temperature", 1, invalid=0xFFFF,
                note="raw value has 400 added: (raw − 400) × 0.1"),
            Reg("humidity", 0x0168, "Humidity", "%", "1", 0, "humidity", 0, invalid=0xFFFF),
            Reg("wind_speed", 0x0169, "Wind speed", "m/s", "0.1", 0, "wind_speed", 1, invalid=0xFFFF),
            Reg("gust", 0x016A, "Wind gust", "m/s", "0.1", 0, "wind_speed", 1, invalid=0xFFFF),
            Reg("wind_direction", 0x016B, "Wind direction", "°", "1", 0, None, 0, invalid=0xFFFF,
                note="0–359°"),
            Reg("rain", 0x016C, "Rainfall", "mm", "0.1", 0, "precipitation", 1),
            Reg("pressure", 0x016D, "Absolute pressure", "hPa", "0.1", 0, "atmospheric_pressure", 1,
                invalid=0xFFFF),
            Reg("rain_counter", 0x016E, "Rain counter", "mm", "0.01", 0, "precipitation", 2, "total_increasing",
                optional=True, note="running total"),
        ),
        ("Default address 0x90 (144), 9600 baud 8N1 – every probe on one RS485 bus must use the same baud rate.",
         "Registers 0x0165–0x016E (357–366) – read them as one block if your firmware supports it.",
         "Wind speed is in m/s; Home Assistant can show it in km/h (entity settings → unit)."),
    ),
    Template(
        "cwt_soil_thcph", "CWT soil sensor THCPH-S / 7-in-1 NPK (RS485)", "ComWinTop (CWT)", 1, 4800, "8N1",
        "03 (holding register)",
        (
            Reg("moisture", 0x0000, "Soil moisture", "%", "0.1", 0, "moisture", 1),
            Reg("temperature", 0x0001, "Soil temperature", "°C", "0.1", 0, "temperature", 1, signed=True,
                note="signed: FF9B = −10.1 °C"),
            Reg("ec", 0x0002, "Soil conductivity", "μS/cm", "1", 0, "conductivity", 0),
            Reg("ph", 0x0003, "Soil pH", None, "0.1", 0, "ph", 1),
            Reg("nitrogen", 0x0004, "Nitrogen (N)", "mg/kg", "1", 0, None, 0, optional=True,
                note="7-in-1 NPK version only"),
            Reg("phosphorus", 0x0005, "Phosphorus (P)", "mg/kg", "1", 0, None, 0, optional=True,
                note="7-in-1 NPK version only"),
            Reg("potassium", 0x0006, "Potassium (K)", "mg/kg", "1", 0, None, 0, optional=True,
                note="7-in-1 NPK version only"),
            Reg("salinity", 0x0007, "Soil salinity", "mg/L", "1", 0, None, 0),
            Reg("tds", 0x0008, "Soil TDS", "mg/L", "1", 0, None, 0),
        ),
        ("Default address 1, 4800 baud 8N1. On a bus with a 9600-baud probe (e.g. the WS90), set the soil sensor to "
         "9600 first: write 2 to register 0x07D1 (function 06: 01 06 07 D1 00 02 59 46), then power-cycle it.",
         "Two sensors of the same kind need different addresses: write the new address to register 0x07D0.",
         "Set the temperature channel to INT16 in ToolBox (if it is read as UINT16 the integration converts it)."),
    ),
)}


def channel_line(reg: Reg, channel: int, prefix: str = "") -> str:
    """One channel-map line for a register on a Modbus channel."""
    opts = []
    if reg.signed:
        opts.append("s16")
    if reg.invalid is not None:
        opts.append(f"invalid={reg.invalid}")
    cols = [str(channel), f"{prefix}{reg.name}", reg.unit or "-", reg.scale,
            "-" if not reg.offset else f"{reg.offset:g}", reg.device_class or "-",
            "-" if reg.decimals is None else str(reg.decimals), reg.state_class or "-", " ".join(opts) or "-"]
    while cols and cols[-1] == "-":
        cols.pop()
    return "; ".join(cols)


def plan(key: str, regs: list[str] | None, first: int, slave_id: int | None = None, prefix: str = "",
         max_channels: int = MAX_CHANNELS) -> tuple[list[dict], list[str]]:
    """Registers → consecutive channels from `first`. Returns (rows, errors); a row has channel, slave, register,
    data type, function and the channel-map line."""
    t = TEMPLATES.get(key)
    if t is None:
        return [], [f"unknown template {key}"]
    chosen = [r for r in t.regs if r.key in (regs if regs is not None else t.defaults())]
    if not chosen:
        return [], ["pick at least one value"]
    last = first + len(chosen) - 1
    if first < 1 or last > max_channels:
        return [], [f"{len(chosen)} values from channel {first} need channels {first}–{last}, "
                    f"but the controller has {max_channels} – start lower or untick some values"]
    sid = t.slave_id if slave_id is None else slave_id
    rows = []
    for i, r in enumerate(chosen):
        ch = first + i
        rows.append({"channel": ch, "slave_id": sid, "address": r.address, "name": r.name,
                     "data_type": "INT16" if r.signed else "UINT16", "function": t.function,
                     "line": channel_line(r, ch, prefix), "note": r.note})
    return rows, []


def merge_map(current: str, rows: list[dict], title: str) -> str:
    """The channel map with the template's channels replaced (other lines kept)."""
    from .channel_map import channel_key
    taken = {f"modbus_chn_{r['channel']}" for r in rows}
    kept = []
    for line in (current or "").splitlines():
        head = line.split("#", 1)[0].strip()
        first = head.replace("|", ";").replace("\t", ";").split(";", 1)[0].strip() if head else ""
        if first and channel_key(first) in taken:
            continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    block = [f"# {title}"] + [r["line"] for r in rows]
    return "\n".join(kept + ([""] if kept else []) + block)


def toolbox_table(t: Template, rows: list[dict]) -> str:
    """Markdown: what to enter in Milesight ToolBox → RS485 → Modbus channels."""
    head = ("| Channel | Slave ID | Register (dec / hex) | Data type | Value |\n|---|---|---|---|---|\n")
    body = "".join(f"| {r['channel']} | {r['slave_id']} | {r['address']} / 0x{r['address']:04X} | {r['data_type']} | "
                   f"{r['name']}{' – ' + r['note'] if r['note'] else ''} |\n" for r in rows)
    return (f"**{t.name}** – RS485 {t.baud} baud {t.serial}, function {t.function}\n\n" + head + body + "\n"
            + "\n".join(f"- {n}" for n in t.notes))
