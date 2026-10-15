"""Self-check for the AM10x / AM30xL / DS3604 decoders against the official Milesight JS decoders.

    python3 check.py [N]     (N random payloads per model, default 400)
"""
import os, importlib.util, json, pathlib, random, struct, subprocess, sys, tempfile, types

REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / "custom_components" / "milesight_lorawan"
SD = pathlib.Path(os.environ.get("SENSOR_DECODERS", "SensorDecoders"))
HERE = pathlib.Path(__file__).resolve().parent
pkg = types.ModuleType("mlw"); pkg.__path__ = [str(PKG)]; sys.modules["mlw"] = pkg
spec = importlib.util.spec_from_file_location("mlw.decoders", PKG / "decoders.py")
dec = importlib.util.module_from_spec(spec); sys.modules["mlw.decoders"] = dec; spec.loader.exec_module(dec)

R = random.Random(7)
def u8(lo=0, hi=255): return bytes([R.randint(lo, hi)])
def u16(lo=0, hi=0xFFFF): return struct.pack("<H", R.randint(lo, hi))
def i16(lo, hi): return struct.pack("<h", R.randint(lo, hi))
def rb(n): return bytes(R.randint(0, 255) for _ in range(n))
def ch(cid, ctype, gen): return lambda: bytes([cid, ctype]) + gen()

# ---- common device-info channels ----------------------------------------------------------
def _hw(): return bytes([R.randint(1, 0x19), R.choice([0x00, 0x10, 0x20, 0x30, 0x90, 0xA0, 0xF0])])
def info_v1(sn_type):  # AM10x / DS3604 header
    return [ch(0xFF, 0x01, lambda: u8()), ch(0xFF, 0x09, _hw), ch(0xFF, 0x0A, lambda: rb(2)),
            ch(0xFF, 0xFF, lambda: rb(2)), ch(0xFF, sn_type, lambda: rb(8 if sn_type == 0x16 else 6)),
            ch(0xFF, 0x0F, lambda: u8(0, 3)), ch(0xFF, 0xFE, lambda: b"\x01"), ch(0xFF, 0x0B, lambda: b"\x01")]

INFO_30XL = [ch(0xFF, 0x0B, lambda: u8(0, 1)), ch(0xFF, 0x01, lambda: u8()), ch(0xFF, 0x16, lambda: rb(8)),
             ch(0xFF, 0xFF, lambda: rb(2)), ch(0xFF, 0x09, lambda: rb(2)), ch(0xFF, 0x0A, lambda: rb(2)),
             ch(0xFF, 0x0F, lambda: u8(0, 3)), ch(0xFF, 0xFE, lambda: u8(0, 1))]

# ---- AM10x --------------------------------------------------------------------------------
BAT = ch(0x01, 0x75, lambda: u8(0, 100))
TEMP = ch(0x03, 0x67, lambda: i16(-400, 850))
HUM = ch(0x04, 0x68, lambda: u8(0, 200))
CO2 = ch(0x07, 0x7D, lambda: u16(0, 10000))
def am10x_cfg(types_):
    lens = {0x03: 2, 0x06: 9, 0x10: 1, 0x11: 4, 0x17: 2, 0x27: 1, 0x2D: 1, 0x2F: 1, 0x3B: 1, 0x56: 1, 0x57: 1,
            0x59: 1, 0x5A: 2, 0x68: 1, 0x69: 1, 0x6A: 3, 0x75: 7, 0x85: 1, 0x86: 1, 0x39: 5, 0x54: 5, 0x87: 3,
            0xF0: 4}
    gens = []
    for t in types_:
        if t == 0x3A:
            gens.append(lambda: bytes([R.choice([0xFE, 0xFF]), 0x3A]) + (lambda n: bytes([n]) + rb(6 * n))(R.randint(0, 3)))
        elif t == 0x1A:
            gens.append(lambda: bytes([R.choice([0xFE, 0xFF]), 0x1A]) + (lambda m: bytes([m]) + (rb(2) if m == 2 else b""))(R.randint(0, 3)))
        else:
            gens.append((lambda t: lambda: bytes([R.choice([0xFE, 0xFF]), t]) + rb(lens[t]))(t))
    gens.append(ch(0xFF, 0x18, lambda: rb(2)))
    return gens
