"""Self-check for group g1 stored-history support (g1.py / g1.json) against the official Milesight JS codecs.

    python3 g1_check.py [N]      (N random payloads per folder, default 300)

A) every command in g1.json (fetch / fetch_since with random times, enable / retransmit / stop / clear) is
   compared with the official encoder output (node). Specs with "verify_with" are checked against that sibling
   encoder (the folder's own encoder has a documented bug).
B) random payloads with 1-5 history records (+ random live channels before / between / after them) are decoded by
   our history_<family>() and by the official decoder; the JS history records are normalised to our keys and
   compared record by record (timestamps, keys, values within 1e-6).
"""
import importlib.util, json, pathlib, random, struct, subprocess, sys, tempfile, types

REPO = __import__("pathlib").Path(__file__).resolve().parents[2]
PKG = REPO / "custom_components" / "milesight_lorawan"
SD = pathlib.Path(__import__("os").environ.get("SENSOR_DECODERS", "SensorDecoders"))
HERE = pathlib.Path(__file__).resolve().parent
pkg = types.ModuleType("mlw"); pkg.__path__ = [str(PKG)]; sys.modules["mlw"] = pkg
spec = importlib.util.spec_from_file_location("mlw.decoders", PKG / "decoders.py")
dec = importlib.util.module_from_spec(spec); sys.modules["mlw.decoders"] = dec; spec.loader.exec_module(dec)
SPEC = json.load(open(HERE / "hist_g1.json"))
N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
R = random.Random(11)
FMT = {"u8": "<B", "u16le": "<H", "u16be": ">H", "u32le": "<I", "i16le": "<h", "i32le": "<i"}


def node(kind, folder, items):
    m = folder.split("/")[1]
    js = SD / folder / f"{m}-{kind}.js"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
        json.dump(items, t)
    out = subprocess.run(["node", str(REPO / "tools" / f"run_official_{kind}.js"), str(js), t.name],
                         capture_output=True, text=True, check=True).stdout
    pathlib.Path(t.name).unlink()
    return json.loads(out)


def subst(p, vals):
    if isinstance(p, dict): return {k: subst(v, vals) for k, v in p.items()}
    return vals.get(p, p) if isinstance(p, str) else p


# ---------------------------------------------------------------- A) encoder commands
def check_encoder():
    total = bad = 0
    for folder, d in SPEC.items():
        cases = {}   # encoder folder -> [(label, payload, expected)]
        for name in ("fetch", "fetch_since"):
            s = d.get(name)
            if not s: continue
            for _ in range(6):
                start = R.randint(1_500_000_000, 1_900_000_000); end = start + R.randint(60, 30 * 86400)
                vals = {"$start": start, "$end": end}
                exp = s["prefix"] + "".join(struct.pack(FMT[f["value"]], vals["$" + f["name"]]).hex() for f in s["fields"])
                cases.setdefault(s.get("verify_with", folder), []).append((f"{name}({start},{end})", subst(s["payload"], vals), exp))
        for name in ("enable", "retransmit", "stop", "clear"):
            s = d.get(name)
            if not s: continue
            for label, x in ([("", s)] if "hex" in s else [(k, s[k]) for k in ("on", "off")]):
                cases.setdefault(folder, []).append((f"{name}.{label}", x["payload"], x["hex"]))
        for enc, cs in cases.items():
            got = node("encoder", enc, [c[1] for c in cs])
            for (label, p, exp), g in zip(cs, got):
                total += 1
                if g != exp:
                    bad += 1; print(f"ENC MISMATCH {folder} [{enc}] {label}: spec {exp} node {g}")
    print(f"A) encoder: {total} commands, {bad} mismatches")
    return bad


# ---------------------------------------------------------------- B) history records
def u8(lo=0, hi=255): return bytes([R.randint(lo, hi)])
def u16(lo=0, hi=0xFFFF): return struct.pack("<H", R.randint(lo, hi))
def i16(lo, hi): return struct.pack("<h", R.randint(lo, hi))
def u32(lo=0, hi=0xFFFFFFFF): return struct.pack("<I", R.randint(lo, hi))
def i32(lo, hi): return struct.pack("<i", R.randint(lo, hi))
def ts(): return u32(1_500_000_000, 1_900_000_000)
def pick(*opts): return R.choice(opts)
def ch(cid, ctype, gen): return lambda: bytes([cid, ctype]) + gen()
def rec(cid, gen, ctype=0xCE): return lambda: (cid, bytes([cid, ctype]) + ts() + gen())

