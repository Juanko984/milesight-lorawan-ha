"""Cross-check our Python decoders against Milesight's official JavaScript decoders.

    git clone --depth 1 https://github.com/Milesight-IoT/SensorDecoders
    python tools/crosscheck.py SensorDecoders        (needs Node.js)

For every model in MODELS below it decodes the official sample payload plus 200
random payloads with both decoders and reports any difference.
To add a model: add its folder, decoder family and channel list to MODELS (and a
value generator to CH if it uses a new channel).
"""
import json, re, random, subprocess, sys, importlib.util, struct, types, pathlib
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

CT_ALM = lambda: bytes([R(0, 15)])
CT10X = [seg([3, 0x97], rb(4)), seg([4, 0x98], lambda: u16(random.choice([R(0, 60000), 0xFFFF]))),
         seg([9, 0x67], lambda: random.choice([i16(R(-300, 900)), b"\xfd\xff", b"\xff\xff"])),
         seg([0x84, 0x98], rb(6), CT_ALM), seg([0x89, 0x67], lambda: i16(R(-300, 900)), lambda: bytes([R(0, 1)])),
         seg([0x10, 0x63], rb(4)), seg([0x13, 0x75], lambda: bytes([1]))]
CT10X_V1 = CT10X[:-2]            # firmware v1 has no energy / low-voltage channels
CT30X = [seg([c, 0x97], rb(4)) for c in (3, 5, 7)] + \
        [seg([c, 0x99], lambda: u16(random.choice([R(0, 60000), 0xFFFF]))) for c in (4, 6, 8)] + \
        [seg([c, 0x99], rb(6), CT_ALM) for c in (0x84, 0x86, 0x88)] + \
        [seg([c, 0x63], rb(4)) for c in (0x10, 0x11, 0x12)] + \
        [seg([9, 0x67], lambda: random.choice([i16(R(-300, 900)), b"\xfd\xff", b"\xff\xff"])),
         seg([0x89, 0x67], lambda: i16(R(-300, 900)), lambda: bytes([R(0, 1)])), seg([0x13, 0x75], lambda: bytes([1]))]
CT30X_V1 = [g for idx, g in enumerate(CT30X) if not 9 <= idx <= 11][:-1]

GS101 = [seg([5, 0x8E], lambda: bytes([R(0, 1)])), seg([6, 1], lambda: bytes([R(0, 1)])), seg([7, 1], lambda: bytes([R(0, 1)])),
         seg([8, 0x90], rb(4)), seg([0xFF, 0x3F], lambda: bytes([R(0, 5)]))]
GS301 = [seg([1, 0x75], lambda: bytes([R(0, 100)])), seg([2, 0x67], lambda: i16(R(-200, 600))), seg([3, 0x68], rb(1)),
         seg([4, 0x7D], lambda: u16(random.choice([R(0, 5000), 0xFFFE, 0xFFFF]))),
         seg([5, 0x7D], lambda: u16(random.choice([R(0, 5000), 0xFFFE, 0xFFFF]))),
         seg([6, 0x7D], lambda: u16(random.choice([R(0, 5000), 0xFFFE, 0xFFFF]))),
         seg([7, 0xEA], lambda: bytes([R(0, 1), R(0, 1)]), rb(2), lambda: bytes([R(0, 3)]))]
GS524N = [lambda: bytes([R(0, 255), 0x10 | random.choice([1, 2, 4, 5, 7, 0xA, 0xB, 0xE, 0xF]), R(0, 100), R(0, 255), R(0, 255), R(0, 255)])]
def gs601_alarm(cmd, size, codes):
    def g():
        c = random.choice(codes)
        return bytes([cmd, c]) + (rb(size)() if c in (0x10, 0x11) else b"")
    return g
GS601 = [seg([0x00], lambda: bytes([R(0, 100)])), seg([0x01], lambda: bytes([R(0, 100)])), seg([0x03], rb(2)), seg([0x05], rb(2)),
         seg([0x07], rb(2)), seg([0x09], lambda: i16(R(-200, 600))), seg([0x0B], lambda: u16(R(0, 1000))), seg([0x0D], rb(2)),
         gs601_alarm(0x02, 1, [0, 1, 2, 0x10, 0x11, 0x20, 0x21]), gs601_alarm(0x04, 2, [0, 1, 2, 0x10, 0x11]),
         gs601_alarm(0x06, 2, [0, 1, 2, 0x10, 0x11]), gs601_alarm(0x08, 2, [0, 1, 2, 0x10, 0x11]),
         gs601_alarm(0x0A, 2, [0, 1, 2, 0x10, 0x11, 0x20, 0x21]), gs601_alarm(0x0C, 0, [0, 1, 2]),
         gs601_alarm(0x0E, 2, [0, 1, 2, 0x10, 0x11]), seg([0x0F], lambda: bytes([R(0, 1)])),
         seg([0x10], lambda: bytes([random.choice([0x20, 0x21])])), seg([0x11], lambda: bytes([R(0, 1)])),
         seg([0x12], lambda: bytes([R(0, 1)])), seg([0x2B], rb(4)), seg([0x20], rb(8)), seg([0xC8], lambda: bytes([R(0, 1)]))]

