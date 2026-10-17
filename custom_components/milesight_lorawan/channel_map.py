"""Channel map for configurable controllers (UC300 / UC50x / UC11xx / UC100): turn a raw Modbus register or
analog input into a named sensor with a unit and a scale. Pure Python (unit-tested).

One line per channel, columns separated by ';' (or '|' / tab):

    channel ; name ; unit ; scale ; offset ; device class ; decimals ; state class ; options

    3        ; Tank pressure ; bar ; 0.01
    3.2      ; Flow          ; m³/h ; 0.1 ; 0 ; volume_flow_rate ; 1
    adc_1    ; Borehole level ; m  ; 4-20>0-10        # 4–20 mA mapped onto 0–10 m
    pt100_1  ; Cold room      ; °C

* channel – a Modbus channel number ("3" = modbus_chn_3, "3.2" = channel 3 register 2) or the decoded key
  (adc_1, adv_1, analog_input_1, pt100_1, gpio_counter_1, modbus_chn_3_reg_2 …)
* scale – a multiplier, or a range 'a-b>c-d' that maps the raw span a…b onto c…d (4-20>0-10)
* options – 's16' (the register is a signed 16-bit number: 65535 = -1), 's32', 'lo8' / 'hi8' (one byte of a
  packed register, e.g. SOC / SOH), 'invalid=65535' (the sensor sends
  this when it has no reading: the entity shows unknown); several separated by spaces or commas
* empty columns (or '-') keep the default. Lines starting with '#' are ignored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# sensor device classes accepted in the map (subset of Home Assistant's SensorDeviceClass that fit raw channels)
DEVICE_CLASSES = (
    "apparent_power", "atmospheric_pressure", "battery", "carbon_dioxide", "carbon_monoxide", "conductivity", "current",
    "distance", "energy", "energy_storage", "frequency", "gas", "humidity", "illuminance", "irradiance",
    "moisture", "ph", "power", "power_factor", "precipitation", "precipitation_intensity", "pressure",
    "reactive_power", "signal_strength", "sound_pressure", "speed", "temperature", "voltage", "volume",
    "volume_flow_rate", "volume_storage", "water", "weight", "wind_speed",
)
STATE_CLASSES = ("measurement", "total", "total_increasing")
# units that imply a device class when none is given
_UNIT_CLASS = {
    "°C": "temperature", "°F": "temperature", "K": "temperature", "bar": "pressure", "mbar": "pressure",
    "kPa": "pressure", "Pa": "pressure", "hPa": "pressure", "psi": "pressure", "MPa": "pressure",
    "V": "voltage", "mV": "voltage", "A": "current", "mA": "current", "W": "power", "kW": "power",
    "kWh": "energy", "Wh": "energy", "Hz": "frequency", "m³/h": "volume_flow_rate", "L/min": "volume_flow_rate",
    "L/s": "volume_flow_rate", "m³/s": "volume_flow_rate", "lx": "illuminance", "W/m²": "irradiance",
    "kg": "weight", "g": "weight", "m/s": "speed", "km/h": "speed", "ppm": "carbon_dioxide",
    "mm": "distance", "cm": "distance", "m": "distance", "L": "volume_storage", "m³": "volume_storage",
    "μS/cm": "conductivity", "mS/cm": "conductivity", "dB": "sound_pressure", "dBA": "sound_pressure",
}
_KEY_RE = re.compile(r"(modbus_chn_\d+(?:_reg_\d+)?|adc_\d+|adv_\d+|analog_input_\d+|pt100_\d+|gpio_counter_\d+)")
_NUM = r"[-+]?\d+(?:[.,]\d+)?"
_RANGE_RE = re.compile(rf"\s*({_NUM})\s*(?:-|…|\.\.)\s*({_NUM})\s*>\s*({_NUM})\s*(?:-|…|\.\.)\s*({_NUM})\s*")


@dataclass(frozen=True)
class Channel:
    key: str
    name: str
    unit: str | None = None
    scale: float = 1.0
    offset: float = 0.0
    device_class: str | None = None
    decimals: int | None = None
    state_class: str = "measurement"
    signed: int = 0                        # 16 / 32: the raw register is a signed number
    invalid: tuple = ()                    # raw values that mean 'no reading'
    byte: str | None = None                # "lo" / "hi": use one byte of the register (packed values)

    def apply(self, raw: object) -> object:
        """Scaled value (non-numbers pass through)."""
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return raw
        if raw in self.invalid:
            return None
        if self.byte and isinstance(raw, int):
            raw = (raw & 0xFF) if self.byte == "lo" else ((raw >> 8) & 0xFF)
        if self.signed and raw >= 2 ** (self.signed - 1) and raw < 2 ** self.signed:
            raw = raw - 2 ** self.signed
        v = raw * self.scale + self.offset
        return round(v, self.decimals) if self.decimals is not None else round(v, 6)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def channel_key(text: str) -> str | None:
    t = text.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(?:ch|chn|modbus)?(\d+)(?:[./:](\d+)|reg(\d+))?", t)
    if m:
        reg = m[2] or m[3]
        return f"modbus_chn_{int(m[1])}" + (f"_reg_{int(reg)}" if reg else "")
    return t if _KEY_RE.fullmatch(t) else None


def parse_channel_map(text: str) -> tuple[dict[str, Channel], list[str]]:
    """Returns ({decoded key: Channel}, errors)."""
    out: dict[str, Channel] = {}
    errors: list[str] = []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.split("#", 1)[0].strip() if not line.lstrip().startswith("#") else ""
        if not line:
            continue
        cols = [c.strip() for c in re.split(r"[;|\t]", line)]
        cols = [("" if c == "-" else c) for c in cols] + [""] * 9
        key = channel_key(cols[0])
        if key is None:
            errors.append(f"line {n}: unknown channel '{cols[0]}' (use 3, 3.2, adc_1, pt100_1 …)")
            continue
        if key in out:
            errors.append(f"line {n}: {cols[0]} is listed twice")
            continue
        name = cols[1] or None
        unit = cols[2] or None
        scale, offset = 1.0, 0.0
        try:
            if cols[3]:
                rng = _RANGE_RE.fullmatch(cols[3])
                if rng:
                    a, b, c, d = (_num(x) for x in rng.groups())
                    if a == b:
                        raise ValueError
                    scale = (d - c) / (b - a)
                    offset = c - a * scale
                else:
                    scale = _num(cols[3])
            if cols[4]:
                offset = _num(cols[4]) if not _RANGE_RE.fullmatch(cols[3] or "") else offset + _num(cols[4])
        except ValueError:
            errors.append(f"line {n}: scale / offset must be numbers (or a range like 4-20>0-10)")
            continue
        dc = cols[5].lower().replace(" ", "_") or None
        if dc in ("none", "no"):
            dc = None
        elif dc is None and unit:
            dc = _UNIT_CLASS.get(unit)
        if dc is not None and dc not in DEVICE_CLASSES:
            errors.append(f"line {n}: unknown device class '{cols[5]}'")
            continue
        decimals = None
        if cols[6]:
            if not cols[6].isdigit() or int(cols[6]) > 6:
                errors.append(f"line {n}: decimals must be 0–6")
                continue
            decimals = int(cols[6])
        sc = cols[7].lower() or ("total_increasing" if key.startswith("gpio_counter") else "measurement")
        if sc not in STATE_CLASSES:
            errors.append(f"line {n}: state class must be one of {', '.join(STATE_CLASSES)}")
            continue
        if dc in ("energy", "gas", "water", "volume") and sc == "measurement":
            sc = "total_increasing"               # Home Assistant requires a total for these classes
        if dc in ("volume_storage", "energy_storage") and sc != "measurement":
            errors.append(f"line {n}: {dc} needs the state class measurement")
            continue
        signed, invalid, bad, byte = 0, [], None, None
        for tok in re.split(r"[\s,]+", cols[8].lower()):
            if not tok:
                continue
            if tok in ("s16", "int16", "signed"):
                signed = 16
            elif tok in ("s32", "int32"):
                signed = 32
            elif tok in ("lo8", "hi8"):
                byte = tok[:2]
            elif tok.startswith("invalid="):
                try:
                    invalid += [int(x, 0) for x in tok.split("=", 1)[1].split("/") if x]
                except ValueError:
                    bad = tok
            else:
                bad = tok
        if bad:
            errors.append(f"line {n}: unknown option '{bad}' (use s16, s32, lo8, hi8, invalid=65535)")
            continue
        out[key] = Channel(key, name or _default_name(key), unit, scale, offset, dc, decimals, sc, signed,
                           tuple(invalid), byte)
    return out, errors


def _default_name(key: str) -> str:
    m = re.fullmatch(r"modbus_chn_(\d+)(?:_reg_(\d+))?", key)
    if m:
        return f"Modbus channel {m[1]}" + (f" register {m[2]}" if m[2] else "")
    m = re.fullmatch(r"(adc|adv|analog_input|pt100|gpio_counter)_(\d+)", key)
    labels = {"adc": "Analog input", "adv": "Analog voltage", "analog_input": "Analog input", "pt100": "PT100",
              "gpio_counter": "Pulse counter"}
    return f"{labels[m[1]]} {m[2]}" if m else key