TEMP = lambda: i16(-400, 1000)
SENT16 = lambda lo, hi: struct.pack("<H", R.choice([R.randint(lo, hi)] * 4 + [0xFFFF, 0xFFFD]))
BAT = ch(0x01, 0x75, lambda: u8(0, 100))
T = ch(0x03, 0x67, TEMP)
H = ch(0x04, 0x68, lambda: u8(0, 200))
FLOAT = lambda: struct.pack("<f", R.uniform(0, 100000))

def ts_v2_val():
    return i16(-400, 1000) if R.random() < 0.6 else struct.pack("<h", R.choice([-999, -1000, -1001, -1002]))

# folder -> (history records generators, live channel generators)
GEN = {
 "em-series/em500-co2": ([rec(0x20, lambda: u16(400, 5000) + u16(9000, 11000) + TEMP() + u8(0, 200))],
                         [BAT, T, H, ch(0x05, 0x7D, lambda: u16(400, 5000)), ch(0x06, 0x73, lambda: u16(9000, 11000))]),
 "em-series/em500-lgt": ([rec(0x20, lambda: u32(0, 100000))], [BAT, ch(0x03, 0x94, lambda: u32(0, 100000))]),
 "em-series/em500-pp": ([rec(0x20, lambda: i16(-100, 2000))], [BAT, ch(0x03, 0x7B, lambda: i16(-100, 2000))]),
 "em-series/em500-pt100": ([rec(0x20, TEMP)], [BAT, T]),
 "em-series/em500-smtc": ([rec(0x20, lambda: SENT16(0, 20000) + pick(TEMP(), b"\xff\xff", b"\xfd\xff") + SENT16(0, 10000))],
                          [BAT, T, ch(0x05, 0x7F, lambda: u16(0, 20000))]),
 "em-series/em500-swl": ([rec(0x20, lambda: SENT16(0, 5000))], [BAT, ch(0x03, 0x77, lambda: u16(0, 5000))]),
 "em-series/em500-udl": ([rec(0x20, lambda: u16(0, 10000))], [BAT, ch(0x03, 0x82, lambda: u16(0, 10000))]),
 "ts-series/ts101": ([rec(0x20, TEMP)], [BAT, T]),
 "ts-series/ts201-v2": ([rec(0x20, lambda: u8(1, 2) + TEMP() + u8(0, 200) + bytes([R.choice([1, 2, 3, 6]) | (R.choice([0, 0, 0, 1, 2]) << 4) | (R.choice([0, 0, 0, 1, 2]) << 6)]))],
                        [BAT, T, H]),
 "ts-series/ts301-v2": ([rec(0x20, lambda: u8() + ts_v2_val() + ts_v2_val())], [BAT, T]),
 "ts-series/ts302-v2": ([rec(0x20, lambda: u8() + ts_v2_val() + ts_v2_val()), rec(0x21, lambda: u8() + ts_v2_val() + ts_v2_val())],
                        [BAT, T, ch(0x04, 0x67, TEMP)]),
 "ts-series/ts301": ([rec(0x20, lambda: bytes([R.randint(0, 7) << 4]) + pick(TEMP(), struct.pack("<H", R.randint(0, 2))) + b"\x00\x00")], [BAT, T]),
 "ts-series/ts302": ([rec(0x20, lambda: bytes([(R.randint(0, 7) << 4) | R.randint(0, 7)]) + pick(TEMP(), struct.pack("<H", R.randint(0, 2)))
                         + pick(TEMP(), struct.pack("<H", R.randint(0, 2))))], [BAT, T, ch(0x04, 0x67, TEMP)]),
 "am-series/am102": ([rec(0x20, lambda: TEMP() + u8(0, 200))], [BAT, T, H]),
 "em-series/em320-th": ([rec(0x20, lambda: TEMP() + u8(0, 200))], [BAT, T, H]),
 "am-series/am103": ([rec(0x20, lambda: TEMP() + u8(0, 200) + u16(400, 5000))], [BAT, T, H, ch(0x07, 0x7D, lambda: u16(400, 5000))]),
 "em-series/em300-th": ([rec(0x20, lambda: TEMP() + u8(0, 200) + u8())], [BAT, T, H]),
 "em-series/em300-mcs": ([rec(0x20, lambda: TEMP() + u8(0, 200) + u8(0, 2))], [BAT, T, H, ch(0x06, 0x00, lambda: u8(0, 1))]),
 "em-series/em300-sld": ([rec(0x20, lambda: TEMP() + u8(0, 200) + u8(0, 2))], [BAT, T, H, ch(0x05, 0x00, lambda: u8(0, 1))]),
 "em-series/em300-zld": ([rec(0x20, lambda: TEMP() + u8(0, 200) + u8(0, 2))], [BAT, T, H, ch(0x05, 0x00, lambda: u8(0, 1))]),
 "em-series/em300-mld": ([rec(0x20, lambda: u8() + u8() + u8() + u8(0, 2))], [BAT, ch(0x05, 0x00, lambda: u8(0, 1))]),
 "em-series/em300-di": ([rec(0x20, lambda: TEMP() + u8(0, 200) + u8(1, 3) + u8(0, 2) + u32()),
                         rec(0x21, lambda: TEMP() + u8(0, 200) + u8(0, 10) + u8(1, 3) + u8(0, 2) + u16(0, 1000) + u16(0, 1000) + FLOAT())],
                        [BAT, T, H, ch(0x05, 0x00, lambda: u8(0, 1)), ch(0x05, 0xC8, lambda: u32())]),
 "em-series/em300-di-hall": ([rec(0x21, lambda: u8() + u8() + u8() + u8(0, 10) + u8(1, 3) + u8(0, 2) + u16(0, 1000) + u16(0, 1000) + FLOAT())],
                             [BAT, ch(0x05, 0x00, lambda: u8(0, 1)), ch(0x05, 0xC8, lambda: u32())]),
 "em-series/em320-th-v2": ([rec(0x20, lambda: pick(TEMP(), b"\x01\x80", b"\x02\x80") + pick(u16(0, 1000), u16(0, 1000), b"\xff\xff") + u8(1, 9))],
                           [BAT, T, ch(0x04, 0x9A, lambda: u16(0, 1000))]),
 "em-series/em410-rdl": ([rec(0x20, lambda: pick(i16(0, 20000), i16(0, 20000), b"\xfd\xff", b"\xfe\xff", b"\xff\xff")
                              + pick(TEMP(), TEMP(), b"\xfe\xff", b"\xff\xff") + i16(-500, 500) + u8(0, 63))],
                         [BAT, T, ch(0x04, 0x82, lambda: u16(0, 20000))]),
 "at-series/at101": ([rec(0x20, lambda: i32(-180_000_000, 180_000_000) + i32(-90_000_000, 90_000_000))], [BAT, T]),
}
GEN["em-series/em411-rdl"] = GEN["em-series/em410-rdl"]
AM3 = lambda extra: (lambda: TEMP() + u16(0, 200) + u8(0, 1) + u8(0, 5) + u16(400, 5000) + u16(0, 500) + u16(9000, 11000) + extra())
AM3_LIVE = [T, H, ch(0x05, 0x00, lambda: u8(0, 1)), ch(0x06, 0xCB, lambda: u8(0, 5)), ch(0x07, 0x7D, lambda: u16(400, 5000)),
            ch(0x09, 0x73, lambda: u16(9000, 11000))]
