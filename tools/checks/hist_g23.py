"""Self-check for hist/g23.py: our history_<family>() records vs the official JS decoders' history arrays.

python3 g23_check.py      (needs node; reads /tmp/claude-0/sd and the repo's decoders.py, writes nothing there)
"""
import importlib.util, json, pathlib, random, re, struct, subprocess, sys, types

REPO = __import__("pathlib").Path(__file__).resolve().parents[2]
PKG = REPO / "custom_components" / "milesight_lorawan"
SD = pathlib.Path(__import__("os").environ.get("SENSOR_DECODERS", "SensorDecoders"))
HERE = pathlib.Path(__file__).resolve().parent
TMP = pathlib.Path(__import__("tempfile").mkdtemp(prefix="mlw_hist_"))
TMP.mkdir(exist_ok=True)

pkg = types.ModuleType("mlw"); pkg.__path__ = [str(PKG)]; sys.modules["mlw"] = pkg
spec = importlib.util.spec_from_file_location("mlw.decoders", PKG / "decoders.py")
dec = importlib.util.module_from_spec(spec); sys.modules["mlw.decoders"] = dec; spec.loader.exec_module(dec)

random.seed(23)
R = random.randint
N_PAYLOADS = 320


def u8(v): return bytes([v & 0xFF])
def u16(v): return struct.pack("<H", v & 0xFFFF)
def i16(v): return struct.pack("<h", v)
def u32(v): return struct.pack("<I", v & 0xFFFFFFFF)
def i32(v): return struct.pack("<i", v)
def ts(): return u32(R(1_600_000_000, 1_900_000_000))
def f16(): return u16(R(0, 0x7BFF) | (R(0, 1) << 15))
def f32(): return struct.pack("<f", random.uniform(-1e5, 1e5))
def f64(): return struct.pack("<d", random.uniform(-1e9, 1e9))
def hdr(c, t): return bytes([c, t])


# ---------------------------------------------------------------- record generators (header included)
def vs121_rec():
    t = random.choice([1, 2, 3] + list(range(4, 0x13)))
    if t == 1: body = u8(R(0, 30)) + u8(n := R(0, 16)) + R(0, 0xFFFF).to_bytes(2, "big")
    elif t == 3: body = u8(R(0, 50))
    elif t == 0x11: body = u8(R(1, 4)) + u16(R(0, 9999)) + u16(R(0, 9999))
    elif 4 <= t <= 7: body = bytes(R(0, 50) for _ in range(4))
    else: body = u16(R(0, 65535)) + u16(R(0, 65535))
    return hdr(0x20, 0xCE) + ts() + u8(t) + body


def vs321_rec():
    if R(0, 1): return hdr(0x20, 0xCE) + ts() + u8(0) + u16(R(0, 999))
    return hdr(0x20, 0xCE) + ts() + u8(1) + u16(R(0, 0x3FF)) + u16(R(0, 0x3FF))


def vs133_rec():
    t = random.choice(list(range(0x03, 0x10)) + list(range(0x11, 0x1E)) + [0x10, 0x20, 0x1E, 0x3C])
    if t in (0x10, 0x20, 0x1E, 0x3C): body = u8(R(1, 4)) + u16(R(0, 65535))
    elif t in (0x0F, 0x1D): body = bytes(R(0, 99) for _ in range(4))
    elif ((t - 0x0E if t >= 0x11 else t) - 3) % 3 == 2: body = u16(R(0, 65535)) + u16(R(0, 65535))
    else: body = u32(R(0, 2**32 - 1))
    return hdr(0x20, 0xCE) + ts() + u8(t) + body


def vs35x_rec():
    t = R(0, 1)
    return hdr(0x20, 0xCE) + ts() + u8(t) + b"".join(u16(R(0, 65535)) for _ in range(2 + 2 * t))


def vs373_rec():
    return hdr(0x20, 0xCE) + ts() + u16(R(0, 65535)) + u8(R(0, 9)) + u8(R(0, 5)) + u8(R(0, 6))