AT101 = [seg([1, 0x75], lambda: bytes([R(0, 100)])), seg([3, 0x67], lambda: i16(R(-300, 700))),
         seg([random.choice([4, 0x84]), 0x88], lambda: i32(R(-90_000_000, 90_000_000)) + i32(R(-180_000_000, 180_000_000)), lambda: bytes([R(0, 3) << 4 | R(0, 3)])),
         seg([5, 0], lambda: bytes([R(0, 1)])), seg([7, 0], lambda: bytes([R(0, 1)])),
         seg([0x83, 0x67], lambda: i16(R(-300, 700)), lambda: bytes([R(0, 1)])),
         seg([6, 0xD9], lambda: bytes([R(0, 3)]), lambda: random.choice([b"\xff" * 6, rb(6)()]), rb(1), lambda: bytes([R(0, 3)])),
         seg([0x20, 0xCE], rb(4), lambda: i32(R(-180_000_000, 180_000_000)), lambda: i32(R(-90_000_000, 90_000_000)))]

B1 = lambda: bytes([R(0, 1)])
BAT = seg([1, 0x75], lambda: bytes([R(0, 100)]))
WS = {
 "ws101": [BAT, seg([0xFF, 0x2E], lambda: bytes([R(1, 3)]))],
 "ws136": [BAT, seg([0xFF, 0x34], lambda: bytes([R(1, 6)]), rb(2))],
 "ws156": [BAT, seg([0xFF, 0x34], lambda: bytes([R(1, 6), R(0, 3), R(0, 2)]))],
 "ws201": [BAT, seg([3, 0x82], rb(2)), seg([4, 0xD6], lambda: bytes([R(0, 100)]))],
 "ws202": [BAT, seg([3, 0], B1), seg([4, 0], B1)],
 "ws203": [BAT, seg([3, 0x67], lambda: i16(R(-200, 600))), seg([4, 0x68], rb(1)), seg([5, 0], B1),
           seg([0x83, 0x67], lambda: i16(R(-200, 600)), lambda: bytes([R(0, 1)])), seg([0x20, 0xCE], rb(9))],
 "ws301": [BAT, seg([3, 0], B1), seg([4, 0], B1)],
 "ws302": [BAT, seg([5, 0x5B], lambda: bytes([R(0, 2) | R(0, 2) << 2]), rb(6))],
 "ws303": [BAT, seg([3, 0], B1)],
}
U32 = lambda: struct.pack("<I", R(0, 2**31 - 1))     # WS558's official readUInt32LE is signed above 2^31
METER = [seg([3, 0x74], rb(2)), seg([4, 0x80], U32), seg([5, 0x81], lambda: bytes([R(0, 100)])), seg([6, 0x83], U32), seg([7, 0xC9], rb(2))]
WS["ws50x"] = [seg([0xFF, 0x29], rb(1)), seg([0xFF, 0x2B], rb(1))]
WS["ws50x_eu"] = METER + [seg([8, 0x29], rb(1))]
WS["ws50x_cn"] = [seg([8, 0x29], rb(1))]
WS["ws50x_v4"] = METER + [seg([0xFF, 0x29], rb(1)), seg([0x87, 0xC9], rb(2), lambda: bytes([1])), seg([0x88, 0x29], lambda: bytes([1])),
                          seg([0x89, 0xDF], lambda: bytes([1]))] + [seg([c, t], lambda: bytes([1])) for c, t in ((0xB3, 0x74), (0xB4, 0x80), (0xB5, 0x81), (0xB6, 0x83), (0xB7, 0xC9))]
WS["ws513"] = METER + [seg([8, 0x70], B1), seg([9, 0x67], lambda: random.choice([i16(R(-200, 900)), b"\xfd\xff", b"\xff\xff"])),
                       seg([0x89, 0x67], lambda: i16(R(-200, 900)), lambda: bytes([R(0, 3)])), seg([0x99, 0x67], lambda: i16(R(-200, 900)) + i16(R(-200, 200)), rb(1))]
WS["ws523"] = METER + [seg([8, 0x70], rb(1))]
WS["ws513_v3"] = METER + [seg([8, 0x70], rb(1)), seg([9, 0x67], lambda: random.choice([i16(R(-200, 900)), b"\xfd\xff", b"\xff\xff"])),
                          seg([0x89, 0x67], lambda: i16(R(-200, 900)), lambda: bytes([R(0, 2)])), seg([0x87, 0xC9], rb(2), lambda: bytes([R(0, 1)])),
                          seg([0x88, 0x29], lambda: bytes([1])), seg([0xFF, 0x29], rb(1))]
WS["ws558"] = METER + [seg([8, 0x31], rb(2)), seg([0xFF, 0x26], B1)]

