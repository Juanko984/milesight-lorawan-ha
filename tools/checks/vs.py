"""Self-check of new VS decoders against the official Milesight JS decoders.

    python3 check.py            (needs node)
"""
import os, importlib.util, json, pathlib, random, struct, subprocess, sys, types

REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / "custom_components" / "milesight_lorawan"
SD = pathlib.Path(os.environ.get("SENSOR_DECODERS", "SensorDecoders")) / 'vs-series'
HERE = pathlib.Path(__file__).resolve().parent
pkg = types.ModuleType("mlw"); pkg.__path__ = [str(PKG)]; sys.modules["mlw"] = pkg
spec = importlib.util.spec_from_file_location("mlw.decoders", PKG / "decoders.py")
dec = importlib.util.module_from_spec(spec); sys.modules["mlw.decoders"] = dec; spec.loader.exec_module(dec)

random.seed(7)
R = random.randint
u16 = lambda v: struct.pack("<H", v)
i16 = lambda v: struct.pack("<h", v)
u32 = lambda v: struct.pack("<I", v)
def seg(*parts): return lambda: b"".join(p() if callable(p) else bytes(p) for p in parts)
def rb(n): return lambda: bytes(R(0, 255) for _ in range(n))
B = lambda *choices: (lambda: bytes([random.choice(choices)]))

INFO_V1 = [seg([0xFF, 0x01], rb(1)), seg([0xFF, 0x09], rb(2)), seg([0xFF, 0x16], rb(8))]
INFO_V2 = INFO_V1 + [seg([0xFF, 0x0A], rb(2)), seg([0xFF, 0xFF], rb(2)), seg([0xFF, 0x0F], B(0, 1, 2, 3)),
                     seg([0xFF, 0xFE], B(1)), seg([0xFF, 0x0B], B(1))]
def dl(cid, table):
    return [seg([cid, t], rb(n)) for t, n in table.items()]
def dl_ext(table):
    return [seg([0xF9, t], rb(n)) for t, n in table.items()] + [seg([0xF8, t], rb(n), B(0)) for t, n in table.items()]

VS132 = INFO_V1 + [seg([0xFF, 0x1F], rb(4)), seg([3, 0xD2], lambda: u32(R(0, 2**32 - 1))),
                   seg([4, 0xD2], lambda: u32(R(0, 2**32 - 1))), seg([5, 0xCC], rb(4))] + dl(0xFF, dec._VS132_SKIP)

def vs133_hist():
    t = random.choice(sorted(dec._VS133_HISTORY_9 | dec._VS133_HISTORY_8))
    return bytes([0x20, 0xCE]) + rb(4)() + bytes([t]) + rb(4 if t in dec._VS133_HISTORY_9 else 3)()
VS133 = INFO_V1 + [seg([0xFF, 0x1F], rb(4)), seg([0xFF, 0xD4], rb(5))] + \
    [seg([c, 0xD2], lambda: u32(R(0, 2**32 - 1))) for c in (3, 4, 6, 7, 9, 10, 12, 13, 0x11, 0x12, 0x14, 0x15, 0x17, 0x18, 0x1A, 0x1B)] + \
    [seg([c, 0xCC], rb(4)) for c in (5, 8, 0xB, 0xE, 0x13, 0x16, 0x19, 0x1C)] + \
    [seg([0x0F, 0xE3], rb(4)), seg([0x1D, 0xE3], rb(4)),
     seg([0x10, 0xE4], lambda: bytes([random.choice([1, 2, 3, 4, R(0, 255)])]), rb(4)),
     seg([0x1E, 0xE4], lambda: bytes([R(1, 4)]), rb(4)),
     seg([0x50, 0xFC], rb(1), lambda: bytes([random.choice([0, 0, 1, 2, 3, R(0, 255)])]), B(0, 1, 2)),
     vs133_hist] + dl(0xFF, dec._VS133_SKIP) + dl_ext(dec._VS133_SKIP_EXT)

VS330 = INFO_V2 + [seg([1, 0x75], lambda: bytes([R(0, 100)])), seg([2, 0x82], rb(2)), seg([3, 0x8E], B(0, 1)),
                   seg([4, 0x8E], B(0, 1))] + dl(0xFF, dec._VS330_SKIP)

TEMP = lambda: i16(R(-400, 850))
def vs35_hist():
    t = R(0, 1)
    return bytes([0x20, 0xCE]) + rb(4)() + bytes([t]) + rb(4 if t == 0 else 8)()
VS35_COMMON = INFO_V2 + [seg([1, 0x75], lambda: bytes([R(0, 100)])), seg([4, 0xCC], rb(4)), seg([5, 0xCC], rb(4)),
                         seg([0x84, 0xCC], rb(4), B(0, 1, 2, 3, 4)), seg([0x85, 0xCC], rb(4), B(0, 1, 2, 3, 4)),
                         seg([0x0A, 0xEF], rb(4)), vs35_hist]
SAFE_DL = lambda t: {k: v for k, v in t.items() if k not in (0x96,)}   # d2d config decoding not exercised
VS350 = VS35_COMMON + [seg([3, 0x67], TEMP), seg([0x83, 0x67], TEMP, B(0, 1, 3, 4, 2)), seg([0x81, 0xEE], rb(1))] + \
    dl(0xFF, SAFE_DL(dec._VS350_SKIP)) + dl_ext(dec._VS_EXT_REPORT_TYPE)