def uc300_io():
    mask = R(0, 0x1FFF) & ~(1 << 12 if R(0, 3) else 0)          # custom-text bit only sometimes
    if mask & (1 << 12): mask &= 0x1FFF
    body = b""
    for k in range(13):
        if not mask >> k & 1: continue
        if k < 4: body += u8(R(0, 1)) + (u32(R(0, 1)) if R(0, 1) else u32(R(0, 2**32 - 1)))
        elif k < 6: body += u8(R(0, 1))
        elif k < 8: body += f16()
        elif k < 12: body += f16() + f16() + f16() + f16()
        else: body += bytes(R(0x20, 0x7E) for _ in range(48))
    if R(0, 4) == 0: mask |= R(0, 7) << 13                       # unused bits 13-15 (no data)
    return hdr(0x20, 0xDC) + ts() + u16(mask) + body


def uc300_modbus():
    mask = R(1, 2**32 - 1) & random.choice([0xFF, 0xFFFF, 0xFFFFFFFF, 0x0F0F])
    body = b""
    for k in range(32):
        if not mask >> k & 1: continue
        t = random.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])  # no coil (0): official puts it outside the record
        sign = R(0, 1)
        val = f32() if t in (5, 7) else bytes(R(0, 255) for _ in range(4))
        body += u8(t | sign << 7) + val
    return hdr(0x20, 0xDD) + ts() + u32(mask) + body


def uc50x_io():
    def gp():
        t = R(0, 3)
        return u8(t) + (u32(R(0, 1)) if t < 2 and R(0, 3) else u32(R(0, 2**32 - 1)))
    return hdr(0x20, 0xDC) + ts() + gp() + gp() + i32(R(-2**31, 2**31 - 1)) + i32(R(-30000, 30000))


def uc50x_sdi():
    mask = R(0, 0xFFFF) & random.choice([0x1, 0x3, 0x5])
    return hdr(0x20, 0xE0) + ts() + u16(mask) + b"".join(
        bytes(R(0x30, 0x39) for _ in range(20)) + bytes(16) for _ in range(bin(mask).count("1")))


def uc50x_modbus():
    mask = R(1, 0xFFFF)
    body = b""
    for k in range(16):
        if mask >> k & 1:
            t = R(0, 255)
            body += u8(t) + (f32() if t & 7 in (5, 7) else u32(R(0, 2**32 - 1)))
    return hdr(0x20, 0xDD) + ts() + u16(mask) + body


def uc51x_valve(): return hdr(0x20, 0xCE) + ts() + u8(R(0, 255)) + u32(R(0, 2**32 - 1))
def uc51x_pressure(): return hdr(0x21, 0xCE) + ts() + u16(R(0, 65535))


def uc100_rec():
    t = R(0, 25)                     # 26+ undefined: the official decoder then skips only 6 bytes (we skip 10)
    d = (R(0, 1) << 7) | (t << 2) | (0 if R(0, 6) == 0 else 2)
    val = f32() if 10 <= t <= 13 or 22 <= t <= 25 else bytes(R(0, 255) for _ in range(4))
    return hdr(0x20, 0xCE) + ts() + u8(R(0, 15)) + u8(d) + val


def uc100_msg():
    m = bytes(R(0x20, 0x7E) for _ in range(R(0, 20)))
    return hdr(0x20, 0xCD) + ts() + u8(len(m)) + m


def uc100v2_rec():
    t = R(0, 44)
    sign, ok, regs = R(0, 1), int(R(0, 6) > 0), R(1, 2)
    d = sign << 15 | t << 9 | ok << 8 | regs << 6 | R(0, 3) << 4

    def val():
        if 10 <= t <= 13 or 22 <= t <= 25: return f32() + bytes(4)
        if 26 <= t <= 29 or 34 <= t <= 37:     # official readDoubleLE is wrong when bit 31 of the low word is set
            d = bytearray(f64()); d[3] &= 0x7F; return bytes(d)
        if 30 <= t <= 33 or 38 <= t <= 41:
            v = R(-2**52, 2**52) if sign else R(0, 2**53 - 1)
            return v.to_bytes(8, "little", signed=True)
        return bytes(R(0, 255) for _ in range(8))
    return hdr(0x21, 0xCE) + ts() + u8(R(0, 31)) + u16(d) + val() + val()


