#!/usr/bin/env python3
"""Verify the integration's DS3604 display encoders (encode_ds3604_content / encode_ds3604) against
Milesight's official ds3604-encoder.js (node runner)."""
import json, os, random, subprocess, sys, tempfile
import importlib.util as _ilu, pathlib as _pl, types as _types

SD = os.environ.get("SENSOR_DECODERS", "SensorDecoders")
RUNNER = str(_pl.Path(__file__).resolve().parents[1] / "run_official_encoder.js")
_PKG = _pl.Path(__file__).resolve().parents[2] / "custom_components" / "milesight_lorawan"
if "mlw.decoders" not in sys.modules:
    _p = _types.ModuleType("mlw"); _p.__path__ = [str(_PKG)]; sys.modules["mlw"] = _p
    _s = _ilu.spec_from_file_location("mlw.decoders", _PKG / "decoders.py")
    _m = _ilu.module_from_spec(_s); sys.modules["mlw.decoders"] = _m; _s.loader.exec_module(_m)
dec = sys.modules["mlw.decoders"]

R = random.Random(3604)
TEXTS = ["", "Hello", "Room 1.04 – Free", "Größe Ä Ö Ü ß", "Next: 14:00 Board meeting", "日本語テキスト", "€ 12,50",
         "https://www.milesight.com", "Occupied until 15:30", "Ελληνικά", "x" * 120]
BLOCKS = [f"text_{n}" for n in range(1, 11)] + ["qrcode"]
VIS = BLOCKS + ["image_1", "image_2", "battery_status", "connect_status"]

cases = []  # (label, js_payload, our_hex)
for _ in range(300):
    tpl = R.choice([1, 2])
    blocks = R.sample(BLOCKS, R.randint(1, 4))
    content = {b: R.choice(TEXTS) for b in blocks}
    ordered = [b for b in BLOCKS if b in content]           # JS emits blocks in its own key order
    ours = b"".join(dec.encode_ds3604_content(tpl, b, content[b]) for b in ordered)
    cases.append((f"template_{tpl} {content}", {f"template_{tpl}": content}, ours.hex()))
for t in (1, 2):
    cases.append((f"template {t}", {"current_template_id": t}, dec.encode_ds3604("template", t).hex()))
for js, (cmd, val) in (({"refresh_display": "yes"}, ("refresh", None)), ({"beep": "yes"}, ("beep", None)),
                       ({"report_current_display": "yes"}, ("report_display", None)),
                       ({"buzzer_enable": "enable"}, ("buzzer", True)), ({"buzzer_enable": "disable"}, ("buzzer", False)),
                       ({"button_enable": "enable"}, ("button", True)), ({"button_enable": "disable"}, ("button", False)),
                       ({"switch_template_button_enable": "enable"}, ("template_button", True)),
                       ({"switch_template_button_enable": "disable"}, ("template_button", False))):
    cases.append((cmd, js, dec.encode_ds3604(cmd, val).hex()))
for _ in range(100):
    sel = {k: R.choice([True, False]) for k in R.sample(VIS, R.randint(1, len(VIS)))}
    cases.append((f"visible {sel}", {"block_visible": {k: "show" if v else "hide" for k, v in sel.items()}},
                  dec.encode_ds3604("visible", sel).hex()))

with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    json.dump([c[1] for c in cases], f)
try:
    got = json.loads(subprocess.run(["node", RUNNER, os.path.join(SD, "ds-series/ds3604/ds3604-encoder.js"), f.name],
                                    capture_output=True, text=True, check=True).stdout)
finally:
    os.unlink(f.name)
bad = 0
for (label, js, exp), g in zip(cases, got):
    if g != exp:
        bad += 1
        print(f"  MISMATCH {label}: ours {exp} official {g}")
# packing: frames are never split and each downlink stays within the limit
frames = [dec.encode_ds3604_content(1, b, R.choice(TEXTS[:9])) for b in BLOCKS]
for size in (51, 115, 222):
    packed = dec.ds3604_frames(frames, size)
    assert b"".join(packed) == b"".join(frames) and all(len(p) <= size for p in packed)
# downlinks.json DS3604 settings must be the same bytes as the encoder
dl = json.load(open(_PKG / "downlinks.json"))["DS3604"]["settings"]
for name, cmd in (("buzzer", "buzzer"), ("button", "button"), ("template_button", "template_button")):
    for st, val in (("on", True), ("off", False)):
        if dl[name][st]["hex"] != dec.encode_ds3604(cmd, val).hex():
            bad += 1
            print(f"  MISMATCH downlinks.json DS3604 {name}.{st}")
print(f"TOTAL {len(cases) + 6} cases, {bad} mismatches")
sys.exit(1 if bad else 0)