CFG_102 = [0x03, 0x06, 0x10, 0x11, 0x17, 0x27, 0x2D, 0x2F, 0x3A, 0x3B, 0x56, 0x57, 0x59, 0x5A, 0x68, 0x69, 0x6A, 0x75, 0x85, 0x86]
CFG_102L = [0x03, 0x06, 0x10, 0x11, 0x17, 0x27, 0x2F, 0x3A, 0x3B, 0x57, 0x59, 0x68, 0x69, 0x6A]
CFG_103 = CFG_102 + [0x1A, 0x39, 0x54, 0x87, 0xF0]
CFG_103L = CFG_102L + [0x1A, 0x39, 0x54, 0x87]
HIST7 = ch(0x20, 0xCE, lambda: rb(4) + i16(-400, 850) + u8(0, 200))
HIST9 = ch(0x20, 0xCE, lambda: rb(4) + i16(-400, 850) + u8(0, 200) + u16(0, 10000))
ACT = ch(0x05, 0x6A, lambda: u16())
ILL = ch(0x06, 0x65, lambda: u16() + u16() + u16())
TVOC = ch(0x08, 0x7D, lambda: u16(0, 60000))
PRES = ch(0x09, 0x73, lambda: u16(3000, 11000))

# ---- AM30xL -------------------------------------------------------------------------------
def am30xl(co2):
    g = [BAT, ch(0x03, 0x67, lambda: i16(-200, 600)), HUM,
         ch(0x05, 0x9F, lambda: u16()), ch(0x05, 0x00, lambda: u8(0, 2)),
         ch(0x06, 0xCB, lambda: u8(0, 5)), ch(0x06, 0x9D, lambda: u16(0, 60000)),
         ch(0xB3, 0x67, lambda: u8(0, 2)), ch(0xB4, 0x68, lambda: u8(0, 1)), ch(0xB6, 0xCB, lambda: u8(0, 1)),
         ch(0xB6, 0x9D, lambda: u8(0, 2)),
         ch(0x83, 0x67, lambda: i16(-200, 600) + u8(15, 24)), ch(0x86, 0x9D, lambda: u16(0, 60000) + u8(15, 18))]
    hist = 18 if co2 else 15
    g += [ch(0x20, 0xCE, lambda: rb(hist)), ch(0x21, 0xCE, lambda: rb(hist))]
    cfg = {(0xFF, 0xF2): 2, (0xFF, 0xF5): 1, (0xFF, 0x2E): 1, (0xFF, 0x25): 1, (0xFF, 0x06): 9, (0xFF, 0x95): 2,
           (0xFF, 0x96): 8, (0xFF, 0x68): 1, (0xFF, 0x69): 1, (0xFF, 0x27): 1, (0xFF, 0x10): 1, (0xFF, 0x4A): 1,
           (0xF9, 0xBD): 3, (0xF9, 0xBE): 4, (0xF9, 0xBF): 5, (0xF9, 0x63): 4, (0xF9, 0x66): 1,
           (0xFD, 0x6B): 4, (0xFD, 0x6C): 8, (0xFD, 0x6D): 1}
    sel = {(0xFF, 0x18): [3, 4], (0xFF, 0x6A): [0, 1], (0xF9, 0xC0): [0, 1], (0xF9, 0xBC): [0, 1]}
    ea = [0, 1]
    if co2:
        g += [ch(0x07, 0x7D, lambda: u16(0, 10000)), ch(0xB7, 0x7D, lambda: u8(0, 2)),
              ch(0x87, 0x7D, lambda: u16(0, 10000) + u8(15, 20))]
        cfg.update({(0xFF, 0x39): 5, (0xFF, 0x87): 3, (0xF9, 0xC4): 6})
        sel[(0xFF, 0x18)] = [3, 4, 5]; sel[(0xFF, 0x1A)] = [0, 3]; ea = [0, 1, 2]
    for k, n in cfg.items():
        g.append((lambda k, n: lambda: bytes(k) + rb(n))(k, n))
    for k, firsts in sel.items():
        g.append((lambda k, firsts: lambda: bytes(k) + (lambda f: bytes([f]) + rb(0 if k == (0xFF, 0x1A) else 1 if k != (0xFF, 0x6A) else 2))(R.choice(firsts)))(k, firsts))
    g.append(lambda: bytes([0xFF, 0xEA]) + bytes([R.choice(ea) | R.choice([0, 0x80])]) + rb(2))
    return INFO_30XL + g

