#!/usr/bin/env python3
"""Verify g3.json templates against the official Milesight encoders (node runner)."""
import os, pathlib, copy, json, os, random, subprocess, sys, tempfile

SD = os.environ.get("SENSOR_DECODERS", "SensorDecoders")
RUNNER = str(pathlib.Path(__file__).resolve().parents[1] / "run_official_encoder.js")
SPEC = json.load(open(str(pathlib.Path(__file__).resolve().parent / "dl_g3.json")))
FMT = {"u8": (1, "little", False), "u16le": (2, "little", False), "u16be": (2, "big", False),
       "u32le": (4, "little", False), "i16le": (2, "little", True), "i32le": (4, "little", True)}


def template(spec, v):
    n, order, signed = FMT[spec["value"]]
    return spec["prefix"] + int(round(v * spec["scale"])).to_bytes(n, order, signed=signed).hex() + spec.get("suffix", "")


def set_path(payload, path, v):
    p = copy.deepcopy(payload)
    d = p
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = v
    return p


def run(enc, payloads):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payloads, f)
    try:
        out = subprocess.run(["node", RUNNER, enc, f.name], capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(f.name)
    return json.loads(out)


def main():
    random.seed(1)
    total = mism = 0
    for folder, cmds in SPEC.items():
        model = folder.split("/")[1]
        enc = os.path.join(SD, folder, model + "-encoder.js")
        cases = []  # (label, payload, expected)
        for name, spec in cmds.items():
            if not isinstance(spec, dict):
                continue
            if "on" in spec and "off" in spec:
                for st in ("on", "off"):
                    cases.append((f"{name}.{st}", spec[st]["payload"], spec[st]["hex"]))
            elif "hex" in spec:
                cases.append((name, spec["payload"], spec["hex"]))
            elif "prefix" in spec:
                lo, hi = spec["min"], spec["max"]
                vals = [lo, hi] + [random.randint(lo, hi) for _ in range(5)]
                for v in vals:
                    cases.append((f"{name}={v}", set_path(spec["payload"], spec["value_path"], v), template(spec, v)))
        if not cases:
            print(f"{folder}: no commands")
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
