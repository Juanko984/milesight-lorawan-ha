"""Self-check of the EM-range decoders against Milesight's official JS decoders.

    python3 check.py [N]        (N random payloads per model, default 400)
"""
import os, importlib.util, json, pathlib, random, struct, subprocess, sys, tempfile, types

REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / "custom_components" / "milesight_lorawan"
SD = pathlib.Path(os.environ.get("SENSOR_DECODERS", "SensorDecoders")) / 'em-series'
HERE = pathlib.Path(__file__).resolve().parent

pkg = types.ModuleType("mlw"); pkg.__path__ = [str(PKG)]; sys.modules["mlw"] = pkg
spec = importlib.util.spec_from_file_location("mlw.decoders", PKG / "decoders.py")
dec = importlib.util.module_from_spec(spec); sys.modules["mlw.decoders"] = dec
spec.loader.exec_module(dec)

R = random.Random(7)
def u8(v): return bytes([v & 0xFF])
def u16(v): return struct.pack("<H", v & 0xFFFF)
def i16(v): return struct.pack("<h", v)
def u32(v): return struct.pack("<I", v)
def ch(cid, ctype, fn, group=None):
    g = lambda: bytes([cid, ctype]) + fn()
    g.group = group
    return g

# device-info channels handled by every official em-series decoder
INFO = [
    ch(0xFF, 0x01, lambda: u8(R.choice([0x01, 0x10, 0x21]))),
    ch(0xFF, 0x09, lambda: bytes([R.randint(1, 0x20), R.randint(0, 9) << 4])),
    ch(0xFF, 0x0A, lambda: bytes([R.randint(1, 0x20), R.randint(0, 0x20)])),
    ch(0xFF, 0xFF, lambda: bytes([R.randint(0, 3), R.randint(0, 9)])),
    ch(0xFF, 0x16, lambda: bytes(R.randint(0, 255) for _ in range(8))),
    ch(0xFF, 0x0F, lambda: u8(R.randint(0, 3))),
    ch(0xFF, 0xFE, lambda: u8(1)),
    ch(0xFF, 0x0B, lambda: u8(1)),
]
BAT = ch(0x01, 0x75, lambda: u8(R.randint(0, 100)))
TEMP = ch(0x03, 0x67, lambda: i16(R.randint(-400, 850)))
HUM = ch(0x04, 0x68, lambda: u8(R.randint(0, 200)))

def tilt310():
    return b"".join(i16(R.randint(-9000, 9000)) for _ in range(3)) + u8(R.randint(0, 7))
def tilt320():
    return b"".join(i16((R.randint(-9000, 9000) << 1) | R.randint(0, 1)) for _ in range(3))
def rdl_dist():
    return u16(R.choice([R.randint(0, 12000), R.randint(0, 12000), 0xFFFD, 0xFFFF, 0xFFFE]))
def th2_temp():
    return u16(R.choice([R.randint(-400, 850) & 0xFFFF] * 3 + [0x8001, 0x8002, 0x8003]))

