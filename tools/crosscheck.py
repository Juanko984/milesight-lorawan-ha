"""Cross-check our Python decoders against Milesight's official JavaScript decoders.

    git clone --depth 1 https://github.com/Milesight-IoT/SensorDecoders
    python tools/crosscheck.py SensorDecoders        (needs Node.js)

For every model in MODELS below it decodes the official sample payload plus 200
random payloads with both decoders and reports any difference.
To add a model: add its folder, decoder family and channel list to MODELS (and a
value generator to CH if it uses a new channel).
"""
import json, random, subprocess, sys, importlib.util, struct, types, pathlib
HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent / "custom_components" / "milesight_lorawan"
pkg = types.ModuleType("mlw"); pkg.__path__=[str(PKG)]; sys.modules["mlw"]=pkg
spec = importlib.util.spec_from_file_location("mlw.decoders", PKG/"decoders.py"); dec = importlib.util.module_from_spec(spec); sys.modules["mlw.decoders"]=dec; spec.loader.exec_module(dec)
MS = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "SensorDecoders")
random.seed(1)
def u16(v): return struct.pack("<H", v)
CH = {  # (cid,ctype) -> random value bytes generator
 (0x01,0x75): lambda: bytes([random.randint(0,100)]),
 (0x03,0x67): lambda: struct.pack("<h", random.randint(-300,600)),
 (0x04,0x68): lambda: bytes([random.randint(0,200)]),
 (0x06,0x00): lambda: bytes([random.randint(0,1)]),
 (0x05,0x00): lambda: bytes([random.randint(0,1)]),
 (0x05,0xc8): lambda: struct.pack("<I", random.randint(0,10**6)),
 (0x05,0xe1): lambda: u16(random.randint(1,100))+u16(random.randint(1,100))+struct.pack("<f", random.random()*1000),
 (0x06,0xcb): lambda: bytes([random.randint(0,5)]),
 (0x07,0x7d): lambda: u16(random.randint(400,5000)),
 (0x08,0x7d): lambda: u16(random.randint(0,500)),
 (0x08,0xe6): lambda: u16(random.randint(0,3000)),
 (0x09,0x73): lambda: u16(random.randint(9000,11000)),
 (0x0a,0x7d): lambda: u16(random.randint(0,200)),
 (0x0b,0x7d): lambda: u16(random.randint(0,500)),
 (0x0c,0x7d): lambda: u16(random.randint(0,500)),
 (0x0d,0x7d): lambda: u16(random.randint(0,200)),
 (0x0e,0x01): lambda: bytes([random.randint(0,1)]),
 (0x0f,0x7d): lambda: u16(random.randint(0,2000)),
 (0x04,0xc9): lambda: bytes([random.randint(0,20), 4]) + u16(random.randint(0,15))[::-1],
 (0x05,0xcc): lambda: struct.pack("<hh", random.randint(0,50), random.randint(0,50)),
 (0x06,0xcd): lambda: bytes([random.randint(0,30)]),
 (0x0d,0xcc): lambda: u16(random.randint(0,999))+u16(random.randint(0,999)),
 (0x0e,0xe4): lambda: bytes([1])+u16(random.randint(0,999))+u16(random.randint(0,999)),
 # EM500 range
 (0x03,0x67,"plain"): lambda: struct.pack("<h", random.randint(-300,600)),
 (0x83,0xd7): lambda: struct.pack("<hh", random.randint(-300,600), random.randint(-100,100)) + bytes([random.randint(0,4)]),
 (0x04,0xca): lambda: u16(random.choice([random.randint(0,10000), 0xffff, 0xfffd])),
 (0x05,0x7d): lambda: u16(random.randint(400,5000)),
 (0x06,0x73): lambda: u16(random.randint(9000,11000)),
 (0x03,0x7b): lambda: struct.pack("<h", random.randint(-100,2000)),
 (0x03,0x94): lambda: struct.pack("<I", random.randint(0,100000)),
 (0x05,0x7f): lambda: u16(random.choice([random.randint(0,20000), 0xffff, 0xfffd])),
 (0x03,0x77): lambda: u16(random.choice([random.randint(0,5000), 0xffff, 0xfffd])),
 (0x03,0x82): lambda: u16(random.randint(0,10000)),
 (0x83,0xe9): lambda: u16(random.randint(0,10000)) + u16(random.randint(0,1000)) + bytes([random.randint(0,4)]),
 # VS340 / VS341 / VS370
 (0x03,0x00): lambda: bytes([random.randint(0,1)]),
 (0x04,0x00): lambda: bytes([random.choice([0,1,254])]),
 # VS321
 (0x03,0x67): lambda: random.choice([struct.pack("<h", random.randint(-300,600)), b"\xff\xff"]),
 (0x04,0x68): lambda: bytes([random.choice([random.randint(0,200), 0xff])]),
 (0x83,0x67): lambda: struct.pack("<h", random.randint(-300,600)) + bytes([random.randint(0,4)]),
 (0x84,0x68): lambda: bytes([random.randint(0,200), random.randint(0,4)]),
 (0x05,0xfd): lambda: u16(random.randint(0,60)),
 (0x06,0xfe): lambda: u16(random.randint(0,1023)) + u16(random.randint(0,1023)),
 (0x07,0xff): lambda: bytes([random.randint(0,1)]),
 (0x08,0xf4): lambda: bytes([0, random.randint(0,1)]),
 (0x0a,0xef): lambda: struct.pack("<I", random.randint(0, 2**31)),
 # VS373
 (0x03,0xf8): lambda: bytes([random.randint(0,4), random.randint(0,3)]) + u16(random.randint(0,9999)) + u16(random.randint(0,9999)),
 (0x07,0xb0): lambda: bytes([random.randint(0,4), random.randint(0,3)]) + struct.pack("<I", random.randint(0,2**24-1))[:3] + struct.pack("<I", random.randint(0,2**24-1))[:3],
 (0x04,0xf9): lambda: bytes([random.randint(0,1) for _ in range(4)]),
 (0x09,0xb2): lambda: bytes([random.choice([0,1,2,3,255]) for _ in range(6)]),
 (0x0a,0xb3): lambda: bytes([random.randint(1,6)]) + struct.pack("<I", random.randint(0,63)),
 (0x05,0xfa): lambda: b"".join(u16(random.randint(0,9999)) for _ in range(4)),
 (0x0b,0xb4): lambda: b"".join(struct.pack("<I", random.randint(0,2**24-1))[:3] for _ in range(3)),
 (0x0c,0xb4): lambda: b"".join(struct.pack("<I", random.randint(0,2**24-1))[:3] for _ in range(3)),
 (0x06,0xfb): lambda: u16(random.randint(0,999)) + bytes([random.randint(0,8), random.randint(1,4), random.randint(1,6)]),
 (0x08,0xb1): lambda: bytes([random.randint(1,5)]) + u16(random.randint(0,4000)),
}
def i16(v): return struct.pack("<h", v)
def i32(v): return struct.pack("<i", v)
def ts_temp(cid): return lambda: bytes([cid, 0x67]) + i16(random.randint(-400, 1200))
def ts_alarm_thr(cid, t, codes): return lambda: bytes([cid, t]) + (i16(random.randint(-400, 1200)) if t != 0x68 else bytes([random.randint(0, 200)])) + bytes([random.choice(codes)])
TS_OLD = [0, 1, 2]
TS_NEW = list(range(9))
def ts60_level(cmd, size):
    def g():
        code = random.choice([0, 1, 2, 3, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x30])
        body = b""
        if 0x10 <= code <= 0x17 or code == 0x30:
            body = i32(random.randint(-4000, 7000)) if size == 4 else u16(random.randint(0, 1000))
        return bytes([cmd, code]) + body
    return g