T16 = lambda: i16(R(-200, 600))
T100 = lambda: i16(R(-2000, 6000))
WT = {
 "wt101": [BAT, seg([3, 0x67], T16), seg([4, 0x67], T16), seg([5, 0x92], lambda: bytes([R(0, 100)])), seg([6, 0], B1), seg([7, 0], B1),
           seg([8, 0xE5], lambda: bytes([R(0, 4)])), seg([9, 0x90], rb(2)), seg([0x0A, 0], B1), seg([0x0B, 0x90], rb(2)), seg([0xF9, 0x33], rb(7))],
 "wt201": [seg([3, 0x67], T16), seg([4, 0x67], T16), seg([5, 0xE7], lambda: bytes([R(0, 7) << 4 | R(0, 3)])),
           seg([6, 0xE8], lambda: bytes([R(0, 3) << 2 | R(0, 3)])), seg([7, 0xBC], lambda: bytes([R(0, 4)])), seg([8, 0x8E], B1),
           seg([9, 0x68], rb(1)), seg([0x0A, 0x6E], rb(1)), seg([0xFF, 0xCB], rb(3)), seg([0xB3, 0x67], lambda: bytes([R(1, 2)])),
           seg([0xB9, 0x68], lambda: bytes([R(1, 2)])), seg([0x20, 0xCE], rb(8))],
 "wt201_v2": [seg([3, 0x67], T16), seg([4, 0x67], T16), seg([0x0B, 0x67], T16), seg([5, 0xE7], lambda: bytes([R(0, 9) << 4 | R(0, 3)])),
              seg([6, 0xE8], lambda: bytes([R(0, 3) << 2 | R(0, 3)])), seg([7, 0xBC], lambda: bytes([R(0, 7)])), seg([7, 0xE9], lambda: bytes([R(1, 3)])),
              seg([0x87, 0xE9], lambda: bytes([R(1, 3), 1])), seg([8, 0x8E], B1), seg([9, 0x68], rb(1)), seg([0x0A, 0x6E], rb(1)),
              seg([0xFF, 0xCB], rb(3)), seg([0x83, 0x67], T16, lambda: bytes([R(1, 10)])), seg([0xB3, 0x67], lambda: bytes([R(1, 2)])),
              seg([0xF9, 0x40], lambda: bytes([R(0, 3)]), rb(6)), seg([0x20, 0xCE], rb(13))],
 "wt303": [seg([1], T100), seg([2], lambda: u16(R(0, 1000))), seg([3], T100), seg([4], lambda: bytes([R(0, 3)])),
           seg([5], lambda: bytes([R(0, 2) << 4 | R(0, 2)])), seg([6], lambda: bytes([random.choice([0, 100])])), seg([7], lambda: bytes([R(0, 3) << 4 | R(0, 3)])),
           seg([8], lambda: bytes([random.choice([R(0, 15), 255])])),
           lambda: (lambda c: bytes([9, c]) + (T100() if c >= 0x10 else b""))(random.choice([0, 1, 2, 3] + list(range(0x10, 0x18)) + [0x20, 0x21, 0x22, 0x23, 0x30, 0x31, 0x32, 0x33])),
           seg([0x0A], lambda: bytes([R(0, 3)])), seg([0x0B], lambda: bytes([3])), seg([0x10], lambda: bytes([R(0, 255), 0, 0, 0])), seg([0xC8], B1),
           seg([0x67], B1), seg([0x68], lambda: bytes([R(0, 2)])), seg([0x72], lambda: bytes([R(0, 3)])), seg([0x6B], T100), seg([0x6C], T100)],
 "wt102": [seg([0], lambda: bytes([R(0, 100)])), seg([1], T100), seg([2], rb(2)), seg([3], rb(2)), seg([4], lambda: bytes([R(0, 100)])),
           seg([5], lambda: bytes([R(0, 4)])), seg([6], T100), seg([7], lambda: bytes([R(0, 100)])), seg([8], lambda: bytes([R(0, 100)])),
           lambda: (lambda c: bytes([9, c]) + T100())(R(0x10, 0x13)), lambda: bytes([0x0A, R(0x20, 0x21)]) + T100() + bytes([R(0, 100)]),
           lambda: bytes([0x0B, R(0x20, 0x21)]) + T100() + bytes([R(0, 100), R(0, 100)]),
           lambda: (lambda c: bytes([0x0C, c, R(0, 1)]) + T100() + (T100() if c < 0x22 else bytes([R(0, 100)])))(R(0x20, 0x23)),
           lambda: bytes([0x0D, R(0x20, 0x21), R(0, 1)]) + T100(),
           lambda: (lambda c: bytes([0x0E, c]) + {0: lambda: bytes([R(0, 100), R(0, 100)]), 1: lambda: T100() + bytes([R(0, 100)]) + T100() + bytes([R(0, 100)]),
                                                  2: lambda: T100() + bytes([R(0, 100), R(0, 100), R(0, 100)]),
                                                  3: lambda: T100() + bytes([R(0, 100)]) + T100() + bytes([R(0, 100), R(0, 100)])}[c]())(R(0, 3)),
           seg([0xC8], B1)],
 "wt401": [seg([0], lambda: bytes([R(0, 100)])), seg([1], T100), seg([2], lambda: u16(R(0, 1000))), seg([3], lambda: bytes([random.choice([0, 1, 2, 3, 4, 5, 10, 11])])),
           seg([4], lambda: bytes([random.choice([0, 1, 2, 3, 4, 5, 10, 11])])), seg([5], lambda: bytes([random.choice([R(0, 15), 255])])),
           seg([6], T100), seg([7], T100), seg([8], lambda: bytes([R(0, 2)])), seg([9], lambda: bytes([R(0, 2)])), seg([0x0A], B1),
           seg([0x0B], lambda: bytes([R(0, 3)])), seg([0x0C], lambda: bytes([R(0, 3)])), seg([0x0D], lambda: bytes([R(0, 2)])), seg([0xC8], B1)],
}
def wt30x():
    fid = random.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 0x0F])
    data = bytes([R(0, 1), R(0, 1), R(0, 2), R(0, 3), R(0, 80), R(0, 80), R(0, 1), R(0, 1), R(0, 80)]) if fid == 0x0F else \
        bytes([{1: R(0, 1), 2: R(0, 1), 3: R(0, 2), 4: R(0, 3), 7: R(0, 1), 8: R(0, 1)}.get(fid, R(0, 80))])
    frame = bytes([0x55, random.choice([1, 2])]) + struct.pack(">H", len(data) + 1) + bytes([fid]) + data
    return frame + bytes([sum(frame) & 0xFF])

def cth_masked(cmd, signed):
    def g():
        mask = R(0, 3)
        body = b""
        for gi in range(2):
            for _ in range(3 if mask >> gi & 1 else 1):
                body += random.choice([i32(R(-50000, 500000)) if signed else struct.pack("<I", R(0, 10**7)), b"\xff\xff\xff\xff"])
        return bytes([cmd, mask]) + body
    return g
