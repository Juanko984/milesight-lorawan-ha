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
}
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
}
STR = {"open":1,"close":0,"leak":1,"normal":0,"trigger":1,"idle":0,"on":1,"off":0,"high":1,"low":0}
RENAME = {"magnet_status":"magnet_status","leakage_status":"input_05","gpio":"input_05","pulse":"pulse_count","buzzer_status":"buzzer"}
SKIP = {"history"}
total=bad=0
for folder,(kind,chans) in MODELS.items():
    d = MS/folder; dfile = next(d.glob("*-decoder.js"))
    codec = next(d.glob("*-codec.json"), None)
    payloads = []
    if codec:
        payloads.append(json.load(open(codec))["bytes"].lower())
    for _ in range(200):
        sel = random.sample(chans, random.randint(1, len(chans)))
        payloads.append(b"".join(bytes(c)+CH[c]() for c in sel).hex())
    inp = HERE / "_in.json"; json.dump(payloads, open(inp, "w"))
    ref = json.loads(subprocess.check_output(["node", str(HERE / "run_official_decoder.js"), str(dfile), str(inp)]))
    fn = getattr(dec, f"decode_{kind}")
    for h, r in zip(payloads, ref):
        mine = fn(bytes.fromhex(h)); total += 1
        exp = {}
        for k,v in r.items():
            if k in SKIP: continue
            k2 = RENAME.get(k,k)
            if k == "tvoc" and kind=="am300":   # official uses one key for both units
                k2 = "tvoc_iaq" if "087d" in h else "tvoc"
            if isinstance(v,str) and v in STR: v = STR[v]
            exp[k2] = v
        diffs = {k:(exp[k], mine.get(k)) for k in exp if not (k in mine and (abs(mine[k]-exp[k])<1e-3 if isinstance(exp[k],(int,float)) and isinstance(mine.get(k),(int,float)) else mine[k]==exp[k]))}
        if diffs:
            bad += 1
            if bad <= 8: print(folder, h, diffs)
inp.unlink(missing_ok=True)
print(f"{total} payloads checked, {bad} mismatches")
sys.exit(1 if bad else 0)
