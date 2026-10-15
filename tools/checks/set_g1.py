"""Verify /tmp/claude-0/work/set/g1.json setting templates against the official Milesight encoders (node).

Template semantics: bytes = prefix + each field in order + suffix, where a field is
  {"const": hex}                       -> literal bytes
  {"map": {...}}                       -> map[user_option] packed as "value"
  {"from": <field>, "map": {...}}      -> map[user[<field>]] packed as "value" (derived byte, e.g. enable flag)
  {"scale": s, ...}                    -> round(user_value * s) packed as "value"
On/off specs: {"on": {"hex"}, "off": {"hex"}}.
"_js" (per setting) only tells this script how to build the equivalent JS payload for the official encoder.
"""
import copy, json, os, random, struct, subprocess, tempfile

RUNNER = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "run_official_encoder.js")
SD = __import__("os").environ.get("SENSOR_DECODERS", "SensorDecoders")
SPEC = json.load(open(str(__import__("pathlib").Path(__file__).resolve().parent / "set_g1.json")))
FMT = {"u8": "<B", "u16le": "<H", "u16be": ">H", "u32le": "<I", "i16le": "<h", "i32le": "<i"}
COND = ["disable", "below", "above", "between", "outside"]
N = 8  # random combinations per multi-field setting


def pack(vtype, n):
    return struct.pack(FMT[vtype], n).hex()



# --- use the integration's own encoder, so this check validates it -----------------------------
import importlib.util as _ilu, sys as _sys, types as _types, pathlib as _pl
_PKG = _pl.Path(__file__).resolve().parents[2] / "custom_components" / "milesight_lorawan"
if "mlw.decoders" not in _sys.modules:
    _p = _types.ModuleType("mlw"); _p.__path__ = [str(_PKG)]; _sys.modules["mlw"] = _p
    _s = _ilu.spec_from_file_location("mlw.decoders", _PKG / "decoders.py")
    _m = _ilu.module_from_spec(_s); _sys.modules["mlw.decoders"] = _m; _s.loader.exec_module(_m)
_dec = _sys.modules["mlw.decoders"]


def template(spec, user):
    return _dec.encode_fields(spec, user).hex()

def setpath(obj, path, val):
    keys = path.split(".")
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = val


def rand_user(spec):
    js = spec["_js"]
    u = {}
    for f in spec["fields"]:
        if "const" in f or "from" in f:
            continue
        if "map" in f:
            u[f["name"]] = random.choice(list(f["map"]))
        else:
            step = js.get("step", {}).get(f["name"], 1)
            k = random.randint(round(f["min"] / step), round(f["max"] / step))
            v = k * step
            u[f["name"]] = round(v, 6) if step != 1 else int(v)
    if "order" in js:  # e.g. CO2 level1 <= level2
        vals = sorted(u[n] for n in js["order"])
        for n, v in zip(js["order"], vals):
            u[n] = v
    return u


def js_payload(spec, user):
    js = spec["_js"]
    root = {} if "array" in js else copy.deepcopy(spec["payload"])
    item = {} if "array" in js else root
    for path, v in js.get("fixed", {}).items():
        setpath(item, path, v)
    fmap = {f["name"]: f for f in spec["fields"] if "name" in f}
    for name, path in js["fields"].items():
        f, v = fmap[name], user[name]
        if "map" in f:
            if js.get("numeric_condition") and name == "condition":
                v = COND.index(v)
            elif js.get("numeric_maps"):
                v = f["map"][v]
        setpath(item, path, v)
    for path, d in js.get("derived", {}).items():
        setpath(item, path, d["map"][user[d["from"]]])
    if "array" in js:
        root = {js["array"]: [item]}
    return root


def run(folder, payloads):
    enc = f"{SD}/{folder}/{folder.split('/')[1]}-encoder.js"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
        json.dump(payloads, t)
    try:
        r = subprocess.run(["node", RUNNER, enc, t.name], capture_output=True, text=True, check=True)
    finally:
        os.unlink(t.name)
    return json.loads(r.stdout)


random.seed(42)
total = bad = 0
for folder, settings in SPEC.items():
    cases = []  # (label, payload, expected)
    for name, s in settings.items():
        if name.startswith("_"):
            continue
        if "on" in s:
            for st in ("on", "off"):
                cases.append((f"{name}.{st}", s[st]["payload"], s[st]["hex"]))
        else:
            cases.append((f"{name}[example]", s["payload"], None))  # example payload must encode w/o error
            for _ in range(N):
                u = rand_user(s)
                cases.append((f"{name}{u}", js_payload(s, u), template(s, u)))
    if not cases:
        print(f"{folder}: no settings")
        continue
    got = run(folder, [c[1] for c in cases])
    fails = 0
    for (label, p, exp), g in zip(cases, got):
        total += 1
        ok = (not g.startswith("ERR")) if exp is None else g == exp
        if not ok:
            fails += 1
            print(f"  MISMATCH {folder} {label}: template {exp} node {g} payload {json.dumps(p)}")
    bad += fails
    print(f"{folder}: {len(cases)} cases {'ok' if not fails else f'{fails} FAIL'}")
print(f"TOTAL {total} cases, {bad} mismatches")
raise SystemExit(1 if bad else 0)