def cth_pf():
    mask = R(0, 15)
    return bytes([7, mask]) + b"".join(bytes([random.choice([R(0, 100), 255]) for _ in range(3 if mask >> gi & 1 else 1)]) for gi in range(4))
def cth_alarm(cmd):
    def g():
        types = {0x30: [0, 1, 2, 3] + list(range(0x10, 0x18)), 0x33: [0, 0x12, 0x13], 0x34: [0, 0x12, 0x13], 0x35: [0, 0x12, 0x13]}.get(cmd, [0, 1, 2, 3, 4] + list(range(0x10, 0x18)))
        t = random.choice(types)
        withv = {0x30: range(0x10, 0x18), 0x33: (0x12, 0x13), 0x34: (0x12, 0x13), 0x35: (0x12, 0x13)}.get(cmd, (1, 2, 4, *range(0x10, 0x18)))
        val = (struct.pack("<I", R(0, 400000))[:3] if cmd == 0x31 else (i16(R(-2000, 8000)) if cmd == 0x30 else u16(R(0, 30000)))) if t in withv else b""
        ch = bytes([R(0, 11 if cmd in (0x31, 0x33) else 2)]) if cmd in (0x31, 0x32, 0x33, 0x34) else b""
        return bytes([cmd]) + ch + bytes([t]) + val
    return g