def uc100v2_msg():
    m = bytes(R(0x20, 0x7E) for _ in range(R(0, 20)))
    return hdr(0x21, 0xCD) + ts() + u8(len(m)) + m


def ws203_rec():
    return hdr(0x20, 0xCE) + ts() + u8(R(0, 7)) + u8(random.choice([0, 1, 0, 1, 2])) + i16(R(-400, 850)) + u8(R(0, 200))


def wt201_rec():
    return hdr(0x20, 0xCE) + ts() + u16(R(0, 65535)) + u16(R(0, 65535))


def wt201v2_rec():
    m = R(0, 0x7FF) & ~(0x0F << 7) | (R(0, 9) << 7)
    t2 = u16(0xFFFF) if R(0, 2) == 0 else i16(R(50, 350))
    return hdr(0x20, 0xCE) + ts() + u16(m) + i16(R(50, 350)) + t2 + i16(R(-200, 600)) + u8(R(0, 200))


# ---------------------------------------------------------------- live channels mixed in
def live(*items): return [lambda it=it: it() if callable(it) else bytes(it) for it in items]


VS_INFO = live(lambda: b"\xff\x01\x01", lambda: b"\xff\x16" + bytes(R(0, 255) for _ in range(8)),
               lambda: b"\xff\x09\x01\x10", lambda: b"\xff\x0f\x00")
