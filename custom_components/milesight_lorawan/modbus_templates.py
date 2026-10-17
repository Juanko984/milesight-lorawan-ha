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
    toolbox: str | None = None  # the channel name in ToolBox, when it differs from the entity name


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
    register_type: str = "Holding Register(INT16)"   # ToolBox 'Type' column

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
            Reg("gust", 0x016A, "Gust speed", "m/s", "0.1", 0, "wind_speed", 1, invalid=0xFFFF),
            Reg("wind_direction", 0x016B, "Wind direction", "°", "1", 0, None, 0, invalid=0xFFFF,
                note="0–359°"),
            Reg("rain", 0x016C, "Rainfall", "mm", "0.1", 0, "precipitation", 1),
            Reg("pressure", 0x016D, "Pressure", "hPa", "0.1", 0, "atmospheric_pressure", 1,
                invalid=0xFFFF),
            Reg("rain_counter", 0x016E, "Rain counter", "mm", "0.01", 0, "precipitation", 2, "total_increasing",
                note="running total"),
        ),
        ("Factory address 0x90 (144) – many units are set to 1; use the address your station answers on. "
         "9600 baud 8N1 – every probe on one RS485 bus must use the same baud rate.",
         "Registers 0x0165–0x016E (357–366) – read them as one block if your firmware supports it.",
         "Wind speed is in m/s; Home Assistant can show it in km/h (entity settings → unit)."),
    ),
    Template(
        "cwt_soil_thcph", "CWT 7-in-1 soil / NPK sensor (THCPH-S, RS485)", "ComWinTop (CWT)", 1, 9600, "8N1",
        "04 (input register)",
        (
            Reg("moisture", 0x0000, "Soil moisture", "%", "0.1", 0, "moisture", 1, signed=True, toolbox="Humidity"),
            Reg("temperature", 0x0001, "Soil temperature", "°C", "0.1", 0, "temperature", 1, signed=True,
                toolbox="Temperature", note="0.1 °C, signed: 254 = 25.4 °C, FF9B = −10.1 °C"),
            Reg("ec", 0x0002, "Soil conductivity", "μS/cm", "1", 0, "conductivity", 0, signed=True,
                toolbox="Conductivity"),
            Reg("ph", 0x0003, "Soil pH", None, "0.1", 0, "ph", 1, signed=True, toolbox="PH",
                note="0.1 pH: 30 = 3.0 (the probe reads about 3 in air – its lowest value)"),
            Reg("nitrogen", 0x0004, "Soil nitrogen (N)", "mg/kg", "1", 0, None, 0, signed=True, toolbox="Nitrogen"),
            Reg("phosphorus", 0x0005, "Soil phosphorus (P)", "mg/kg", "1", 0, None, 0, signed=True,
                toolbox="Phosphorus"),
            Reg("potassium", 0x0006, "Soil potassium (K)", "mg/kg", "1", 0, None, 0, signed=True,
                toolbox="Potassium"),
            Reg("salinity", 0x0007, "Soil salinity", "mg/L", "1", 0, None, 0, signed=True, toolbox="Salinity"),
            Reg("tds", 0x0008, "Soil TDS", "mg/L", "1", 0, None, 0, signed=True, toolbox="TDS"),
        ),
        ("Address 1, 9600 baud 8N1, input registers 0–8 (the THCPH-S manual's factory setting is 4800 baud: "
         "write 2 to register 0x07D1 – 01 06 07 D1 00 02 59 46 – and power-cycle it to run it at 9600).",
         "Two probes of the same kind need different addresses: write the new address to register 0x07D0 (2000).",
         "Readings are 0 until the probe is in moist soil; N / P / K are estimates derived from conductivity."),
        "Input Register(INT16)",
    ),
    Template(
        "womaster_ws101ll", "WoMaster WS101LL liquid level sensor (RS485)", "WoMaster", 1, 9600, "8N1",
        "04 (input register)",
        (
            Reg("unit", 0x0002, "Level unit code", None, "1", 0, None, 0, signed=True, toolbox="Unit Type",
                note="unit code of the measured value (11 on a factory WS101LL-3M = mm)"),
            Reg("decimals", 0x0003, "Level decimal points", None, "1", 0, None, 0, signed=True,
                toolbox="Decimal Points"),
            Reg("level", 0x0004, "Water level", "mm", "1", 0, "distance", 0, signed=True, toolbox="Measure Value",
                note="in the unit set by Unit Type; divide by 10^Decimal Points (scale 0.1 for 1 decimal)"),
            Reg("zero", 0x0005, "Level zero point", "mm", "1", 0, "distance", 0, signed=True, toolbox="Zero Point",
                optional=True),
            Reg("full", 0x0006, "Level full point", "mm", "1", 0, "distance", 0, signed=True, toolbox="Full Point",
                note="measuring range (3000 = 3 m on the -3M)"),
            Reg("offset", 0x000D, "Level offset", "mm", "1", 0, "distance", 0, signed=True, toolbox="Offset",
                optional=True),
            Reg("slave", 0x07D0, "Level sensor address", None, "1", 0, None, 0, signed=True, toolbox="SlaveID",
                optional=True, note="register 2000 – read it to check the address"),
        ),
        ("Factory address 1, 9600 baud 8N1 (label on the cable) – give it its own address (e.g. 2) when another "
         "probe on the bus already uses 1.",
         "Power 10–30 V DC. Unit Type, Decimal Points and Full Point only need reading once – untick them to save "
         "channels after commissioning."),
        "Input Register(INT16)",
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
                     "toolbox_name": (r.toolbox or r.name)[:16], "quantity": 1, "type": t.register_type,
                     "byte_order": "AB", "signed": r.signed, "data_type": "INT16" if r.signed else "UINT16",
                     "function": t.function, "line": channel_line(r, ch, prefix), "note": r.note})
    return rows, []