# ---- DS3604 -------------------------------------------------------------------------------
def _ds_block():
    blk = R.randint(0, 12) | (R.randint(0, 3) << 6)
    if (blk & 0x3F) <= 10:
        txt = R.choice([b"Milesight", b"hello", "Größe".encode(), b"", b"QR:https://x.y"])
        return bytes([blk, len(txt)]) + txt
    return bytes([blk])
DS = info_v1(0x16) + [BAT, ch(0xFF, 0x2E, lambda: u8(0, 4)), ch(0xFF, 0x73, lambda: u8(0, 3)),
                      ch(0xFE, 0x73, lambda: u8(0, 3)), ch(0xFB, 0x01, _ds_block),
                      ch(0xFA, 0x01, lambda: u8() + u8(0, 5)), ch(0xFA, 0x02, lambda: rb(2)),
                      ch(0xFA, 0x03, lambda: u8() + u8(0, 5))]
DS += [(lambda t, n: lambda: bytes([R.choice([0xFE, 0xFF]), t]) + rb(n))(t, n)
       for t, n in {0x03: 2, 0x10: 1, 0x25: 1, 0x27: 1, 0x28: 1, 0x3E: 1, 0x3D: 1, 0x66: 1, 0x82: 1, 0x89: 5,
                    0x90: 1}.items()]

GEN = {
    "am-series/am102": info_v1(0x16) + [BAT, TEMP, HUM, HIST7] + am10x_cfg(CFG_102),
    "am-series/am102l": info_v1(0x16) + [BAT, TEMP, HUM, HIST7] + am10x_cfg(CFG_102L),
    "am-series/am103": info_v1(0x16) + [BAT, TEMP, HUM, CO2, HIST9] + am10x_cfg(CFG_103),
    "am-series/am103l": info_v1(0x16) + [BAT, TEMP, HUM, CO2, HIST9] + am10x_cfg(CFG_103L),
    "am-series/am104": info_v1(0x08) + [BAT, TEMP, HUM, ACT, ILL] + am10x_cfg(CFG_102 + [0xF0]),
    "am-series/am107": info_v1(0x08) + [BAT, TEMP, HUM, ACT, ILL, CO2, TVOC, PRES] + am10x_cfg(CFG_103),
    "am-series/am304l": am30xl(False),
    "am-series/am305l": am30xl(True),
    "ds-series/ds3604": DS,
}
DECODER = {"am-series/am102": "decode_am102", "am-series/am102l": "decode_am102",
           "am-series/am103": "decode_am103", "am-series/am103l": "decode_am103",
           "am-series/am104": "decode_am104", "am-series/am107": "decode_am107",
           "am-series/am304l": "decode_am304l", "am-series/am305l": "decode_am305l",
           "ds-series/ds3604": "decode_ds3604"}

# ---- JS -> our keys -----------------------------------------------------------------------
_CLASS = {0: "Class A", 1: "Class B", 2: "Class C", 3: "Class CtoB"}
_TEMP_AL = {16: "below_threshold_alarm_release", 17: "below_threshold_alarm", 18: "above_threshold_alarm_release",
            19: "above_threshold_alarm", 20: "between_threshold_alarm_release", 21: "between_threshold_alarm",
            22: "exceed_tolerance_alarm_release", 23: "exceed_tolerance_alarm"}
_LUX_AL = {16: "dim", 17: "bright"}
_CO2_AL = {16: "polluted_alarm_release", 17: "polluted_alarm", 18: "bad_alarm_release", 19: "bad_alarm"}
_ANOM = [("temperature_collection_anomaly", "Temperature"), ("humidity_collection_anomaly", "Humidity"),
         ("illuminace_collection_anomaly", "Illuminance level"), ("Lux_collection_anomaly", "Illuminance"),
         ("co2_collection_anomaly", "CO2")]
_ANOM_TXT = {0: "collection failed", 1: "out of range"}


