#!/usr/bin/env python3
"""Verify g23.json settings specs (groups g2 + g3) against the official Milesight encoders (node runner).

Template semantics: bytes = prefix + for each field: const hex, or pack(value_fmt, (v << shift) | or)
with v = map[name] (map fields) or round(user_value * scale); + suffix.
Field "path" = location of the field in the JS payload; "raw": true -> encoder wants the numeric map value
instead of the map name.
"""
import copy, json, os, random, subprocess, sys, tempfile

SD = __import__("os").environ.get("SENSOR_DECODERS", "SensorDecoders")
RUNNER = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "run_official_encoder.js")
SPEC = json.load(open(str(__import__("pathlib").Path(__file__).resolve().parent / "set_g23.json")))
FMT = {"u8": (1, False), "u16le": (2, False), "u32le": (4, False), "i16le": (2, True), "i32le": (4, True),
       "u16be": (2, False)}
N_RANDOM = 8


def pack(fmt, v):
    n, signed = FMT[fmt]
    return int(v).to_bytes(n, "big" if fmt.endswith("be") else "little", signed=signed).hex()



# --- use the integration's own encoder, so this check validates it -----------------------------
import importlib.util as _ilu, sys as _sys, types as _types, pathlib as _pl
_PKG = _pl.Path(__file__).resolve().parents[2] / "custom_components" / "milesight_lorawan"
if "mlw.decoders" not in _sys.modules:
    _p = _types.ModuleType("mlw"); _p.__path__ = [str(_PKG)]; _sys.modules["mlw"] = _p
    _s = _ilu.spec_from_file_location("mlw.decoders", _PKG / "decoders.py")
    _m = _ilu.module_from_spec(_s); _sys.modules["mlw.decoders"] = _m; _s.loader.exec_module(_m)
_dec = _sys.modules["mlw.decoders"]


def template(spec, values):
    return _dec.encode_fields(spec, values).hex()

def set_path(p, path, v):
    d = p
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = v


def rand_value(fld):
    if "map" in fld:
        return random.choice(list(fld["map"]))
    scale = fld.get("scale", 1)
    lo, hi = int(round(fld["min"] * scale)), int(round(fld["max"] * scale))
    while True:  # pick values whose value*scale is exact in float (encoder truncates instead of rounding)
        k = random.randint(lo, hi)
        v = k / scale if scale != 1 else k
        if v * scale == k:
            return int(v) if float(v).is_integer() else v


def build_cases(spec):
    cases = []
    vary = [x for x in spec["fields"] if "const" not in x]
    combos = []
    # extremes first, then random combos
    for edge in ("min", "max"):
        c = {}
        for fld in vary:
            c[fld["name"]] = list(fld["map"])[0 if edge == "min" else -1] if "map" in fld else fld[edge]
        combos.append(c)
    combos += [{fld["name"]: rand_value(fld) for fld in vary} for _ in range(N_RANDOM)]
    for c in combos:
        p = copy.deepcopy(spec["payload"])
        for fld in vary:
            v = c[fld["name"]]
            set_path(p, fld["path"], fld["map"][v] if ("map" in fld and fld.get("raw")) else v)
        cases.append((json.dumps(c, ensure_ascii=False), p, template(spec, c)))
    return cases


def run(enc, payloads):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payloads, f)
    try:
        out = subprocess.run(["node", RUNNER, enc, f.name], capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(f.name)
    return json.loads(out)


def main():
    random.seed(23)
    total = mism = 0
    for folder, cmds in SPEC.items():
        model = folder.split("/")[1]
        enc = os.path.join(SD, folder, model + "-encoder.js")
        cases = []
        for name, spec in cmds.items():
            if name.startswith("_") or not isinstance(spec, dict):
                continue
            if "on" in spec and "off" in spec:
                for st in ("on", "off"):
                    cases.append((f"{name}.{st}", spec[st]["payload"], spec[st]["hex"]))
            elif "fields" in spec:
                cases += [(f"{name} {lbl}", p, exp) for lbl, p, exp in build_cases(spec)]
            else:
                raise SystemExit(f"unknown spec {folder} {name}")
        if not cases:
            print(f"{folder}: no settings")
            continue
        got = run(enc, [c[1] for c in cases])
        bad = 0
        for (label, p, exp), g in zip(cases, got):
            total += 1
            if g != exp:
                bad += 1
                print(f"  MISMATCH {folder} {label}: expected {exp} got {g} payload={json.dumps(p)}")
        mism += bad
        print(f"{folder}: {len(cases)} cases, {bad} mismatches")
    print(f"TOTAL {total} cases, {mism} mismatches")
    return 1 if mism else 0


if __name__ == "__main__":
    sys.exit(main())