U24 = lambda: random.choice([struct.pack("<I", R(0, 400000))[:3], b"\xff\xff\xff"])
U16E = lambda: random.choice([u16(R(0, 50000)), b"\xff\xff"])
CTH = [seg([1], lambda: i16(R(-2000, 8000))), seg([2], U16E), lambda: bytes([3]) + b"".join(U16E() for _ in range(12)),
       lambda: bytes([4]) + b"".join(U16E() for _ in range(3)), lambda: bytes([5]) + b"".join(U24() for _ in range(12)),
       lambda: bytes([6]) + b"".join(U16E() for _ in range(3)), cth_pf] + \
      [cth_masked(c, c in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D)) for c in range(0x08, 0x18)] + \
      [cth_alarm(c) for c in range(0x30, 0x36)] + [seg([0x36]), seg([0xC8], B1)]

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
 "ct-series/ct101": ("ct10x", CT10X_V1),
 "ct-series/ct101-v2": ("ct10x", CT10X),
 "ct-series/ct103": ("ct10x", CT10X_V1),
 "ct-series/ct103-v2": ("ct10x", CT10X),
 "ct-series/ct105": ("ct10x", CT10X_V1),
 "ct-series/ct105-v2": ("ct10x", CT10X),
 "ct-series/ct303": ("ct30x", CT30X_V1),
 "ct-series/ct303-v2": ("ct30x", CT30X),
 "ct-series/ct305": ("ct30x", CT30X_V1),
 "ct-series/ct305-v2": ("ct30x", CT30X),
 "ct-series/ct310": ("ct30x", CT30X_V1),
 "ct-series/ct310-v2": ("ct30x", CT30X),
 "gs-series/gs101": ("gs101", GS101),
 "gs-series/gs301": ("gs301", GS301),
 "gs-series/gs524n": ("gs524n", GS524N),
 "gs-series/gs601": ("gs601", GS601),
 "at-series/at101": ("at101", AT101),
 "ws-series/ws101": ("ws101", WS["ws101"]), "ws-series/ws136": ("ws136", WS["ws136"]), "ws-series/ws156": ("ws156", WS["ws156"]),
 "ws-series/ws201": ("ws201", WS["ws201"]), "ws-series/ws202": ("ws202", WS["ws202"]), "ws-series/ws203": ("ws203", WS["ws203"]),
 "ws-series/ws301": ("ws301", WS["ws301"]), "ws-series/ws302": ("ws302", WS["ws302"]), "ws-series/ws303": ("ws303", WS["ws303"]),
 "ws-series/ws501": ("ws501", WS["ws50x"]), "ws-series/ws502": ("ws502", WS["ws50x"]), "ws-series/ws503": ("ws503", WS["ws50x"]),
 "ws-series/ws501-eu": ("ws501", WS["ws50x_eu"]), "ws-series/ws501-us": ("ws501", WS["ws50x_eu"]), "ws-series/ws502-eu": ("ws502", WS["ws50x_eu"]),
 "ws-series/ws501-cn": ("ws501", WS["ws50x_cn"]), "ws-series/ws502-cn": ("ws502", WS["ws50x_cn"]), "ws-series/ws503-cn": ("ws503", WS["ws50x_cn"]),
 "ws-series/ws501-v4": ("ws501_v4", WS["ws50x_v4"]), "ws-series/ws502-v4": ("ws502_v4", WS["ws50x_v4"]), "ws-series/ws503-v4": ("ws503_v4", WS["ws50x_v4"]),
 "ws-series/ws513": ("ws52x", WS["ws513"]), "ws-series/ws515": ("ws52x", WS["ws513"]),
 "ws-series/ws523": ("ws52x", WS["ws523"]), "ws-series/ws525": ("ws52x", WS["ws523"]),
 "ws-series/ws513-v3": ("ws52x_v3", WS["ws513_v3"]), "ws-series/ws515-v3": ("ws52x_v3", WS["ws513_v3"]),
 "ws-series/ws558": ("ws558", WS["ws558"]),
 "wt-series/wt101": ("wt101", WT["wt101"]), "wt-series/wt102": ("wt102", WT["wt102"]),
 "wt-series/wt201": ("wt201", WT["wt201"]), "wt-series/wt201-v2": ("wt201_v2", WT["wt201_v2"]), "wt-series/wt211": ("wt201_v2", WT["wt201_v2"]),
 "wt-series/wt301": ("wt30x", [wt30x]), "wt-series/wt302": ("wt30x", [wt30x]),
 "wt-series/wt303": ("wt303", WT["wt303"]), "wt-series/wt304": ("wt303", WT["wt303"]), "wt-series/wt401": ("wt401", WT["wt401"]),
 "cth-series/cth01": ("cth01", CTH), "cth-series/cth01-compress": ("cth01", CTH),
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
        if sample and not folder.endswith(("wt301", "wt302")):    # their codec sample is a WT201 frame
            payloads.append(sample.lower())
    for _ in range(200):
        sel = random.sample(chans, random.randint(1, len(chans)))
        payloads.append(b"".join(c() if callable(c) else bytes(c[:2])+CH[c]() for c in sel).hex())
    inp = HERE / "_in.json"; json.dump(payloads, open(inp, "w"))
    ref = json.loads(subprocess.check_output(["node", str(HERE / "run_official_decoder.js"), str(dfile), str(inp)]))
    fn = getattr(dec, f"decode_{kind}")
    errors = sum(1 for r in ref if "__error" in r)
    if errors > 20:
        print(folder, f"{errors} payloads rejected by the official decoder")
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
        if kind in ("ct10x", "ct30x"):
            r2 = {}
            for k, v in r.items():
                if k.endswith("_sensor_status"): continue
                m = re.fullmatch(r"current_chn(\d)(_total)?(.*)", k)
                if m: k = ("total_current_" + m[1] if m[2] else "current_" + m[1]) + m[3]
                m = re.fullmatch(r"ch(\d)_sumkwh", k)
                if m: k = "energy" if kind == "ct10x" else f"energy_{m[1]}"
                if k.endswith("_alarm") and isinstance(v, dict):
                    flags = [f for f in ("threshold_alarm", "threshold_alarm_release", "over_range_alarm", "over_range_alarm_release")
                             if any(kk.endswith(f) and kk[: -len(f)].endswith("current_") and vv == "yes" for kk, vv in v.items())]
                    if flags: r2[k + "_status"] = ", ".join(flags)
                    continue
                if k == "temperature_alarm": k, v = k + "_status", v.replace("temperature ", "").replace(" ", "_")
                if k == "low_voltage_alarm": v = v.get("alarm_type") == "low voltage alarm"
                r2[k] = v
            r = r2
        if kind == "at101":
            r = {("temperature_alarm_status" if k == "temperature_alarm" else k): v for k, v in r.items()}
            if "wifi" in r:
                r["wifi"] = [{kk: vv for kk, vv in w.items() if kk != "motion_status"} for w in r["wifi"]]
        if kind.startswith("ws"):
            v3 = kind == "ws52x_v3"
            r2 = {}
            for k, v in r.items():
                if k.endswith(("_msgid", "_change", "_collect_error", "_collection_error_report", "_sensor_status", "_celsius", "_fahrenheit")) \
                        or k.startswith(("celsius_", "fahrenheit_")) or k in ("history", "temperature_error"):
                    continue
                if re.fullmatch(r"button_\d+", k): continue
                if k == "button_event": v = v["status"].replace(" ", "_")
                elif k == "pir": v = v == "trigger"
                elif k == "occupancy": v = {"vacant": 0, "occupied": 1}.get(v, v)
                elif k == "tamper_status": k, v = "tamper", v == "uninstalled"
                elif k == "leakage_status": k, v = "leak", {"normal": 0, "leak": 1}.get(v, v)
                elif k == "magnet_status": v = {"close": 0, "open": 1}.get(v, v)
                elif re.fullmatch(r"L[ZAC][IFS]", k): r2["sound_weighting"] = k; k = "sound_level"
                elif re.fullmatch(r"L[ZAC]eq", k): k = "sound_level_eq"
                elif re.fullmatch(r"L[ZAC][IFS]max", k): k = "sound_level_max"
                elif re.fullmatch(r"switch_\d", k) or k == "socket_status" and isinstance(v, str):
                    if v == "unknown": continue
                    k, v = ("switch_1" if k == "socket_status" else k), v == "on"
                elif k == "socket_status": k, v = "switch_1", v["switch_status_1"] == 1
                elif k == "set_socket": k, v = "switch_1", v["status_1"] == 1
                elif k in ("button_status", "button_status_control"):
                    for kk, vv in v.items():
                        m = re.fullmatch(r"button(?:_status)?(\d)", kk)
                        if m: r2[f"switch_{m[1]}"] = vv == "on"
                    continue
                elif k == "function_key_event": v = v == "yes"
                elif k == "power_consumption_enable": v = v == "enable"
                elif k in ("active_power", "electric_power"): k = "power"
                elif k == "power_consumption": k, v = "energy", (v if v3 else v / 1000)
                elif k in ("current", "total_current", "current_rating"): k, v = "current", (v if v3 else v / 1000)
                elif k == "overcurrent_alarm":
                    r2["current"] = v["current"] if v3 else v["current"] / 1000
                    k, v = "overcurrent_alarm", v["status"] in (1, "overcurrent")
                elif k == "device_abnormal_alarm": k, v = "device_fault", v["status"] in (1, "abnormal")
                elif k == "temperature_alarm" and isinstance(v, dict):
                    if "status" in v: k, v = "overtemperature_alarm", v["status"] == "overtemperature"
                    else:
                        r2["temperature"] = v["temperature"]
                        k, v = "temperature_alarm_status", {0: "threshold_alarm_release", 1: "threshold_alarm", 2: "overheat_alarm"}.get(v["alarm_type"], "unknown")
                elif k == "temperature_alarm": k, v = "temperature_alarm_status", v.replace(" ", "_")
                r2[k] = v
            r = r2
        if kind == "cth01":
            r2 = {}
            AB = "abcd"
            def put(key, v):
                if v != "error": r2[key] = v
            for k, v in r.items():
                if k == "temperature": r2[k] = v
                elif k == "voltage_three_phase_imbalcance": put("voltage_unbalance", v)
                elif k in ("thdi", "thdv", "current", "voltage"):
                    pre = {"thdi": "thdi_ct", "thdv": "thdv_l", "current": "current_ct", "voltage": "voltage_l"}[k]
                    for n, item in enumerate(v): put(f"{pre}{n + 1}", item["value"])
                elif k == "power_factor":
                    for g in range(1, 5):
                        if f"group{g}_value" in v and not v.get(f"mask{g}"): put(f"power_factor_{AB[g - 1]}", v[f"group{g}_value"])
                        if f"group{g}" in v and v.get(f"mask{g}"):
                            for c in range(1, 4): put(f"power_factor_ct{3 * (g - 1) + c}", v[f"group{g}"][f"chan{c}"])
                elif re.fullmatch(r"[a-z_]+(power|energy)[12]", k):
                    measure, half = k[:-1], int(k[-1])
                    for g in (1, 2):
                        circuit = (half - 1) * 2 + (g - 1)
                        if v.get(f"mask{g}") == 0 and f"group{g}_value" in v: put(f"{measure}_{AB[circuit]}", v[f"group{g}_value"])
                        if v.get(f"mask{g}") == 1 and f"group{g}" in v:
                            for c in range(1, 4): put(f"{measure}_ct{circuit * 3 + c}", v[f"group{g}"][f"chan{c}"])
                elif k.endswith("_alarm") and isinstance(v, dict):
                    name = k[:-6]
                    info = v.get("info", v)
                    sub = [kk for kk in info if kk != "type"]
                    if not sub: continue
                    if "channel" in v:
                        ch = v["channel"] + 1
                        label = {"current": f"current_ct{ch}", "thdi": f"thdi_ct{ch}", "voltage": f"voltage_l{ch}", "thdv": f"thdv_l{ch}"}[name]
                    else:
                        label = name
                    r2[label + "_alarm_status"] = sub[0]
                elif k == "power_loss_alarm": r2[k] = True
            r = r2
        if kind.startswith("wt"):
            if kind == "wt401":
                r = {(k[len("celsius_"):] if k.startswith("celsius_") else k): v for k, v in r.items()}
            r2 = {}
            alarm_maps = {}
            for k, v in r.items():
                if k.startswith(("fahrenheit_", "celsius_")) or k.endswith("_sensor_status") or k in (
                        "history", "head", "command", "data_length", "type", "raw", "crc", "wires_relay", "enabled_relay",
                        "temperature_control_support_mode", "temperature_control_support_status", "heating_date", "temperature_source_value", "device_status"):
                    continue
                if k == "ambient_temperature": k = "temperature"
                elif k in ("tamper_status",): k, v = "tamper", v == "uninstalled"
                elif k == "window_detection": k, v = "window_open", v == "open"
                elif k == "freeze_protection": v = v == "triggered"
                elif k in ("motor_calibration_result",): pass
                elif k == "motor_calibration_result_report": k, v = "motor_calibration_result", {0: "uncalibrated", 1: "success", 2: "fail: out of range", 3: "fail: temperature control disabled", 4: "fail: uninstalled"}[v["status"]]
                elif k == "motor_total_stroke": k = "motor_stroke"
                elif k in ("valve_opening_degree", "temperature_control_valve_status"): k = "valve_opening"
                elif k == "target_valve_opening_degree": k = "target_valve_opening"
                elif k == "low_battery_alarm": k, v = "battery_low_alarm", True
                elif k == "temperature_alarm" and isinstance(v, dict):
                    sub = [kk for kk in v if kk != "type"]
                    if sub and isinstance(v[sub[0]], dict) and "temperature" in v[sub[0]]: k, v = "temperature_alarm_status", sub[0]
                    else: continue
                elif k == "temperature_alarm": k, v = "temperature_alarm_status", v.replace(" ", "_")
                elif k in ("humidity_alarm", "target_temperature_alarm", "anti_freeze_protection_alarm", "mandatory_heating_alarm",
                           "auto_away_report", "window_opening_alarm", "periodic_reporting", "ble_event", "power_bus_event",
                           "key_event", "battery_event", "source_alarm", "target_temperature_range_alarm", "lorawan_configuration_settings"):
                    if k == "anti_freeze_protection_alarm" and len(v) > 1: r2["freeze_protection"] = "trigger" in v
                    if k == "mandatory_heating_alarm" and len(v) > 1: r2["mandatory_heating"] = "enter" in v
                    if k == "window_opening_alarm" and len(v) > 1: r2["window_open"] = list(v.values())[1]["state"] == 1
                    if k == "power_bus_event": r2["power_bus_disconnected"] = v["type"] == 1
                    continue
                elif k == "current_temperature_control_mode": r2["temperature_control_status"] = v["status"]; k, v = "temperature_control_mode", v["mode"]
                elif k == "fan_mode_setting": r2["fan_status"] = v["status"]; k, v = "fan_mode", {"always on": "on"}.get(v["mode"], v["mode"])
                elif k == "temperature_control_info":
                    r2["temperature_control_status"] = {0: "standby", 1: "heat", 2: "cool"}.get(v["status"], "unknown")
                    k, v = "temperature_control_mode", {0: "ventilation", 1: "heat", 2: "cool"}.get(v["mode"], "unknown")
                elif k == "fan_control_info":
                    r2["fan_status"] = {0: "off", 1: "low", 2: "medium", 3: "high"}.get(v["status"], "unknown")
                    k, v = "fan_mode", {0: "auto", 1: "low", 2: "medium", 3: "high"}.get(v["mode"], "unknown")
                elif k == "fan_control_mode": k, v = "fan_mode", {0: "auto", 1: "low", 2: "medium", 3: "high"}.get(v, "unknown")
                elif k == "temperature_control_mode" and kind == "wt303": v = {0: "ventilation", 1: "heat", 2: "cool"}.get(v, "unknown")
                elif k == "relay_status":
                    for name, src in (("relay_low", "low_status"), ("relay_medium", "mid_status"), ("relay_high", "high_status"), ("valve_1", "valve_1_status"), ("valve_2", "valve_2_status")):
                        r2[name] = v[src] == 1
                    continue
                elif k == "execution_plan_id": k, v = "execution_plan", "not executed" if v == 255 else f"schedule {v + 1}"
                elif k == "data_source": v = {0: "internal", 1: "external NTC", 2: "LoRaWAN", 3: "D2D"}.get(v, "unknown")
                elif k in ("system_status", "thermostat_status"): k, v = "system_status", v in ("on", 1)
                elif k == "btn_lock_enable": k, v = "button_lock", v == "enable"
                elif k == "card_mode": k, v = "card_inserted", v == "insert"
                elif k == "device_status": v = {0: "off", 1: "on"}.get(v, v)
                elif k == "curr_temperature_humidity_source": k, v = "temperature_source", v.lower()
                elif k in ("target_temperature1", "target_temperature2"): k = "target_temperature" if k.endswith("1") else "target_temperature_2"
                elif k == "temperature_mode": k, v = "temperature_control_mode", {0: "heat", 1: "em heat", 2: "cool", 3: "auto", 4: "dehumidify", 5: "ventilation", 10: "off", 11: "none"}.get(v, "unknown")
                elif k == "fan_mode" and kind == "wt401": v = {0: "auto", 1: "circulate", 2: "on", 3: "low", 4: "medium", 5: "high", 10: "off", 11: "none"}.get(v, "unknown")
                elif k == "pir_status": v = {0: "vacant", 1: "occupied", 2: "night occupied"}.get(v, "unknown")
                elif k == "plan_type": pass
                elif k == "temperature_control_mode" and kind == "wt201": v = v.replace("_", " ")
                elif k == "temperature_control_status": v = v.replace("_", " ")
                elif k == "mode": pass
                r2[k] = v
            r = r2
        if kind.startswith("gs"):
            r2 = {}
            for k, v in r.items():
                if k.endswith(("_sensor_status", "_calibration_result", "_celsius", "_fahrenheit")) or k.startswith(("tvoc_raw", "celsius_", "fahrenheit_")):
                    continue
                if k in ("sensor_id", "version", "protocol", "type", "device_status", "random_key"):
                    continue
                if kind == "gs101":
                    if k == "gas_status": k, v = "gas_alarm", v == "alarm"
                    elif k == "alarm": k, v = "device_alarm", v.replace(" ", "_")
                    elif v in ("on", "off"): v = v == "on"
                if kind == "gs524n" and k == "event": v = v.replace(" ", "_")
                if kind == "gs601":
                    if isinstance(v, dict):
                        if k == "tamper_status_alarm":
                            r2["tamper_status"] = "trigger" in v
                            continue
                        sub = [kk for kk in v if kk != "type"]
                        if sub: r2[k + "_status"] = sub[0]
                        continue
                    if k == "occupancy_status": k = "occupancy"
                    if k in ("tamper_status", "buzzer"): v = v == 1
                r2[k] = v
            r = r2
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
            elif isinstance(v,str) and v in STR and not kind.startswith("wt") and not ((kind.startswith(("uc", "gs", "at", "ws", "wt")) or kind == "em400") and v == "normal"): v = STR[v]
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

