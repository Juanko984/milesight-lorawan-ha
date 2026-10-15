"""Verify g1.json templates against the official Milesight encoders (via node)."""
import os, pathlib, copy, json, os, random, struct, subprocess, tempfile
RUNNER = str(pathlib.Path(__file__).resolve().parents[1] / "run_official_encoder.js")
SD = os.environ.get("SENSOR_DECODERS", "SensorDecoders")
spec = json.load(open(str(pathlib.Path(__file__).resolve().parent / "dl_g1.json")))
FMT = {"u8": "<B", "u16le": "<H", "u16be": ">H", "u32le": "<I", "i16le": "<h", "i32le": "<i"}

def tmpl(s, v):
    return s["prefix"] + struct.pack(FMT[s["value"]], round(v * s["scale"])).hex() + s.get("suffix", "")

def subst(p, old, new):
    if isinstance(p, dict): return {k: subst(x, old, new) for k, x in p.items()}
    return new if p == old else p

random.seed(1)
total = bad = 0
for folder, cmds in spec.items():
    enc = f"{SD}/{folder}/{folder.split('/')[1]}-encoder.js"
    cases = []  # (label, payload, expected)
    def walk(name, s):
        if "hex" in s: cases.append((name, s["payload"], s["hex"]))
        for k, x in s.items():
            if isinstance(x, dict) and k not in ("payload",): walk(f"{name}.{k}", x)
    def _leaves(p):
        for x in (p.values() if isinstance(p, dict) else [p]):
            yield from (_leaves(x) if isinstance(x, dict) else [x])
    for name, s in cmds.items():
        if not isinstance(s, dict): continue
        if "prefix" in s:
            # value leaf in the example payload = largest numeric leaf (unit flags are 0/1)
            leaf = max(_leaves(s["payload"]))
            vals = [s["min"], s["max"]] + [random.randint(s["min"], s["max"]) for _ in range(5)]
            for v in vals:
                cases.append((f"{name}={v}", subst(s["payload"], leaf, round(v * s["scale"])), tmpl(s, v)))
        else:
            walk(name, s)
    if not cases: print(f"{folder}: no commands"); continue
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
        json.dump([c[1] for c in cases], t)
    got = json.loads(subprocess.run(["node", RUNNER, enc, t.name], capture_output=True, text=True, check=True).stdout)
    os.unlink(t.name)
    for (label, p, exp), g in zip(cases, got):
        total += 1
        if g != exp:
            bad += 1; print(f"MISMATCH {folder} {label}: template {exp} node {g} payload {p}")
    print(f"{folder}: {len(cases)} cases ok" if all(g == c[2] for c, g in zip(cases, got)) else f"{folder}: FAIL")
print(f"TOTAL {total} cases, {bad} mismatches")
raise SystemExit(1 if bad else 0)