for f, extra, ids in (("am-series/am307", lambda: b"", (0x20, 0x21)),
                      ("am-series/am308", lambda: u16(0, 999) + u16(0, 999), (0x20, 0x21)),
                      ("am-series/am319-hcho", lambda: u16(0, 999) + u16(0, 999) + u16(0, 500), (0x20, 0x21)),
                      ("am-series/am319-o3", lambda: u16(0, 999) + u16(0, 999) + u16(0, 500), (0x20, 0x21)),
                      ("am-series/am319-hcho-well", lambda: u16(0, 999) + u16(0, 5000), (0x22, 0x23))):
    GEN[f] = ([rec(ids[0], AM3(extra)), rec(ids[1], AM3(extra))], AM3_LIVE + ([BAT] if f in ("am-series/am307", "am-series/am308") else []))
def am30xl(co2):
    def g():
        typ = lambda: u8(0, 3) if R.random() < 0.3 else b"\x01"
        s = typ() + TEMP() + typ() + u8(0, 200) + bytes([(R.randint(0, 1) << 6) | R.randint(0, 1)]) + u16(0, 999) + typ() + u16(0, 2000)
        return s + (typ() + u16(400, 5000) if co2 else b"")
    return g
GEN["am-series/am304l"] = ([rec(0x20, am30xl(False)), rec(0x21, am30xl(False))], [BAT, T, H])
GEN["am-series/am305l"] = ([rec(0x20, am30xl(True)), rec(0x21, am30xl(True))], [BAT, T, H, ch(0x07, 0x7D, lambda: u16(400, 5000))])