# ---- downlinks: our switch commands vs Milesight's official encoders --------------------------
ENC = [  # folder, encoder kind, gangs, payload builder(channel, on)
 ("ws-series/ws501", "ff29", 1, lambda c, on: {f"switch_{c}": "on" if on else "off"}),
 ("ws-series/ws503", "ff29", 3, lambda c, on: {f"switch_{c}": "on" if on else "off"}),
 ("ws-series/ws502-eu", "0829", 2, lambda c, on: {f"switch_{c}": "on" if on else "off"}),
 ("ws-series/ws501-us", "0829", 1, lambda c, on: {f"switch_{c}": "on" if on else "off"}),
 ("ws-series/ws503-cn", "0829", 3, lambda c, on: {f"switch_{c}": "on" if on else "off"}),
 ("ws-series/ws503-v4", "ff29", 3, lambda c, on: {"button_status_control": {f"button_status{c}": "on" if on else "off", f"button_status{c}_change": "yes"}}),
 ("ws-series/ws513", "0870", 1, lambda c, on: {"socket_status": "on" if on else "off"}),
 ("ws-series/ws525", "0870", 1, lambda c, on: {"socket_status": "on" if on else "off"}),
 ("ws-series/ws515-v3", "ff29", 1, lambda c, on: {"set_socket": {"status_1": int(on)}}),
 ("ws-series/ws558", "0831", 8, lambda c, on: {f"switch_{c}": "on" if on else "off"}),
]
for folder, ekind, gangs, build in ENC:
    cases = [(c, on) for c in range(1, gangs + 1) for on in (True, False)]
    inp = HERE / "_in.json"; json.dump([build(c, on) for c, on in cases], open(inp, "w"))
    ref = json.loads(subprocess.check_output(["node", str(HERE / "run_official_encoder.js"),
                                              str(next((MS / folder).glob("*-encoder.js"))), str(inp)]))
    for (c, on), r in zip(cases, ref):
        total += 1
        mine = dec.encode_ws_switch(ekind, c, on).hex()
        if mine != r:
            bad += 1; print(folder, "downlink", c, on, mine, r)
