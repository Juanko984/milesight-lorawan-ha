#!/usr/bin/env python3
"""Verify g2.json templates against the official Milesight encoders (node runner)."""
import os, pathlib, copy, json, os, random, struct, subprocess, sys, tempfile

SPECS = str(pathlib.Path(__file__).resolve().parent / "dl_g2.json")
SD = os.environ.get("SENSOR_DECODERS", "SensorDecoders")
RUNNER = str(pathlib.Path(__file__).resolve().parents[1] / "run_official_encoder.js")
FMT = {"u8": "<B", "u16le": "<H", "u16be": ">H", "u32le": "<I", "i16le": "<h", "i32le": "<i"}
random.seed(int(os.environ.get("SEED", "1")))


def iter_specs(node, path=()):
    if isinstance(node, dict):
        if "hex" in node or "prefix" in node:
            yield path, node
            return
        for k, v in node.items():
            if not k.startswith("_"):
                yield from iter_specs(v, path + (k,))


def find_path(obj, target, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            r = find_path(v, target, path + (k,))
            if r is not None:
                return r
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and obj == target:
        return path
    return None


def set_path(obj, path, value):
    for k in path[:-1]:
        obj = obj[k]
    obj[path[-1]] = value



# --- use the integration's own encoder, so this check validates it -----------------------------
import importlib.util as _ilu, sys as _sys, types as _types, pathlib as _pl
_PKG = _pl.Path(__file__).resolve().parents[2] / "custom_components" / "milesight_lorawan"
if "mlw.decoders" not in _sys.modules:
    _p = _types.ModuleType("mlw"); _p.__path__ = [str(_PKG)]; _sys.modules["mlw"] = _p
    _s = _ilu.spec_from_file_location("mlw.decoders", _PKG / "decoders.py")
    _m = _ilu.module_from_spec(_s); _sys.modules["mlw.decoders"] = _m; _s.loader.exec_module(_m)
_dec = _sys.modules["mlw.decoders"]


def template(spec, v):
    return _dec.encode_template(spec, v).hex()

def run(encoder, payloads):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payloads, f)
        name = f.name
    try:
        res = subprocess.run(["node", RUNNER, encoder, name], capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    finally:
        os.unlink(name)


def main():
    specs = json.load(open(SPECS))
    checks = mism = 0
    for folder, cmds in specs.items():
        model = os.path.basename(folder)
        enc = os.path.join(SD, folder, model + "-encoder.js")
        cases = []  # (label, payload, expected)
        for path, spec in iter_specs(cmds):
            label = folder + ":" + ".".join(path)
            if "hex" in spec:
                cases.append((label, spec["payload"], spec["hex"]))
                continue
            ex = spec["payload"]
            # locate the payload leaf holding the encoded value: run the example, decode raw int
            out = run(enc, [ex])[0]
            pre, suf = spec["prefix"], spec.get("suffix", "")
            if not (out.startswith(pre) and out.endswith(suf)):
                print("EXAMPLE MISMATCH", label, out); mism += 1; continue
            raw_ex = struct.unpack(FMT[spec["value"]], bytes.fromhex(out[len(pre):len(out) - len(suf)]))[0]
            if sum(1 for n in _nums(ex) if n == raw_ex) != 1:
                print("AMBIGUOUS value in payload", label); mism += 1; continue
            leaf = find_path(ex, raw_ex)
            for _ in range(5):
                if "values" in spec:
                    v = random.choice(spec["values"])
                else:
                    v = random.randint(int(spec["min"]), int(spec["max"]))
                raw = round(v * spec["scale"])
                pl = copy.deepcopy(ex)
                set_path(pl, leaf, raw)
                cases.append((label + "=%s" % v, pl, template(spec, v)))
        if not cases:
            continue
        got = run(enc, [c[1] for c in cases])
        for (label, pl, exp), g in zip(cases, got):
            checks += 1
            if g != exp:
                mism += 1
                print("MISMATCH", label, "payload", json.dumps(pl), "template", exp, "node", g)
    print("checks: %d  mismatches: %d" % (checks, mism))
    return 1 if mism else 0


def _nums(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _nums(v)
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        yield o


if __name__ == "__main__":
    sys.exit(main())