LIVE = {
    "vs121": live(lambda: b"\x04\xc9" + u8(R(0, 9)) + b"\x04" + bytes(2), lambda: b"\x05\xcc" + i16(R(0, 50)) + i16(R(0, 50)),
                  lambda: b"\x0f\x85" + ts(), lambda: b"\x0e\xe4\x01" + u16(R(0, 999)) + u16(R(0, 99))),
    "vs321": live(lambda: b"\x01\x75" + u8(R(0, 100)), lambda: b"\x03\x67" + i16(R(-100, 400)), lambda: b"\x05\xfd" + u16(R(0, 99)),
                  lambda: b"\x06\xfe" + u16(R(0, 1023)) + u16(R(0, 1023)), lambda: b"\x0a\xef" + ts(), lambda: b"\x84\x68" + u8(R(0, 200)) + u8(R(0, 2))),
    "vs133": live(lambda: b"\x03\xd2" + u32(R(0, 99999)), lambda: b"\x05\xcc" + u16(R(0, 99)) + u16(R(0, 99)),
                  lambda: b"\x0f\xe3" + bytes(4), lambda: b"\x10\xe4\x01" + u16(R(0, 999)) + u16(R(0, 999)),
                  lambda: b"\xff\x1f\x01\x00\x09\x00", lambda: b"\xff\x68\x01", lambda: b"\x50\xfc\x00\x00\x01"),
    "vs35x": live(lambda: b"\x01\x75" + u8(R(0, 100)), lambda: b"\x04\xcc" + u16(R(0, 99)) + u16(R(0, 99)),
                  lambda: b"\x85\xcc" + u16(R(0, 99)) + u16(R(0, 99)) + u8(R(0, 1)), lambda: b"\x0a\xef" + ts(), lambda: b"\xff\x68\x01"),
    "vs373": live(lambda: b"\x07\xb0" + bytes([R(0, 4), R(0, 3)]) + bytes(6), lambda: b"\x06\xfb" + u16(R(0, 999)) + bytes([R(0, 8), R(1, 4), R(0, 5)]),
                  lambda: b"\x08\xb1" + u8(R(1, 5)) + u16(R(0, 3000))),
    "uc300": live(lambda: b"\x03\x00" + u8(R(0, 1)), lambda: b"\x04\xc8" + u32(R(0, 99999)), lambda: b"\x09\x67" + i16(R(-100, 999)),
                  lambda: b"\x0b\xe2" + f16() + f16() + f16() + f16(), lambda: b"\xff\x19\x00\x02\x02" + u16(R(0, 65535)), lambda: b"\xff\x15\x03"),
    "uc50x": live(lambda: b"\x01\x75" + u8(R(0, 100)), lambda: b"\x03\x00" + u8(R(0, 1)), lambda: b"\x04\xc8" + u32(R(0, 9999)),
                  lambda: b"\x05\x02" + i16(R(0, 999)) * 4, lambda: b"\x85\xe2" + f16() * 4 + u8(1), lambda: b"\xff\x0e\x07\x02" + u16(R(0, 999)),
                  lambda: b"\x80\x0e\x08\x05" + f32() + u8(1), lambda: b"\xff\x15\x08"),
    "uc51x": live(lambda: b"\x01\x75" + u8(R(0, 100)), lambda: b"\x03\x01" + u8(R(0, 1)), lambda: b"\x04\xc8" + u32(R(0, 9999)),
                  lambda: b"\x09\x7b" + u16(R(0, 999)), lambda: b"\x0e\xaf" + bytes(3)),
    "uc100": live(lambda: b"\xff\x19\x00\x02\x03" + u16(R(0, 999)), lambda: b"\xff\x15\x02", lambda: b"\xf9\x5f" + bytes(7)),
    "uc100v2": live(lambda: b"\xf9\x73\x00\x02" + u16(R(0, 999)), lambda: b"\xff\x15\x01", lambda: b"\xfc\x01\x00"),
    "ws203": live(lambda: b"\x01\x75" + u8(R(0, 100)), lambda: b"\x03\x67" + i16(R(-100, 400)), lambda: b"\x04\x68" + u8(R(0, 200)),
                  lambda: b"\x05\x00" + u8(R(0, 1)), lambda: b"\x83\x67" + i16(R(-100, 400)) + u8(R(0, 1))),
    "wt201": live(lambda: b"\x03\x67" + i16(R(-100, 400)), lambda: b"\x05\xe7" + u8(R(0, 0x73)), lambda: b"\x08\x8e" + u8(R(0, 1)),
                  lambda: b"\x09\x68" + u8(R(0, 200)), lambda: b"\x0a\x6e" + u8(R(0, 127))),
    "wt201v2": live(lambda: b"\x03\x67" + i16(R(-100, 400)), lambda: b"\x0b\x67" + i16(R(100, 300)), lambda: b"\x07\xe9" + u8(R(1, 3)),
                    lambda: b"\x83\x67" + i16(R(-100, 400)) + u8(R(1, 10)), lambda: b"\x09\x68" + u8(R(0, 200))),
}
for k in ("vs121", "vs321", "vs35x", "vs373", "uc300", "uc50x", "uc51x", "uc100v2", "ws203", "wt201", "wt201v2"):
    LIVE[k] = LIVE[k] + VS_INFO[:1]


# ---------------------------------------------------------------- normalisation of official records
ONOFF = {"on": 1, "off": 0, "unknown": 0}


def norm_vs321(r):
    out = {}
    for k, v in r.items():
        if k == "people_total_counts": k = "people_count_all"
        elif re.fullmatch(r"region_\d+", k): v = {"occupied": 1, "vacant": 0}[v]
        out[k] = v
    return out


def norm_vs133(r):
    out = {}
    for k, v in r.items():
        m = re.fullmatch(r"region_(\d+)(_child)?_(avg|max)_dwell", k)
        if m: k = f"region_{m[1]}{m[2] or ''}_dwell_time_{m[3]}"
        k = re.sub(r"_period_(in|out)$", r"_\1", k)
        out[k] = v
        if k in ("line_1_total_in", "line_1_total_out", "line_1_in", "line_1_out"):
            out[k.replace("line_1_", "people_")] = v
    return out