VS351 = VS35_COMMON + [seg([3, 0x67], TEMP), seg([0x83, 0x67], TEMP, B(0, 1, 3, 4, 2)), seg([0xFF, 0xCC], B(0, 1, 2, 3))] + \
    dl(0xFF, SAFE_DL(dec._VS351_SKIP)) + dl_ext(dec._VS351_SKIP_EXT)
VS360 = VS35_COMMON + [seg([2, 0x75], lambda: bytes([R(0, 100)])), seg([3, 0xF4], B(0, 1, 2, 3), B(0, 1, 2))] + \
    dl(0xFF, SAFE_DL(dec._VS360_SKIP)) + dl_ext(dec._VS_EXT_REPORT_TYPE)

GEN = {"vs132": VS132, "vs133": VS133, "vs135": VS133, "vs330": VS330, "vs350": VS350, "vs351": VS351, "vs360": VS360}
FUNC = {"vs132": dec.decode_vs132, "vs133": dec.decode_vs133, "vs135": dec.decode_vs135, "vs330": dec.decode_vs330,
        "vs350": dec.decode_vs350, "vs351": dec.decode_vs351, "vs360": dec.decode_vs360}
EXTRA_OK = ("_alarm_active",)        # our-only keys


def normalise(model: str, js: dict) -> dict:
    """Map an official JS decoder result to our key names (keys without a counterpart are dropped)."""
    import re
    r: dict = {}
    for k, v in js.items():
        if k == "ipso_version":
            major, minor = v[1:].split(".")
            r["protocol_version"] = int(major) * 16 + int(minor)
        elif k in ("protocol_version", "hardware_version", "firmware_version", "tsl_version", "sn", "lorawan_class",
                   "device_version", "battery", "distance", "calibration_status", "battery_node", "power_status",
                   "current_sensitivity"):
            r[k] = v
        elif k == "battery_main": r["battery"] = v
        elif k == "reset_event": r[k] = v == "reset"
        elif k == "device_status": r[k] = v
        elif k == "occupancy": r[k] = {"occupied": 1, "vacant": 0}.get(v, 0)
        elif k == "temperature": r[k] = v
        elif k in ("total_counter_in", "total_counter_out", "total_in", "total_out"):
            r["people_total_" + k.rsplit("_", 1)[1]] = v
        elif k in ("periodic_counter_in", "periodic_counter_out", "period_in", "period_out"):
            r["people_" + k.rsplit("_", 1)[1]] = v
        elif k in ("temperature_alarm", "total_count_alarm", "period_count_alarm"):
            r[k + "_status"] = v.replace(" ", "_")
        elif k == "timestamp" and model not in ("vs133", "vs135"): r["device_timestamp"] = v
        elif k == "event":
            for ev in v: r[ev["type"] + "_alarm_status"] = ev["status"]
        elif m := re.fullmatch(r"line_(\d)(_child)?_total_(in|out)", k):
            r[k] = v
            if m[1] == "1" and not m[2]: r[f"people_total_{m[3]}"] = v
        elif m := re.fullmatch(r"line_(\d)(_child)?_period_(in|out)", k):
            r[f"line_{m[1]}{m[2] or ''}_{m[3]}"] = v
            if m[1] == "1" and not m[2]: r[f"people_{m[3]}"] = v
        elif re.fullmatch(r"region_\d+(_child)?_count", k): r[k] = v
        elif m := re.fullmatch(r"(region_\d+(?:_child)?)_(avg|max)_dwell", k):
            r[f"{m[1]}_dwell_time_{m[2]}"] = v
        elif k.endswith("_occlusion_alarm"): r[k + "_status"] = v
        else:
            DROPPED.add(k)
    return r


DROPPED: set = set()


def run_js(model, payloads):
    path = HERE / f"_in_{model}.json"
    path.write_text(json.dumps([p.hex() for p in payloads]))
    res = subprocess.run(["node", str(REPO / "tools" / "run_official_decoder.js"),
                          str(SD / model / f"{model}-decoder.js"), str(path)], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool): return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)): return abs(a - b) < 1e-3
    return a == b


def main(n=400):
    total_bad = 0
    for model, gens in GEN.items():
        payloads = []
        sample = json.loads((SD / model / f"{model}-codec.json").read_text()).get("bytes")
        if sample: payloads.append(bytes.fromhex(sample))
        for _ in range(n):
            payloads.append(b"".join(random.choice(gens)() for _ in range(R(1, 6))))
        js_out = run_js(model, payloads)
        bad = errs = cmp_keys = 0
        for p, js in zip(payloads, js_out):
            if "__error" in js: errs += 1; continue
            exp = normalise(model, js)
            got = FUNC[model](p)
            for k, v in exp.items():
                cmp_keys += 1
                if k not in got or not same(got[k], v):
                    bad += 1
                    if bad <= 8: print(f"  {model} {p.hex()} key {k}: js={v!r} py={got.get(k, '<missing>')!r}")
            for k in got:
                if k not in exp and not k.endswith(EXTRA_OK):
                    bad += 1
                    if bad <= 8: print(f"  {model} {p.hex()} extra py key {k}={got[k]!r}")
        total_bad += bad
        print(f"{model}: {len(payloads)} payloads ({errs} JS errors skipped), {cmp_keys} values compared, {bad} mismatches")
    print("dropped JS keys (no counterpart):", sorted(DROPPED))
    print("TOTAL mismatches:", total_bad)
    return total_bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