def merge_map(current: str, rows: list[dict], title: str) -> str:
    """The channel map with the template's channels replaced (other lines kept)."""
    from .channel_map import channel_key
    taken = {f"modbus_chn_{r['channel']}" for r in rows}
    kept = []
    for line in (current or "").splitlines():
        if line.strip() == f"# {title}":
            continue                                   # the same template again: one title line
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
    """Markdown laid out like Milesight ToolBox → RS485 (UC300): one row per channel, same columns."""
    head = ("| Channel ID | Name | Slave ID | Address | Quantity | Type | Byte order | Signed |\n"
            "|---|---|---|---|---|---|---|---|\n")
    body = "".join(f"| {r['channel']} | {r['toolbox_name']} | {r['slave_id']} | {r['address']} | {r['quantity']} | "
                   f"{r['type']} | {r['byte_order']} | {'☑' if r['signed'] else '☐'} |\n" for r in rows)
    notes = [f"{r['name']} (register 0x{r['address']:04X}): {r['note']}" for r in rows if r["note"]]
    return (f"**{t.name}** – RS485 {t.baud} baud {t.serial} (ToolBox: RS485 tab on the UC300, Serial tab on the "
            f"UC50x)\n\n" + head + body + "\n"
            + "\n".join(f"- {n}" for n in list(t.notes) + notes))


def block_title(t: Template, rows: list[dict]) -> str:
    return f"{t.name} – channels {rows[0]['channel']}–{rows[-1]['channel']}, slave {rows[0]['slave_id']}"


def remove_from_map(current: str, first: int, last: int, title: str | None = None, name: str | None = None) -> str:
    """Take a template's channels (first…last) and its '# title' line out of the channel map."""
    from .channel_map import channel_key
    gone = {f"modbus_chn_{c}" for c in range(first, last + 1)}
    out = []
    for line in (current or "").splitlines():
        stripped = line.strip()
        if title and stripped == f"# {title}":
            continue
        if not title and name and stripped.startswith(f"# {name}"):      # applied before titles were stored
            continue
        head = line.split("#", 1)[0].strip()
        col = head.replace("|", ";").replace("\t", ";").split(";", 1)[0].strip() if head else ""
        key = channel_key(col) if col else None
        if key and (key in gone or any(key.startswith(g + "_reg_") for g in gone)):
            continue
        out.append(line)
    text = "\n".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip("\n")


def describe_applied(applied: list[dict]) -> str:
    """Markdown list of the templates on a controller."""
    if not applied:
        return "none yet"
    return "\n".join(f"- **{TEMPLATES[a['template']].name if a.get('template') in TEMPLATES else a.get('template')}**"
                      f" – channels {a['first']}–{a['last']}, slave ID {a.get('slave_id')}" for a in applied)