def norm_vs35x(r):
    ren = {"period_in": "people_in", "period_out": "people_out", "total_in": "people_total_in", "total_out": "people_total_out"}
    return {ren.get(k, k): v for k, v in r.items()}


def norm_onoff(r, drop=()):
    return {k: (ONOFF[v] if isinstance(v, str) and v in ONOFF else v) for k, v in r.items()
            if not k.endswith(drop) and not k.startswith(("sdi12_", "custom_message", "text"))}


def norm_uc51x(r):
    out = {}
    for k, v in r.items():
        if k == "mode": continue
        out[k] = {"open": 1, "close": 0, "on": 1, "off": 0}.get(v, v) if isinstance(v, str) else v
    return out


def norm_ws203(r):
    out = {k: v for k, v in r.items() if k != "report_type"}
    occ = {"vacant": 0, "occupied": 1}.get(out.pop("occupancy", None))
    if occ is not None: out["occupancy"] = occ
    return out


def norm_wt201(r):
    out = {}
    for k, v in r.items():
        if k == "system_status": v = v == "on"
        elif k in ("temperature_control_mode", "temperature_control_status"): v = v.replace("_", " ")
        out[k] = v
    return out


def norm_wt102(r):
    ren = {"motor_total_stroke": "motor_stroke", "valve_opening_degree": "valve_opening",
           "target_valve_opening_degree": "target_valve_opening"}
    out = {}
    for k, v in r.items():
        if k == "low_battery_alarm": out["battery_low_alarm"] = True; continue
        out[ren.get(k, k)] = v
    return out


# ---------------------------------------------------------------- families
# family: (our function, folders, record generators, normaliser, JS keys holding records)
FAM = {
    "vs121": ("history_vs121", ["vs-series/vs121"], [vs121_rec], lambda r: r, ("history",)),
    "vs321": ("history_vs321", ["vs-series/vs321"], [vs321_rec], norm_vs321, ("history",)),
    "vs133": ("history_vs133", ["vs-series/vs133", "vs-series/vs135"], [vs133_rec], norm_vs133, ("history",)),
    "vs35x": ("history_vs35x", ["vs-series/vs350", "vs-series/vs351", "vs-series/vs360"], [vs35x_rec], norm_vs35x, ("history",)),
    "vs373": ("history_vs373", ["vs-series/vs373"], [vs373_rec], lambda r: r, ("history",)),
    "uc300": ("history_uc300", ["uc-series/uc300"], [uc300_io, uc300_modbus], norm_onoff, ("channel_history", "modbus_history")),
    "uc50x": ("history_uc50x", ["uc-series/uc501", "uc-series/uc502"], [uc50x_io, uc50x_io, uc50x_sdi, uc50x_modbus], norm_onoff, ("history",)),
    "uc51x": ("history_uc51x", ["uc-series/uc511", "uc-series/uc512"], [uc51x_valve, uc51x_pressure], norm_uc51x, ("history",)),
    "uc100": ("history_uc100", ["uc-series/uc100"], [uc100_rec, uc100_rec, uc100_msg], lambda r: norm_onoff(r, ("_alarm",)), ("history",)),
    "uc100v2": ("history_uc100_v2", ["uc-series/uc100-v2"], [uc100v2_rec, uc100v2_rec, uc100v2_msg], lambda r: norm_onoff(r, ("_alarm",)), ("history",)),
    "ws203": ("history_ws203", ["ws-series/ws203"], [ws203_rec], norm_ws203, ("history",)),
    "wt201": ("history_wt201", ["wt-series/wt201"], [wt201_rec], norm_wt201, ("history",)),
    "wt201v2": ("history_wt201_v2", ["wt-series/wt201-v2", "wt-series/wt211"], [wt201v2_rec], norm_wt201, ("history",)),
}