# command-format devices: record = 0xED <mode> <ts> + commands
TS60_CMDS = [lambda: b"\x01" + u8(0, 100), lambda: b"\x04" + i32(-4000, 8000), lambda: b"\x05" + u16(0, 1000),
             lambda: b"\x06" + i32(-90_000_000, 90_000_000) + i32(-180_000_000, 180_000_000), lambda: b"\x0c" + u8(0, 1),
             lambda: b"\x0d" + i16(-9000, 9000) + i16(-9000, 9000) + i16(-9000, 9000)]
def cth_masked():
    cmd = R.randint(0x08, 0x17); mask = R.randint(0, 3); out = bytes([cmd, mask])
    for g in range(2):
        out += b"".join(struct.pack("<i" if cmd <= 0x0D else "<I", R.randint(0, 10**6)) for _ in range(3 if mask >> g & 1 else 1))
    return out
def cth_pf():
    mask = R.randint(0, 15)
    return bytes([0x07, mask]) + b"".join(bytes(R.randint(0, 100) for _ in range(3 if mask >> g & 1 else 1)) for g in range(4))
CTH_CMDS = [lambda: b"\x01" + i16(-4000, 8000), lambda: b"\x02" + u16(0, 5000),
            lambda: b"\x03" + b"".join(u16(0, 5000) for _ in range(12)), lambda: b"\x04" + b"".join(u16(0, 5000) for _ in range(3)),
            lambda: b"\x05" + b"".join(struct.pack("<I", R.randint(0, 10**6))[:3] for _ in range(12)),
            lambda: b"\x06" + b"".join(u16(20000, 25000) for _ in range(3)), cth_masked, cth_pf]
def cmd_rec(cmds, mode):
    def g():
        body = b"".join(c() for c in R.sample(cmds, R.randint(1, 4)))   # one command of each kind per record
        return (0xED, bytes([0xED, mode()]) + ts() + body)
    return g
GEN["ts-series/ts601"] = ([cmd_rec(TS60_CMDS, lambda: R.randint(0, 1))], TS60_CMDS)
GEN["ts-series/ts602"] = GEN["ts-series/ts601"]
GEN["cth-series/cth01"] = ([cmd_rec(CTH_CMDS, lambda: R.randint(0, 3))], CTH_CMDS)
CMD_FORMAT = ("ts-series/ts601", "ts-series/ts602", "cth-series/cth01")


def make_payload(folder):
    recs, live = GEN[folder]
    parts, cids = [], []
    if folder in CMD_FORMAT:        # live commands only before the first record (afterwards they belong to a record)
        if R.random() < 0.5:
            parts += [R.choice(live)() for _ in range(R.randint(1, 2))]
        for _ in range(R.randint(1, 5)):
            cid, raw = R.choice(recs)(); parts.append(raw); cids.append(cid)
        return b"".join(parts), cids
    if folder in ("am-series/am304l", "am-series/am305l"):
        recs = [R.choice(recs)]     # the official decoder keeps only the last record per channel
    for _ in range(R.randint(1, 5)):
        if R.random() < 0.4:
            parts.append(R.choice(live)())
        cid, raw = R.choice(recs)(); parts.append(raw); cids.append(cid)
    if R.random() < 0.4:
        parts.append(R.choice(live)())
    return b"".join(parts), cids