def normalise(model: str, js: dict) -> dict:
    out = {}
    m = model.split("/")[-1]
    for k in ("battery", "temperature", "humidity", "co2", "pressure", "sn", "firmware_version", "tsl_version",
              "hardware_version"):
        if k in js:
            out[k] = js[k]
    if m.startswith("am30"):
        if "device_status" in js:
            out["device_status"] = "on" if js["device_status"] else "off"
        if "ipso_version" in js:
            out["protocol_version"] = js["ipso_version"]
        if "lorawan_class" in js:
            out["lorawan_class"] = _CLASS.get(js["lorawan_class"], "unknown")
        pir = js.get("pir") or {}
        if "pir_status" in pir:
            out["pir"] = pir["pir_status"] == 1
            out["occupancy"] = 1 if pir["pir_status"] == 1 else 0
        if "pir_count" in pir:
            out["pir_count"] = pir["pir_count"]
        if "als_level" in js:
            out["light_level"] = js["als_level"]
        if "Lux" in js:
            out["illuminance_lux"] = js["Lux"]
        for jk, name, tbl in (("temperature_alarm", "temperature", _TEMP_AL), ("Lux_alarm", "illuminance", _LUX_AL),
                              ("co2_alarm", "co2", _CO2_AL)):
            if jk in js:
                out[f"{name}_alarm_status"] = tbl.get(js[jk]["alarm_type"], "unknown")
        order = [k for k in js if k.endswith("_collection_anomaly")]
        errs = [f"{dict(_ANOM)[k]}: {_ANOM_TXT.get(js[k]['type'], 'unknown')}" for k in order]
        if errs:
            out["sensor_error"] = ", ".join(errs)
        elif any(k in out for k in ("temperature", "humidity", "co2", "light_level", "illuminance_lux")):
            out["sensor_error"] = "OK"
    else:
        for k in ("lorawan_class", "device_status"):
            if k in js:
                out[k] = js[k]
        if "reset_event" in js:
            out["reset_event"] = js["reset_event"] == "reset"
        if "illumination" in js:
            out["illuminance_lux"] = js["illumination"]
        for k in ("infrared_and_visible", "infrared"):
            if k in js:
                out[k] = js[k]
        if "activity" in js:
            out["pir_activity"] = js["activity"]
        if "tvoc" in js:
            out["tvoc_ppb"] = js["tvoc"]
        if "button_status" in js:
            out["button_event"] = js["button_status"]
        if "current_template_id" in js:
            out["current_template_id"] = js["current_template_id"]
        for k in ("template_1", "template_2", "template_3", "template_4"):
            if js.get(k):                      # JS creates an empty dict for image / unknown blocks
                out[k] = js[k]
        if "update_content_result" in js:      # JS keeps a stale block_name (function-scoped var) for ids > 10
            out["update_content_result"] = [{k: v for k, v in r.items() if k != "block_name" or r["block_id"] <= 10}
                                            for r in js["update_content_result"]]
    return out


IGNORED_OURS = {"button_events", "temperature_alarm_active", "illuminance_alarm_active", "co2_alarm_active",
                "protocol_version"}


def run_js(folder, payloads):
    name = folder.split("/")[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payloads, f)
    res = subprocess.run(["node", str(REPO / "tools" / "run_official_decoder.js"),
                          str(SD / folder / f"{name}-decoder.js"), f.name], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-3
    return a == b


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    total = bad = 0
    for folder, gens in GEN.items():
        name = folder.split("/")[-1]
        codec = json.loads((SD / folder / f"{name}-codec.json").read_text())
        payloads = [codec["bytes"].lower()] if "bytes" in codec else []
        for g in gens:                     # every channel at least once on its own
            payloads.append(g().hex())
        while len(payloads) < n + len(gens):
            payloads.append(b"".join(R.choice(gens)() for _ in range(R.randint(1, 8))).hex())
        js_out = run_js(folder, payloads)
        fn = getattr(dec, DECODER[folder])
        mism = 0; errs = 0
        for hx, js in zip(payloads, js_out):
            if "__error" in js:
                errs += 1
                continue
            exp = normalise(folder, js)
            got = fn(bytes.fromhex(hx))
            diffs = [(k, exp[k], got.get(k, "<missing>")) for k in exp if not same(exp[k], got.get(k, "<missing>"))]
            extra = [k for k in got if k not in exp and k not in IGNORED_OURS]
            if diffs or extra:
                mism += 1
                if mism <= 5:
                    print(f"  {folder} {hx}\n    diffs={diffs} extra={extra}")
        total += len(payloads); bad += mism
        print(f"{folder:22s} {DECODER[folder]:15s} payloads={len(payloads)} js_errors={errs} mismatches={mism}")
    print(f"TOTAL payloads={total} mismatches={bad}")
    return bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