def build(gens, lives):
    parts = [random.choice(gens)() for _ in range(R(1, 5))]
    for _ in range(R(0, 2) if lives else 0):
        parts.insert(R(0, len(parts)), random.choice(lives)())
    return b"".join(parts)


# WT102: [live cmds] (ED type ts [cmds])+
def wt102_cmds():
    out = b""
    for _ in range(R(1, 4)):
        c = random.choice([0x00, 0x01, 0x02, 0x03, 0x04, 0x06, 0x07, 0x08])
        if c in (0x00, 0x04, 0x07, 0x08): out += u8(c) + u8(R(0, 100))
        elif c in (0x01, 0x06): out += u8(c) + i16(R(-1000, 4000))
        else: out += u8(c) + u16(R(0, 65535))
    return out


def wt102_payload():
    p = wt102_cmds() if R(0, 1) else b""
    for _ in range(R(1, 5)):
        p += b"\xed" + u8(R(0, 1)) + ts() + wt102_cmds()
    return p


def run_node(folder, hexes):
    model = folder.split("/")[1]
    inp = TMP / "check_in.json"
    inp.write_text(json.dumps(hexes))
    out = subprocess.check_output(["node", str(REPO / "tools" / "run_official_decoder.js"),
                                   str(SD / folder / f"{model}-decoder.js"), str(inp)])
    return json.loads(out)


def same(a, b, fam):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if fam == "uc50x" and isinstance(a, int) and isinstance(b, int) and (a - b) % 2**32 == 0:
            return True                # official readUInt32LE returns signed values
        return abs(a - b) <= max(1e-3, 1e-9 * abs(b))
    return a == b


def canon(recs):
    return sorted(recs, key=lambda r: (r[0], json.dumps(sorted(r[1]), default=str)))


def compare(fam, fn, folder, payloads, js, norm, keys):
    bad = 0
    for p, j in zip(payloads, js):
        if "__error" in j:
            print("JS error", folder, p.hex(), j["__error"]); bad += 1; continue
        exp = []
        for key in keys:
            for r in j.get(key, []):
                r = dict(r); t = r.pop("timestamp")
                r = norm(r)
                if r: exp.append((t, r))
        mine = fn(p)
        e, m = canon(exp), canon(mine)
        ok = len(e) == len(m) and all(te == tm and set(ve) == set(vm) and all(same(vm[k], ve[k], fam) for k in ve)
                                      for (te, ve), (tm, vm) in zip(e, m))
        if not ok:
            bad += 1
            if bad <= 5: print("MISMATCH", folder, p.hex(), "\n  js  ", e, "\n  ours", m)
    return bad


total = bad_total = 0
results = {}
for fam, (fname, folders, gens, norm, keys) in FAM.items():
    fn = getattr(dec, fname)
    for folder in folders:
        payloads = [build(gens, LIVE.get(fam)) for _ in range(N_PAYLOADS)]
        js = run_node(folder, [p.hex() for p in payloads])
        nrec = sum(len(fn(p)) for p in payloads)
        bad = compare(fam, fn, folder, payloads, js, norm, keys)
        results[folder] = (fname, len(payloads), nrec, bad)
        total += len(payloads); bad_total += bad

payloads = [wt102_payload() for _ in range(N_PAYLOADS)]
js = run_node("wt-series/wt102", [p.hex() for p in payloads])
bad = compare("wt102", dec.history_wt102, "wt-series/wt102", payloads, js, norm_wt102, ("history",))
results["wt-series/wt102"] = ("history_wt102", len(payloads), sum(len(dec.history_wt102(p)) for p in payloads), bad)
total += len(payloads); bad_total += bad