TS60X = [
    lambda: bytes([0x01, random.randint(0, 100)]),
    lambda: bytes([0x04]) + i32(random.randint(-4000, 7000)),
    lambda: bytes([0x05]) + u16(random.randint(0, 1000)),
    lambda: bytes([0x06]) + i32(random.randint(-90_000_000, 90_000_000)) + i32(random.randint(-180_000_000, 180_000_000)),
    lambda: bytes([0x07, random.randint(0, 1)]),
    ts60_level(0x08, 4), ts60_level(0x09, 2),
    lambda: bytes([0x0A, random.choice([0, 1, 2, 3, 0x10, 0x11, 0x21])]),
    lambda: bytes([0x0B, random.choice([0, 1, 2, 3, 0x10, 0x11])]),
    lambda: bytes([0x0C, random.randint(0, 1)]),
    lambda: bytes([0x0D]) + i16(random.randint(-9000, 9000)) + i16(random.randint(-9000, 9000)) + i16(random.randint(-9000, 9000)),
    lambda: bytes([0x0E, random.randint(0, 1)]),
    lambda: bytes([0x1A, random.choice([0, 3, 0x11])]), lambda: bytes([0x1B, random.choice([0, 3, 0x13])]),
]

R = random.randint
def seg(*parts): return lambda: b"".join(p() if callable(p) else bytes(p) for p in parts)
def rb(n): return lambda: bytes(R(0, 255) for _ in range(n))
def f16_safe(): return u16(R(0, 0x7BFF) | (R(0, 1) << 15))
def mb_val(dtype, wide=False):
    sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 6: 4, 5: 4, 7: 4, 8: 4, 9: 4, 10: 4, 11: 4, 12: 8, 14: 8, 13: 8, 15: 8}
    if dtype in (5, 7): return struct.pack("<f", random.uniform(-1000, 1000))
    if dtype in (13, 15): return struct.pack("<d", random.uniform(-1000, 1000))
    if dtype in (12, 14): return struct.pack("<q", R(-10**9, 10**9))
    if dtype in (0, 1): return bytes([R(0, 1) if dtype == 0 else R(0, 255)])
    return bytes(R(0, 255) for _ in range(sizes[dtype]))