GEN = {
    "em300-cl": INFO + [BAT,
        ch(0x03, 0xED, lambda: u8(R.choice([0, 1, 2, 255, 7]))),
        ch(0x83, 0xED, lambda: u8(R.choice([0, 1, 2, 255])) + u8(R.randint(0, 2))),
        ch(0x04, 0xEE, lambda: u8(R.randint(0, 2)))],
    "em300-di-hall": INFO + [BAT,
        ch(0x05, 0x00, lambda: u8(R.randint(0, 1))),
        ch(0x05, 0xC8, lambda: u32(R.randint(0, 10**7))),
        ch(0x05, 0xE1, lambda: u16(R.randint(1, 1000)) + u16(R.randint(1, 1000)) + struct.pack("<f", R.random() * 10**5)),
        ch(0x85, 0x00, lambda: u8(R.randint(0, 1)) + u8(R.randint(0, 1))),
        ch(0x85, 0xE1, lambda: u16(R.randint(1, 1000)) + u16(R.randint(1, 1000)) + struct.pack("<f", R.random() * 10**5) + u8(R.randint(1, 4)))],
    "em300-mld": INFO + [BAT, ch(0x05, 0x00, lambda: u8(R.randint(0, 1)))],
    "em310-tilt": INFO + [BAT, ch(0x03, 0xCF, tilt310)],
    "em320-tilt": INFO + [BAT, ch(0x03, 0xD4, tilt320)],
    "em310-udl": INFO + [BAT, ch(0x03, 0x82, lambda: u16(R.randint(0, 65535))), ch(0x04, 0x00, lambda: u8(R.randint(0, 2)))],
    "em320-th": INFO + [BAT, TEMP, HUM],
    "em320-th-v2": INFO[:7] + [ch(0xFF, 0x0B, lambda: u8(R.randint(0, 1))), BAT,
        ch(0x03, 0x67, th2_temp, "t"),
        ch(0x83, 0x67, lambda: i16(R.randint(-400, 850)) + u8(R.choice([1, 2, 3, 4, 6, 7, 8, 9, 5])), "t"),
        ch(0x93, 0x67, lambda: i16(R.randint(-400, 850)) + i16(R.randint(-100, 100)) + u8(R.choice([0, 0, 1])), "t"),
        ch(0xB3, 0x67, lambda: u8(R.randint(1, 4)) + u8(0), "t"),
        ch(0x04, 0x9A, lambda: u16(R.choice([R.randint(0, 1000)] * 3 + [0xFFFF])), "h"),
        ch(0x04, 0x68, lambda: u8(R.choice([R.randint(0, 200)] * 3 + [0xFF])), "h"),
        ch(0x84, 0x9A, lambda: u16(R.randint(0, 1000)) + u8(R.randint(1, 9)), "h"),
        ch(0x84, 0x68, lambda: u8(R.randint(0, 200)) + u8(R.randint(1, 9)), "h"),
        ch(0x94, 0x9A, lambda: u16(R.randint(0, 1000)) + i16(R.randint(-200, 200)) + u8(R.choice([0, 0, 1])), "h"),
        ch(0x94, 0x68, lambda: u8(R.randint(0, 200)) + u8(R.randint(0, 100)) + u8(R.choice([0, 0, 1])), "h"),
        ch(0xB4, 0x68, lambda: u8(R.randint(1, 2)) + u8(0), "h"),
        ch(0xB4, 0x9A, lambda: u8(R.randint(1, 2)) + u8(0), "h"),
        ch(0x05, 0x6B, lambda: u8(R.randint(0, 1))),
        ch(0x05, 0x9C, lambda: u8(R.randint(1, 5))),
        ch(0xF9, 0x39, lambda: u16(R.randint(1, 3600))),
        ch(0xF9, 0x0B, lambda: bytes(R.randint(0, 1) for _ in range(7)))],
}
_RDL = INFO + [BAT, TEMP,
    ch(0x04, 0x82, rdl_dist),
    ch(0x05, 0x00, lambda: u8(R.randint(0, 2))),
    ch(0x06, 0xC7, lambda: i16(R.randint(-12000, 0))),
    ch(0x84, 0x82, lambda: rdl_dist() + u8(R.randint(0, 3))),
    ch(0x94, 0x82, lambda: rdl_dist() + i16(R.randint(-2000, 2000)) + u8(R.randint(0, 3))),
    ch(0xB4, 0x82, lambda: rdl_dist() + u8(R.randint(0, 4)))]
GEN["em410-rdl"] = _RDL
GEN["em411-rdl"] = _RDL

DECODER = {
    "em300-cl": dec.decode_em300_cl, "em300-di-hall": dec.decode_em300, "em300-mld": dec.decode_em300_mld,
    "em310-tilt": dec.decode_em310_tilt, "em320-tilt": dec.decode_em320_tilt, "em310-udl": dec.decode_em310_udl,
    "em320-th": dec.decode_em300, "em320-th-v2": dec.decode_em320_th_v2,
    "em410-rdl": dec.decode_em410_rdl, "em411-rdl": dec.decode_em411_rdl,
}


def snake(s): return s.lower().replace(" ", "_")

_ALARM_320 = {"Below alarm": "below_threshold_alarm", "Above alarm": "above_threshold_alarm",
              "Between alarm": "between_threshold_alarm", "Outside alarm": "outside_threshold_alarm",
              "Temperature mutation": "mutation_alarm", "Humidity mutation": "mutation_alarm", "unknown": "unknown"}
_ERR = {"collection_err": "collection error", "lower_range_err": "lower range error",
        "over_range_err": "over range error", "unknown": "unknown"}


def _a320(t):
    return _ALARM_320[t] if t in _ALARM_320 else _ALARM_320[t[:-6]] + "_release"   # "... clear"