# a few hand-made edge cases: truncated record stops parsing, unknown channel stops parsing
assert dec.history_ws203(bytes.fromhex("20ce00f15365")) == []
assert dec.history_ws203(bytes.fromhex("20ce00f1536501010a0164")) == [(1700000000, {"temperature": 26.6, "humidity": 50.0, "occupancy": 1})]
assert len(dec.history_vs35x(bytes.fromhex("20ce00f15365000100020099" + "20ce00f153650001000200"))) == 1
assert dec.history_uc300(bytes.fromhex("20dd00f15365010000000001000000")) == [(1700000000, {"modbus_chn_1": 1})]   # coil kept


# ---------------------------------------------------------------- downlink templates (g23.json) vs official encoders
SPECS = json.loads((HERE / "hist_g23.json").read_text())
INVERTED = {"vs-series/vs133", "vs-series/vs135", "vs-series/vs351", "ws-series/ws203", "wt-series/wt201"}
CMD = {"wt-series/wt102", "wt-series/wt303", "wt-series/wt304", "wt-series/wt401"}


def tmpl(spec, vals):
    if "hex" in spec: return spec["hex"]
    return spec["prefix"] + "".join(struct.pack("<I", v).hex() for v in vals)


def cases(folder, spec_name, spec):
    """-> list of (payload, values for the template)"""
    out = []
    if spec_name in ("enable", "retransmit"):
        for state in ("on", "off"):
            if folder in CMD:
                key = "enable" if spec_name == "enable" else "retransmission_enable"
                out.append(({"data_storage_settings": {key: int(state == "on")}}, state))
            else:
                key = "history_enable" if spec_name == "enable" else "retransmit_enable"
                out.append(({key: "enable" if state == "on" else "disable"}, state))
        return out
    if spec_name == "stop": return [({"stop_historical_data_retrieval": 1} if folder in CMD else {"stop_transmit": "yes"}, None)]
    if spec_name == "clear": return [({"clear_historical_data": 1} if folder in CMD else {"clear_history": "yes"}, None)]
    for _ in range(5):
        s = R(1_500_000_000, 1_800_000_000); e = s + R(1, 10**6)
        if spec_name == "fetch":
            if folder in CMD: out.append(({"retrieve_historical_data_by_time_range": {"start_time": s, "end_time": e}}, [s, e]))
            elif folder in INVERTED: out.append(({"fetch_history": {"start_time": s}}, [s, 0]))
            else: out.append(({"fetch_history": {"start_time": s, "end_time": e}}, [s, e]))
        else:   # fetch_since
            if folder in CMD: out.append(({"retrieve_historical_data_by_time": {"time": s}}, [s]))
            elif folder in INVERTED: out.append(({"fetch_history": {"start_time": s, "end_time": e}}, [s]))
            else: out.append(({"fetch_history": {"start_time": s}}, [s]))
    return out


dl_total = dl_bad = 0
for folder, d in SPECS.items():
    jobs = []
    for name in ("enable", "retransmit", "fetch", "fetch_since", "stop", "clear"):
        spec = d.get(name)
        if not spec: continue
        for payload, vals in cases(folder, name, spec):
            want = tmpl(spec[vals], []) if isinstance(vals, str) else tmpl(spec, vals or [])
            jobs.append((name, payload, want))
    if not jobs: continue
    inp = TMP / "enc_in.json"; inp.write_text(json.dumps([j[1] for j in jobs]))
    model = folder.split("/")[1]
    ref = json.loads(subprocess.check_output(["node", str(REPO / "tools" / "run_official_encoder.js"),
                                              str(SD / folder / f"{model}-encoder.js"), str(inp)]))
    for (name, payload, want), got in zip(jobs, ref):
        dl_total += 1
        if got != want:
            dl_bad += 1; print("DOWNLINK MISMATCH", folder, name, payload, "ours", want, "official", got)
print(f"downlinks: {dl_total} commands checked, {dl_bad} mismatches")
bad_total += dl_bad

for folder, (fname, n, nrec, bad) in results.items():
    print(f"{folder:22s} {fname:18s} payloads={n} records={nrec} mismatches={bad}")
print(f"TOTAL {total} payloads, {bad_total} mismatches")
sys.exit(1 if bad_total else 0)