def uc11_mb(offset): 
    def g():
        dt = R(0, 7); return bytes([0xFF, 0x0E, R(1, 8) + offset, dt]) + mb_val(dt)
    return g
def mb19(types):
    def g():
        dt = random.choice(types); return bytes([0xFF, 0x19, R(0, 15), 4, dt | (R(0, 1) << 7)]) + mb_val(dt)
    return g
UC50X_MB = lambda: (lambda dt, cid: bytes([cid, 0x0E, R(7, 20), dt]) + mb_val(dt) + (bytes([R(1, 2)]) if cid == 0x80 else b""))(R(0, 7), random.choice([0xFF, 0x80]))
def uc100v2():
    dt = random.choice([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])
    return bytes([0xF9, 0x73, R(0, 255), (R(0, 1) << 7) | (R(0, 3) << 5) | dt]) + mb_val(dt)
UC_STAT = lambda cid: seg([cid, 0xE2], f16_safe, f16_safe, f16_safe, f16_safe)

MODELS = {
 "em-series/em300-th": ("em300", [(1,0x75),(3,0x67),(4,0x68)]),
 "em-series/em300-mcs": ("em300", [(1,0x75),(3,0x67),(4,0x68),(6,0)]),
 "em-series/em300-zld": ("em300", [(1,0x75),(3,0x67),(4,0x68),(5,0)]),
 "em-series/em300-sld": ("em300", [(1,0x75),(3,0x67),(4,0x68),(5,0)]),
 "em-series/em300-di": ("em300", [(1,0x75),(3,0x67),(4,0x68),(5,0),(5,0xc8),(5,0xe1)]),
 "am-series/am307": ("am300", [(1,0x75),(3,0x67),(4,0x68),(5,0),(6,0xcb),(7,0x7d),(8,0x7d),(9,0x73),(0xe,1)]),
 "am-series/am308": ("am300", [(1,0x75),(3,0x67),(4,0x68),(5,0),(6,0xcb),(7,0x7d),(8,0xe6),(9,0x73),(0xb,0x7d),(0xc,0x7d),(0xe,1)]),
 "am-series/am319-hcho": ("am300", [(3,0x67),(4,0x68),(5,0),(6,0xcb),(7,0x7d),(8,0x7d),(9,0x73),(0xa,0x7d),(0xb,0x7d),(0xc,0x7d),(0xe,1)]),
 "am-series/am319-hcho-well": ("am300", [(3,0x67),(4,0x68),(7,0x7d),(8,0xe6),(9,0x73),(0xb,0x7d),(0xf,0x7d)]),
 "am-series/am319-o3": ("am300", [(3,0x67),(4,0x68),(5,0),(7,0x7d),(8,0x7d),(9,0x73),(0xb,0x7d),(0xc,0x7d),(0xd,0x7d)]),
 "vs-series/vs121": ("vs121", [(4,0xc9),(5,0xcc),(6,0xcd),(0xd,0xcc),(0xe,0xe4)]),
 "em-series/em500-co2": ("em500", [(1,0x75),(3,0x67,"plain"),(4,0x68),(5,0x7d),(6,0x73),(0x83,0xd7)]),
 "em-series/em500-lgt": ("em500", [(1,0x75),(3,0x94)]),
 "em-series/em500-pp": ("em500", [(1,0x75),(3,0x7b)]),
 "em-series/em500-pt100": ("em500", [(1,0x75),(3,0x67,"plain"),(0x83,0xd7)]),
 "em-series/em500-smtc": ("em500_smtc", [(1,0x75),(3,0x67,"plain"),(4,0x68),(4,0xca),(5,0x7f),(0x83,0xd7)]),
 "em-series/em500-swl": ("em500", [(1,0x75),(3,0x77)]),
 "em-series/em500-udl": ("em500", [(1,0x75),(3,0x82),(0x83,0xe9)]),
 "ts-series/ts101": ("ts101", [lambda: bytes([1, 0x75, random.randint(0, 100)]), ts_temp(0x03),
                               ts_alarm_thr(0x83, 0x67, TS_OLD),
                               lambda: bytes([0x93, 0xD7]) + i16(random.randint(-400, 1200)) + i16(random.randint(-500, 500)) + bytes([random.choice(TS_OLD)])]),
 "ts-series/ts201": ("ts201", [lambda: bytes([1, 0x75, random.randint(0, 100)]), ts_temp(0x03), ts_alarm_thr(0x83, 0x67, TS_OLD),
                               lambda: bytes([0x93, 0x67]) + i16(random.randint(-400, 1200)) + i16(random.randint(-500, 500)) + bytes([random.choice(TS_OLD)])]),
 "ts-series/ts201-v2": ("ts201", [lambda: bytes([1, 0x75, random.randint(0, 100)]), ts_temp(0x03),
                                  lambda: bytes([0x04, 0x68, random.randint(0, 200)]), ts_alarm_thr(0x83, 0x67, TS_OLD), ts_alarm_thr(0x84, 0x68, TS_OLD),
                                  lambda: bytes([0x93, 0x67]) + i16(random.randint(-400, 1200)) + i16(random.randint(-500, 500)) + bytes([random.choice(TS_OLD)]),
                                  lambda: bytes([0x94, 0x68, random.randint(0, 200), random.randint(0, 200), random.choice(TS_OLD)])]),
 "ts-series/ts301": ("ts301_v1", [lambda: bytes([1, 0x75, random.randint(0, 100)]), ts_temp(0x03), lambda: bytes([3, 0, random.randint(0, 1)]),
                                  ts_alarm_thr(0x83, 0x67, TS_OLD),
                                  lambda: bytes([0x93, 0xD7]) + i16(random.randint(-400, 1200)) + i16(random.randint(-500, 500)) + bytes([random.choice(TS_OLD)])]),
 "ts-series/ts301-v2": ("ts301", [lambda: bytes([1, 0x75, random.randint(0, 100)]), ts_temp(0x03), lambda: bytes([3, 0, random.randint(0, 1)]),
                                  lambda: bytes([3, 0x9A]) + i16(random.randint(0, 1000)), ts_alarm_thr(0x83, 0x67, TS_NEW), ts_alarm_thr(0x83, 0x9A, TS_NEW),
                                  lambda: bytes([0x93, 0x67]) + i16(random.randint(-400, 1200)) + i16(random.randint(-500, 500)) + bytes([8]),
                                  lambda: bytes([0xB3, 0x67, random.randint(0, 2)])]),
 "ts-series/ts302": ("ts302_v1", [lambda: bytes([1, 0x75, random.randint(0, 100)]), ts_temp(0x03), ts_temp(0x04),
                                  lambda: bytes([3, 0, random.randint(0, 1)]), lambda: bytes([4, 0, random.randint(0, 1)]),
                                  ts_alarm_thr(0x83, 0x67, TS_OLD), ts_alarm_thr(0x84, 0x67, TS_OLD),
                                  lambda: bytes([0x93, 0xD7]) + i16(random.randint(-400, 1200)) + i16(random.randint(-500, 500)) + bytes([random.choice(TS_OLD)]),
                                  lambda: bytes([0x94, 0xD7]) + i16(random.randint(-400, 1200)) + i16(random.randint(-500, 500)) + bytes([random.choice(TS_OLD)])]),
 "ts-series/ts302-v2": ("ts302", [lambda: bytes([1, 0x75, random.randint(0, 100)]), ts_temp(0x03), ts_temp(0x04),
                                  lambda: bytes([3, 0, random.randint(0, 1)]), lambda: bytes([4, 0x9A]) + i16(random.randint(0, 1000)),
                                  ts_alarm_thr(0x83, 0x67, TS_NEW), ts_alarm_thr(0x84, 0x9A, TS_NEW),
                                  lambda: bytes([0x94, 0x67]) + i16(random.randint(-400, 1200)) + i16(random.randint(-500, 500)) + bytes([8]),
                                  lambda: bytes([0xB4, 0x67, random.randint(0, 2)])]),
 "ts-series/ts601": ("ts60x", TS60X),
 "ts-series/ts602": ("ts60x", TS60X),
 "em-series/em400-udl": ("em400", [seg([1, 0x75], rb(1)), seg([3, 0x67], lambda: i16(R(-300, 600))), seg([4, 0x82], rb(2)),
                                     seg([5, 0], lambda: bytes([R(0, 1)])), seg([0x83, 0x67], lambda: i16(R(-300, 600)), lambda: bytes([R(0, 1)])),
                                     seg([0x84, 0x82], rb(2), lambda: bytes([R(0, 1)]))]),
 "em-series/em400-tld": ("em400", [seg([1, 0x75], rb(1)), seg([4, 0x82], rb(2)), seg([5, 0], lambda: bytes([R(0, 1)])), seg([0x84, 0x82], rb(2), lambda: bytes([R(0, 1)]))]),
 "em-series/em400-mud": ("em400", [seg([1, 0x75], rb(1)), seg([3, 0x67], lambda: i16(R(-300, 600))), seg([4, 0x82], rb(2)), seg([0x83, 0x67], lambda: i16(R(-300, 600)), lambda: bytes([R(0, 1)]))]),
 "uc-series/uc11-t1": ("uc11t1", [seg([3, 0x75], rb(1)), seg([1, 0x67], lambda: i16(R(-300, 600))), seg([2, 0x68], rb(1))]),
 "uc-series/uc11xx": ("uc11xx", [seg([1, 0], lambda: bytes([R(0, 1)])), seg([2, 0], lambda: bytes([R(0, 1)])), seg([1, 0xC8], rb(4)), seg([2, 0xC8], rb(4)),
                                 seg([9, 1], lambda: bytes([R(0, 1)])), seg([0x0A, 1], lambda: bytes([R(0, 1)])), seg([0x11, 2], rb(8)), seg([0x12, 2], rb(8)), uc11_mb(0)]),
 "uc-series/uc11-n1": ("uc11n1", [seg([1, 0x75], rb(1)), seg([3, 0], lambda: bytes([R(0, 1)])), seg([4, 0], lambda: bytes([R(0, 1)])), seg([4, 0xC8], rb(4)),
                                  seg([5, 2], rb(8)), seg([6, 2], rb(8)), uc11_mb(6)]),
 "uc-series/uc300": ("uc300", [seg([R(3, 6), 0], lambda: bytes([R(0, 1)])), seg([5, 0xC8], rb(4)), seg([7, 1], lambda: bytes([R(0, 1)])), seg([8, 1], lambda: bytes([R(0, 1)])),
                               seg([9, 0x67], lambda: i16(R(-500, 2000))), seg([0x0B, 2], rb(4)), seg([0x0E, 2], rb(4)), UC_STAT(0x0A), UC_STAT(0x0C), UC_STAT(0x0D),
                               mb19([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]), seg([0xFF, 0x15], lambda: bytes([R(0, 15)]))]),
 "uc-series/uc501": ("uc50x", [seg([1, 0x75], rb(1)), seg([3, 0], lambda: bytes([R(0, 1)])), seg([4, 1], lambda: bytes([R(0, 1)])), seg([3, 0xC8], rb(4)),
                               seg([0xFF, 0x14], lambda: bytes([(R(1, 2) << 4) | R(0, 1)])), seg([5, 2], rb(8)), UC_STAT(0x06),
                               seg([0x85, 0xE2], f16_safe, f16_safe, f16_safe, f16_safe, lambda: bytes([R(1, 2)])),
                               seg([8, 0xDB], lambda: bytes([R(0, 3)]) + b"0+12.5+3.2".ljust(36, b"\x00")), UC50X_MB, seg([0xFF, 0x15], lambda: bytes([R(7, 20)]))]),
 "uc-series/uc511": ("uc51x", [seg([1, 0x75], rb(1)), seg([3, 1], lambda: bytes([random.choice([0, 1, 0xFF])])), seg([5, 1], lambda: bytes([R(0, 1)])),
                               seg([4, 0xC8], rb(4)), seg([6, 0xC8], rb(4)), seg([7, 1], lambda: bytes([R(0, 1)])), seg([9, 0x7B], rb(2)),
                               seg([0xB9, 0x7B], lambda: bytes([1])), seg([0x0B, 0xF5], rb(8), lambda: bytes([R(0, 1)])), seg([0x0E, 0xAF], rb(3))]),
 "uc-series/uc512": ("uc51x", [seg([1, 0x75], rb(1)), seg([3, 1], lambda: bytes([R(0, 1)])), seg([4, 0xC8], rb(4)), seg([8, 1], lambda: bytes([R(0, 1)])), seg([9, 0x7B], rb(2))]),
 "uc-series/uc521": ("uc521", [seg([1, 0x75], rb(1)), seg([3, 0xF6], lambda: bytes([R(0, 1), R(0, 200)])), seg([5, 0xF6], lambda: bytes([R(0, 1), R(0, 100)])),
                               seg([4, 0xC8], rb(4)), seg([8, 1], lambda: bytes([R(0, 1)])), seg([9, 0x7B], rb(2)), seg([0x0A, 0x7B], rb(2)),
                               seg([0x0C, 0xF5], lambda: bytes([R(0, 3), R(0, 4)]), rb(6), lambda: bytes([R(0, 1)])), seg([0x0D, 0xE3], rb(4)),
                               seg([0xB3, 0xF6], lambda: bytes([R(0, 1), R(0, 3)])), seg([0xBA, 0x7B], lambda: bytes([R(0, 2)])), seg([0x0F, 0x01], rb(1))]),
 "uc-series/uc100": ("uc100", [mb19([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]), seg([0xFF, 0x15], lambda: bytes([R(0, 31)])),
                               lambda: (lambda dt: bytes([0xFF, 0xEE, R(0, 255), 4, dt | (R(0, 1) << 7)]) + mb_val(dt))(random.choice([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])),
                               seg([0xF9, 0x5F], lambda: bytes([R(0, 255), 0, 0]), lambda: struct.pack("<f", random.uniform(-100, 100)))]),
 "uc-series/uc100-v2": ("uc100_v2", [uc100v2, seg([0xFF, 0x15], lambda: bytes([R(0, 31)])),
                                     seg([0xF9, 0x74], lambda: bytes([R(0, 255)]), lambda: struct.pack("<d", random.uniform(-100, 100)))]),
 "vs-series/vs340": ("vs_occupancy", [(1,0x75),(3,0x00)]),
 "vs-series/vs341": ("vs_occupancy", [(1,0x75),(3,0x00)]),
 "vs-series/vs370": ("vs_occupancy", [(1,0x75),(3,0x00),(4,0x00)]),
 "vs-series/vs321": ("vs321", [(1,0x75),(3,0x67),(4,0x68),(0x83,0x67),(0x84,0x68),(5,0xfd),(6,0xfe),(7,0xff),(8,0xf4),(0xa,0xef)]),
 "vs-series/vs373": ("vs373", [(3,0xf8),(7,0xb0),(4,0xf9),(9,0xb2),(0xa,0xb3),(5,0xfa),(0xb,0xb4),(0xc,0xb4),(6,0xfb),(8,0xb1)]),
}
STR = {"open":1,"close":0,"leak":1,"normal":0,"trigger":1,"idle":0,"on":1,"off":0,"high":1,"low":0}
STR_VS = {"vacant":0,"occupied":1}   # VS-series occupancy strings -> 0/1
RENAME = {"magnet_status":"magnet_status","leakage_status":"input_05","gpio":"input_05","pulse":"pulse_count","buzzer_status":"buzzer",
          "people_total_counts":"people_count_all","timestamp":"device_timestamp","illuminance_status":"illuminance"}