inp.unlink(missing_ok=True)

# ---- WT downlinks: (folder, our encoder kind, our call, official payload) ------------------------
WT_ENC = [
 ("wt-series/wt101", "wt101", ("target", 21), {"target_temperature": 21, "temperature_tolerance": 1}),
 ("wt-series/wt101", "wt101", ("power", True), {"temperature_control": {"enable": "enable"}}),
 ("wt-series/wt101", "wt101", ("power", False), {"temperature_control": {"enable": "disable"}}),
 ("wt-series/wt102", "wt102", ("target", 21.5), {"set_target_temperature": {"value": 21.5}}),
 ("wt-series/wt102", "wt102", ("power", True), {"temp_control": {"enable": 1}}),
 ("wt-series/wt102", "wt102", ("power", False), {"temp_control": {"enable": 0}}),
 ("wt-series/wt201", "wt201", ("target", 21.5, "heat"), {"temperature_control_mode": "heat", "target_temperature": 21.5}),
 ("wt-series/wt201", "wt201", ("target", 24, "cool"), {"temperature_control_mode": "cool", "target_temperature": 24}),
 ("wt-series/wt201", "wt201", ("mode", "auto"), {"temperature_control_mode": "auto"}),
 ("wt-series/wt201", "wt201", ("power", True), {"temperature_control_enable": "enable"}),
 ("wt-series/wt201", "wt201", ("fan", "circulate"), {"fan_mode": "circulate"}),
 ("wt-series/wt201-v2", "wt201v2", ("target", 21.5, "heat"), {"temperature_control_mode": "heat", "target_temperature": 21.5}),
 ("wt-series/wt211", "wt201v2", ("target", 19, "auto"), {"temperature_control_mode": "auto", "target_temperature": 19}),
 ("wt-series/wt201-v2", "wt201v2", ("mode", "cool", None, 24, True), {"system_status": "on", "temperature_control_mode": "cool", "target_temperature": 24}),
 ("wt-series/wt201-v2", "wt201v2", ("power", False, "em heat", 20.5), {"system_status": "off", "temperature_control_mode": "em heat", "target_temperature": 20.5}),
 ("wt-series/wt201-v2", "wt201v2", ("fan", "on"), {"fan_mode_setting": {"mode": "always on"}}),
 ("wt-series/wt201-v2", "wt201v2", ("fan", "auto"), {"fan_mode_setting": {"mode": "auto"}}),
 ("wt-series/wt301", "wt30x", ("target", 21.5), {"target_temperature": 21.5}),
 ("wt-series/wt301", "wt30x", ("mode", "heat"), {"mode": "heat"}),
 ("wt-series/wt302", "wt30x", ("power", False), {"thermostat_status": "off"}),
 ("wt-series/wt302", "wt30x", ("fan", "low"), {"fan_speed": "low"}),
 ("wt-series/wt303", "wt303", ("target", 21.5, "heat"), {"heating_target_temperature": 21.5}),
 ("wt-series/wt304", "wt303", ("target", 23.5, "cool"), {"cooling_target_temperature": 23.5}),
 ("wt-series/wt303", "wt303", ("mode", "ventilation"), {"temperature_control_mode": 0}),
 ("wt-series/wt304", "wt303", ("power", True), {"system_status": 1}),
 ("wt-series/wt303", "wt303", ("fan", "medium"), {"fan_control_mode": 2}),
 ("wt-series/wt401", "wt401", ("target", 21.5, "heat"), {"target_temperature_settings": {"heat": 21.5}}),
 ("wt-series/wt401", "wt401", ("target", 24, "cool"), {"target_temperature_settings": {"cool": 24}}),
 ("wt-series/wt401", "wt401", ("target", 22.5, "auto"), {"target_temperature_settings": {"auto": 22.5}}),
 ("wt-series/wt401", "wt401", ("mode", "cool"), {"temperature_control_mode": {"mode": 2}}),
 ("wt-series/wt401", "wt401", ("power", False), {"system_status": 0}),
 ("wt-series/wt401", "wt401", ("fan", "high"), {"fan_control_mode": 5}),
]
for folder, ekind, call, payload in WT_ENC:
    inp = HERE / "_in.json"; json.dump([payload], open(inp, "w"))
    ref = json.loads(subprocess.check_output(["node", str(HERE / "run_official_encoder.js"),
                                              str(next((MS / folder).glob("*-encoder.js"))), str(inp)]))[0]
    action, value, *rest = call
    kw = {}
    if rest: kw["mode"] = rest[0]
    if len(rest) > 1: kw["target"] = rest[1]
    if len(rest) > 2: kw["on"] = rest[2]
    mine = dec.encode_wt(ekind, action, value, **kw).hex()
    total += 1
    if mine != ref:
        bad += 1; print(folder, "downlink", call, mine, ref)
inp.unlink(missing_ok=True)
print(f"{total} payloads checked, {bad} mismatches")
sys.exit(1 if bad else 0)