# ---- normalisation of the JS history records to our keys
MAG = {"close": 0, "open": 1}
def norm_record(folder, r, cid):
    m = folder.split("/")[1]
    out = {}
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    def put(k, v):
        if num(v): out[k] = v
    if m.startswith("em500") or m == "ts101":
        ren = {"pressure": "pressure_kpa"} if m == "em500-pp" else {}
        for k, v in r.items():
            if k != "timestamp": put(ren.get(k, k), v)
    elif m == "ts201-v2":
        ev = r.get("event", {})
        if ev.get("temperature_sensor_status") == "normal": put("temperature", r.get("temperature"))
        if "humidity" in r and ev.get("humidity_sensor_status") == "normal": put("humidity", r["humidity"])
    elif m in ("ts301-v2", "ts301", "ts302-v2", "ts302"):
        for k, v in r.items():
            k2 = k.replace("_chn1", "_1").replace("_chn2", "_2")
            if k2.startswith("magnet"):
                k2 = k2.replace("magnet", "magnet_status")
                if v in MAG: out[k2] = MAG[v]
            elif k2.startswith(("temperature", "humidity")) and not k2.endswith(("_event", "_alarm")):
                put(k2, v)
    elif m in ("am102", "em320-th", "am103", "em300-th", "at101"):
        for k, v in r.items():
            if k != "timestamp": put(k, v)
    elif m == "em320-th-v2":
        if r["temperature"] > -3276.5: out["temperature"] = r["temperature"]
        put("humidity", r["humidity"])
    elif m in ("em300-mcs",):
        out.update(temperature=r["temperature"], humidity=r["humidity"])
        if r["magnet_status"] in MAG: out["magnet_status"] = MAG[r["magnet_status"]]
    elif m in ("em300-sld", "em300-zld", "em300-mld"):
        if m != "em300-mld": out.update(temperature=r["temperature"], humidity=r["humidity"])
        lv = {"normal": 0, "leak": 1}.get(r["leakage_status"])
        if lv is not None: out["input_05" if m != "em300-mld" else "leak"] = lv
    elif m in ("em300-di", "em300-di-hall"):
        for k in ("temperature", "humidity", "water_conv", "pulse_conv", "water"): put(k, r.get(k))
        if "pulse" in r: out["pulse_count"] = r["pulse"]
        if r.get("gpio") in ("low", "high"): out["input_05"] = 1 if r["gpio"] == "high" else 0
    elif m in ("em410-rdl", "em411-rdl"):
        for k in ("distance", "temperature", "distance_mutation"): put(k, r.get(k))
    elif m.startswith(("am307", "am308", "am319")):
        for k, v in r.items():
            if k == "timestamp": continue
            if k == "pir":
                if v in ("idle", "trigger"): out["pir"] = 1 if v == "trigger" else 0
            elif k == "tvoc": out["tvoc_iaq" if cid in (0x20, 0x22) else "tvoc"] = v
            else: put(k, v)
    elif m in ("am304l", "am305l"):
        if r.get("temperature_type") == 1: out["temperature"] = r["temperature"]
        if r.get("humidity_type") == 1: out["humidity"] = r["humidity"]
        if r.get("pir_type") == 1:
            out["pir"] = r["pir_status"] == 1; out["occupancy"] = 1 if r["pir_status"] == 1 else 0; out["pir_count"] = r["pir_count"]
        if r.get("als_level_type") == 1: out["light_level"] = r["als_level"]
        if r.get("Lux_type") == 1: out["illuminance_lux"] = r["Lux"]
        if r.get("co2_type") == 1: out["co2"] = r["co2"]
    elif m in ("ts601", "ts602"):
        for k in ("battery", "temperature", "humidity"):
            if k in r: out[k] = r[k]
        if "base_station_position" in r:
            out["latitude"] = r["base_station_position"]["latitude"]; out["longitude"] = r["base_station_position"]["longitude"]
        if "probe_connect_status" in r: out["probe_connected"] = r["probe_connect_status"] == 1
        if "relative_surface_info" in r:
            for a in "xyz": out[f"angle_{a}"] = r["relative_surface_info"][f"angle_{a}"]
    elif m == "cth01":
        AB = "abcd"
        def cput(key, v):
            if v != "error": out[key] = v
        for k, v in r.items():
            if k == "temperature": out[k] = v
            elif k == "voltage_three_phase_imbalcance": cput("voltage_unbalance", v)
            elif k in ("thdi", "thdv", "current", "voltage"):
                pre = {"thdi": "thdi_ct", "thdv": "thdv_l", "current": "current_ct", "voltage": "voltage_l"}[k]
                for n, item in enumerate(v): cput(f"{pre}{n + 1}", item["value"])
            elif k == "power_factor":
                for g in range(1, 5):
                    if f"group{g}_value" in v and not v.get(f"mask{g}"): cput(f"power_factor_{AB[g - 1]}", v[f"group{g}_value"])
                    if f"group{g}" in v and v.get(f"mask{g}"):
                        for c in range(1, 4): cput(f"power_factor_ct{3 * (g - 1) + c}", v[f"group{g}"][f"chan{c}"])
            elif k[:-1].endswith(("power", "energy")) and k[-1] in "12":
                measure, half = k[:-1], int(k[-1])
                for g in (1, 2):
                    circuit = (half - 1) * 2 + (g - 1)
                    if v.get(f"mask{g}") == 0 and f"group{g}_value" in v: cput(f"{measure}_{AB[circuit]}", v[f"group{g}_value"])
                    if v.get(f"mask{g}") == 1 and f"group{g}" in v:
                        for c in range(1, 4): cput(f"{measure}_ct{circuit * 3 + c}", v[f"group{g}"][f"chan{c}"])
    else:
        raise KeyError(folder)
    return out