# fields whose official value is an alarm/status string we keep as raw codes
RAW_CODES = {"temperature_alarm","humidity_alarm","distance_alarm","measuring_equipment"}
SKIP = {"history"}
total=bad=0
for folder,(kind,chans) in MODELS.items():
    d = MS/folder; dfile = next(d.glob("*-decoder.js"))
    codec = next(d.glob("*-codec.json"), None)
    payloads = []
    if codec:
        sample = json.load(open(codec)).get("bytes")
        if sample: payloads.append(sample.lower())
    for _ in range(200):
        sel = random.sample(chans, random.randint(1, len(chans)))
        payloads.append(b"".join(c() if callable(c) else bytes(c[:2])+CH[c]() for c in sel).hex())
    inp = HERE / "_in.json"; json.dump(payloads, open(inp, "w"))
    ref = json.loads(subprocess.check_output(["node", str(HERE / "run_official_decoder.js"), str(dfile), str(inp)]))
    fn = getattr(dec, f"decode_{kind}")
    for h, r in zip(payloads, ref):
        mine = fn(bytes.fromhex(h)); total += 1
        exp = {}
        if kind == "ts60x":
            for k in ("battery", "temperature", "humidity"):
                if k in r: exp[k] = r[k]
            if "base_station_position" in r:
                exp["latitude"] = r["base_station_position"]["latitude"]; exp["longitude"] = r["base_station_position"]["longitude"]
            if "probe_connect_status" in r: exp["probe_connected"] = r["probe_connect_status"] == 1
            if "relative_surface_info" in r:
                for a in ("x", "y", "z"): exp[f"angle_{a}"] = r["relative_surface_info"][f"angle_{a}"]
            r = {}
        if kind == "em400":
            r = {(k + "_status" if k.endswith("_alarm") else k): v for k, v in r.items()}
        if kind.startswith("uc"):
            r = {k: v for k, v in r.items() if k not in ("event", "history") and not isinstance(v, (dict, list))
                 and not (kind == "uc521" and k.endswith("_sensor_status"))
                 # UC100 v2: we also expose event alarms as <chn>_alarm (official only lists them under "event")
                 and not (kind == "uc100_v2" and k.endswith("_alarm"))}
            r = {k: (STR[v] if isinstance(v, str) and v in STR and v != "normal" else v) for k, v in r.items()}
        if kind.startswith("ts") and kind != "ts60x":
            r2 = {}
            for k, v in r.items():
                if k in ("event", "history") or k.endswith("_sensor_status") or k.startswith("sensor_"): continue
                k = k.replace("_chn1", "_1").replace("_chn2", "_2")
                if k.endswith("_alarm"):            # compare normalised alarm text too
                    k, v = k + "_status", str(v).replace(" ", "_")
                if k.startswith("magnet"): k, v = k.replace("magnet", "magnet_status"), STR.get(v, v)
                r2[k] = v
            r = r2
        for k,v in r.items():
            if k in SKIP: continue
            k2 = RENAME.get(k,k)
            if k == "tvoc" and kind=="am300":   # official uses one key for both units
                k2 = "tvoc_iaq" if "087d" in h else "tvoc"
            if folder.endswith("em500-pp") and k == "pressure":
                k2 = "pressure_kpa"
            if kind.startswith("em500") and k in RAW_CODES:
                continue
            if kind.startswith("vs") and kind != "vs121":
                if k in RAW_CODES: continue
                if isinstance(v,str) and v in STR_VS and (k == "occupancy" or k.startswith("region_")):
                    v = STR_VS[v]
                if kind == "vs_occupancy" and k == "occupancy" and v == "unknown": v = 0
                # detection_status / illuminance etc. stay strings on both sides
            elif isinstance(v,str) and v in STR and not ((kind.startswith("uc") or kind == "em400") and v == "normal"): v = STR[v]
            exp[k2] = v
        def same(a, b):
            if b == "unknown":                     # official returns "unknown" for out-of-range enum bytes
                return True
            if isinstance(a, int) and isinstance(b, int) and kind == "uc50x" and (a - b) % 2**32 == 0:
                return True                        # uc501/502 official readUInt32LE returns signed values
            if isinstance(b, (int, float)) and isinstance(a, (int, float)):
                return abs(a - b) <= max(1e-3, 1e-9 * abs(b))
            return a == b
        diffs = {k: (exp[k], mine.get(k)) for k in exp if not (k in mine and same(mine[k], exp[k]))}
        if diffs:
            bad += 1
            if bad <= 8: print(folder, h, diffs)
inp.unlink(missing_ok=True)
print(f"{total} payloads checked, {bad} mismatches")
sys.exit(1 if bad else 0)