def normalise(model, js):
    """Map an official JS result to our key names/values. None = key must be absent in ours."""
    o = {}
    for k, v in js.items():
        if k == "ipso_version":
            a, b = v[1:].split("."); o["protocol_version"] = int(a) * 16 + int(b)
        elif k == "reset_event":
            o[k] = v == "reset"
        elif k in ("hardware_version", "firmware_version", "tsl_version", "sn", "lorawan_class", "device_status", "battery"):
            o[k] = v
        elif model == "em300-cl":
            if k == "liquid":
                o[k] = {"critical liquid level alert": "critical"}.get(v, v)
                if v in ("full", "critical liquid level alert"):
                    o["liquid_critical"] = v != "full"
            elif k == "liquid_alarm":
                o["liquid_alarm_status"] = snake(v)
                if v != "unknown": o["liquid_alarm_active"] = not v.endswith("release")
            elif k == "calibration_result":
                o[k] = v
        elif model == "em300-di-hall":
            if k == "gpio": o["input_05"] = 1 if v == "high" else 0
            elif k == "pulse": o["pulse_count"] = v
            elif k in ("water_conv", "pulse_conv", "water"): o[k] = v
            elif k == "gpio_alarm": o[k] = {"gpio alarm release": 0, "gpio alarm": 1}[v]
            elif k == "water_alarm":
                o[k] = {"water outage timeout alarm": 1, "water outage timeout alarm release": 2,
                        "water flow timeout alarm": 3, "water flow timeout alarm release": 4}[v]
        elif model == "em300-mld":
            if k == "leakage_status": o["leak"] = 1 if v == "leak" else 0
        elif model in ("em310-tilt", "em320-tilt"):
            if k.startswith("angle_"): o[k] = v
            elif k.startswith("threshold_"): o[f"angle_{k[-1]}_alarm"] = v == "trigger"
        elif model == "em310-udl":
            if k == "distance": o[k] = v
            elif k == "position": o[k] = v; o["tilted"] = v == "tilt"
        elif model == "em320-th":
            if k in ("temperature", "humidity"): o[k] = v
        elif model == "em320-th-v2":
            if k in ("temperature", "humidity"):
                if isinstance(v, str): o[k] = None; o[f"{k}_error"] = _ERR[v]
                else: o[k] = v
            elif k in ("temperature_error", "humidity_error"):
                o[k.split("_")[0]] = None; o[k] = _ERR[v]
            elif k == "trigger_type": o[k] = v.replace("_", " ")
            elif k == "storage_status": o[k] = v.replace("_", " ")
            elif k in ("temperature_threshold_alarm", "temperature_mutation_alarm",
                       "humidity_threshold_alarm", "humidity_mutation_alarm"):
                base = k.split("_")[0]
                for kk, vv in v.items():
                    if kk in ("temperature", "relative_humidity"): o[base] = vv
                    elif kk.endswith("_change"): o[f"{base}_change"] = vv
                    elif kk == "alarm_type":
                        st = _a320(vv); o[f"{base}_alarm_status"] = st
                        if st != "unknown" and st != "mutation_alarm": o[f"{base}_alarm_active"] = not st.endswith("release")
        elif model in ("em410-rdl", "em411-rdl"):
            if k in ("temperature", "radar_signal_rssi"): o[k] = v
            elif k == "distance": o[k] = None if v in (-1, -2, -3) else v
            elif k == "position": o[k] = v; o["tilted"] = v == "tilt"
            elif k == "event":
                for ev in v:
                    if "distance_alarm" in ev:
                        st = snake(ev["distance_alarm"]); o["distance_alarm_status"] = st
                        if st in ("threshold_alarm", "threshold_alarm_release"):
                            o["distance_alarm_active"] = st == "threshold_alarm"
                    if "distance_mutation" in ev: o["distance_mutation"] = ev["distance_mutation"]
                    if "distance_exception" in ev:
                        st = snake(ev["distance_exception"]); o["distance_exception_alarm_status"] = st
                        if st.startswith("blind"): o["distance_exception_alarm_active"] = not st.endswith("release")
    return o


def payload(gens):
    groups, chosen = set(), []
    for g in R.sample(gens, R.randint(1, min(len(gens), 6))):
        if g.group and g.group in groups:
            continue
        groups.add(g.group); chosen.append(g)
    return b"".join(g() for g in chosen)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    total_bad = 0
    for model, gens in GEN.items():
        cases = []
        sample = json.loads((SD / model / f"{model}-codec.json").read_text()).get("bytes", "")
        if sample:
            cases.append(bytes.fromhex(sample))
        cases += [payload(gens) for _ in range(n)]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([c.hex() for c in cases], f)
        js_file = SD / model / f"{model}-decoder.js"
        res = json.loads(subprocess.run(["node", str(REPO / "tools/run_official_decoder.js"), str(js_file), f.name],
                                        capture_output=True, text=True, check=True).stdout)
        bad = compared = 0
        for c, js in zip(cases, res):
            if "__error" in js:
                bad += 1; print(model, c.hex(), "JS error", js); continue
            exp, got = normalise(model, js), DECODER[model](c)
            for k, v in exp.items():
                compared += 1
                g = got.get(k, None)
                ok = (g is None) if v is None else (
                    k in got and (abs(g - v) <= 1e-3 if isinstance(v, (int, float)) and not isinstance(v, bool)
                                  and isinstance(g, (int, float)) else g == v))
                if not ok:
                    bad += 1
                    if bad <= 10: print(f"  {model} {c.hex()} {k}: js={v!r} ours={g!r}")
        total_bad += bad
        print(f"{model:15s} {DECODER[model].__name__:20s} payloads={len(cases)} keys_compared={compared} mismatches={bad}")
    print("TOTAL mismatches:", total_bad)
    return total_bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