# keys we may add that the official record has no counterpart for
EXTRA_OK = {"cth-series/cth01": {"power_loss_alarm"}}


def js_records(folder, js, cids, single):
    m = folder.split("/")[1]
    if m in ("am304l", "am305l"):
        return [(o["historical_data_retrieval" if c == 0x20 else "historical_data_retrieval_Lux"]["timestamp"],
                 norm_record(folder, o["historical_data_retrieval" if c == 0x20 else "historical_data_retrieval_Lux"], c))
                for o, c in zip(single, cids)]
    hist = js.get("history", [])
    if folder not in CMD_FORMAT and len(hist) != len(cids):
        return None
    return [(r["timestamp"], norm_record(folder, r, c)) for r, c in zip(hist, cids or [None] * len(hist))]


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool): return a == b
    return abs(a - b) <= 1e-6


def check_history():
    total_p = total_r = bad = 0
    for folder, d in SPEC.items():
        if not d["history_fn"]: continue
        fn = getattr(dec, d["history_fn"])
        payloads = [make_payload(folder) for _ in range(N)]
        js = node("decoder", folder, [p.hex() for p, _ in payloads])
        single = [None] * len(payloads)
        if folder in ("am-series/am304l", "am-series/am305l"):   # decode every record on its own as well
            recs = []
            for p, cids in payloads:
                b, j, lst = p, 0, []
                while j + 2 <= len(b):
                    size = 15 if folder.endswith("am304l") else 18
                    if b[j + 1] == 0xCE and b[j] in (0x20, 0x21): lst.append(b[j:j + 2 + size].hex()); j += 2 + size
                    else: j += 2 + {0x75: 1, 0x67: 2, 0x68: 1, 0x7D: 2}[b[j + 1]]
                recs.append(lst)
            flat = node("decoder", folder, [h for lst in recs for h in lst]); k = 0
            for n, lst in enumerate(recs):
                single[n] = flat[k:k + len(lst)]; k += len(lst)
        fbad = 0
        for n, ((p, cids), o) in enumerate(zip(payloads, js)):
            total_p += 1
            if "__error" in o:
                fbad += 1; print(f"{folder}: JS error {o} for {p.hex()}"); continue
            if folder in ("am-series/am304l", "am-series/am305l"):
                last = o["historical_data_retrieval" if cids[-1] == 0x20 else "historical_data_retrieval_Lux"]
                if last != single[n][-1]["historical_data_retrieval" if cids[-1] == 0x20 else "historical_data_retrieval_Lux"]:
                    fbad += 1; print(f"{folder}: last record differs in full payload {p.hex()}"); continue
            exp = js_records(folder, o, cids, single[n])
            mine = fn(p)
            if exp is None:
                fbad += 1; print(f"{folder}: JS record count differs for {p.hex()}"); continue
            exp = [(t, v) for t, v in exp if v]
            total_r += len(exp)
            ok = len(exp) == len(mine)
            for (t1, v1), (t2, v2) in zip(exp, mine) if ok else []:
                extra = set(v2) - set(v1) - EXTRA_OK.get(folder, set())
                if t1 != t2 or extra or any(k not in v2 or not same(v1[k], v2[k]) for k in v1):
                    ok = False
            if not ok:
                fbad += 1
                if fbad <= 5: print(f"MISMATCH {folder} {p.hex()}\n  js:   {exp}\n  ours: {mine}")
        bad += fbad
        print(f"{folder}: {N} payloads ({d['history_fn']}) {'ok' if not fbad else f'{fbad} MISMATCHES'}")
    print(f"B) history: {total_p} payloads, {total_r} records, {bad} mismatches")
    return bad


if __name__ == "__main__":
    a = check_encoder()
    b = check_history()
    print("TOTAL mismatches:", a + b)
    raise SystemExit(1 if a + b else 0)
