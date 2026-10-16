"""Unit tests for decoders, analytics and models (no Home Assistant needed).

Run:  python -m pytest tests/test_pure.py   (or: python tests/test_pure.py)
"""
import base64
import importlib.util
import json
import pathlib
import sys
import types
from datetime import datetime
from zoneinfo import ZoneInfo

PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "milesight_lorawan"

# Load the pure modules without executing the package __init__ (which needs HA).
pkg = types.ModuleType("mlw"); pkg.__path__ = [str(PKG)]; sys.modules["mlw"] = pkg
def _load(name):
    spec = importlib.util.spec_from_file_location(f"mlw.{name}", PKG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[f"mlw.{name}"] = mod
    spec.loader.exec_module(mod); return mod
dec = _load("decoders"); ana = _load("analytics"); mdl = _load("models")

TZ = ZoneInfo("Africa/Johannesburg")
CAL = ana.Calendar(TZ)
def T(s): return datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()
MIN = 60


def test_envelope_milesight():
    raw = bytes([0x04, 0xC9, 2, 0, 0, 0])
    msg = {"devEUI": "24E124600B251990", "data": base64.b64encode(raw).decode(), "rssi": -90,
           "snr": 8.5, "time": "2026-10-14T14:08:45+02:00", "fPort": 85, "deviceName": "VS121"}
    up = dec.parse_envelope(json.dumps(msg))
    assert up.deveui == "24e124600b251990" and up.raw == raw
    assert up.rssi == -90 and up.snr == 8.5 and up.fport == 85 and up.time.utcoffset().seconds == 7200


def test_envelope_chirpstack_and_garbage():
    msg = {"deviceInfo": {"devEui": "24e124136b322135", "deviceName": "door"},
           "data": "AXVkA2cJAQRoTgYAAQ==", "rxInfo": [{"rssi": -100, "snr": 3.8}]}
    up = dec.parse_envelope(json.dumps(msg))
    assert up.deveui == "24e124136b322135" and up.rssi == -100 and up.device_name == "door"
    assert dec.parse_envelope("not json") is None
    assert dec.parse_envelope(json.dumps({"foo": 1})) is None


def test_decode_em300_mcs():
    d = dec.decode_em300(base64.b64decode("AXVkA2cJAQRoTgYAAQ=="))
    assert d == {"battery": 100, "temperature": 26.5, "humidity": 39.0, "status_input": 1}


def test_decode_em300_negative_and_unknown_channel():
    d = dec.decode_em300(bytes([0x03, 0x67, 0x9C, 0xFF, 0xFE, 0x99, 0x01]))  # -10.0 °C then junk
    assert d["temperature"] == -10.0


def test_decode_vs121():
    d = dec.decode_vs121(bytes([0xFF, 0x01, 0x01, 0x04, 0xC9, 3, 2, 0x00, 0x02]))
    assert d["people_count_all"] == 3 and d["region_count"] == 2 and d["region_1"] == 0 and d["region_2"] == 1


def test_guess_model():
    assert mdl.guess_model(bytes([0x04, 0xC9, 1, 0, 0, 0]))[0] == "VS121"
    best, cands = mdl.guess_model(base64.b64decode("AXVkA2cJAQRoTgYAAQ=="))
    assert best == "EM300-MCS" and "EM300-SLD" in cands
    assert mdl.guess_model(bytes([0x03, 0x67, 0x09, 0x01]))[0] == "EM300-TH"
    assert mdl.guess_model(bytes([0x05, 0xC8, 1, 0, 0, 0]))[0] == "EM300-DI"


def test_entity_specs_unique_keys():
    for m in mdl.MODELS:
        keys = [s.key for s in mdl.entity_specs(m)]
        assert len(keys) == len(set(keys)), m


def test_door_tracker_midnight_week_month():
    tr = ana.BinaryEventTracker(CAL, max_gap_s=7200, left_open_s=600)
    tr.update(T("2026-10-11T23:00:00"), False)       # Sunday
    tr.update(T("2026-10-11T23:50:00"), True)
    tr.tick(T("2026-10-12T00:05:00"))                 # live crediting across midnight
    v = tr.values(T("2026-10-12T00:05:00"))
    assert v["today_s"] == 5 * MIN and v["yesterday_s"] == 10 * MIN and v["count_yesterday"] == 1
    assert v["week_s"] == 5 * MIN and v["last_week_s"] == 10 * MIN   # Monday = new week
    tr.update(T("2026-10-12T00:10:00"), False)
    v = tr.values(T("2026-10-12T00:10:00"))
    assert v["today_s"] == 10 * MIN and v["last_duration_s"] == 20 * MIN and v["active"] is False
    assert v["longest_today_s"] == 20 * MIN
    tr.update(T("2026-10-12T08:00:00"), True)
    v = tr.values(T("2026-10-12T08:15:00"))
    assert v["current_s"] == 15 * MIN and v["left_open"] is True and v["count_today"] == 1
    tr.update(T("2026-10-12T08:20:00"), False)
    v = tr.values(T("2026-11-02T09:00:00"))
    assert v["last_month_s"] == 40 * MIN and v["count_last_month"] == 2 and v["today_s"] == 0


def test_door_gap_cap():
    tr = ana.BinaryEventTracker(CAL, max_gap_s=2 * 3600)
    tr.update(T("2026-10-14T08:00:00"), False)
    tr.update(T("2026-10-14T09:00:00"), True)
    tr.tick(T("2026-10-14T15:00:00"))                 # sensor silent 6 h
    assert tr.values(T("2026-10-14T15:00:00"))["today_s"] == 2 * 3600


def test_occupancy_debounce_and_person_minutes():
    oc = ana.OccupancyTracker(CAL, grace_s=120, max_gap_s=1800)
    t0 = T("2026-10-13T08:00:00")                      # Tuesday, inside 08-17
    for i, n in enumerate([1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1]):   # flickering single person
        oc.update(t0 + i * MIN, n)
    v = oc.values(t0 + 10 * MIN)
    assert v["sessions_today"] == 1 and v["occupied_today_s"] == 10 * MIN
    assert v["person_minutes_today"] == 10 and v["avg_people_today"] == 1.0
    oc.update(t0 + 11 * MIN, 2); oc.update(t0 + 13 * MIN, 0)
    oc.tick(t0 + 16 * MIN)                             # grace expires without new uplink
    v = oc.values(t0 + 16 * MIN)
    assert v["occupied"] is False and v["last_session_s"] == 13 * MIN
    assert v["person_minutes_today"] == 10 + 1 + 4 and v["peak_today"] == 2
    assert v["utilisation_today_pct"] == round(13 / 16 * 100, 1)


def test_occupancy_yesterday_and_weekend():
    oc = ana.OccupancyTracker(CAL)
    oc.update(T("2026-10-16T09:00:00"), 1)             # Friday
    oc.update(T("2026-10-16T09:30:00"), 0)
    oc.tick(T("2026-10-16T09:35:00"))
    v = oc.values(T("2026-10-17T10:00:00"))            # Saturday (closed)
    assert v["occupied_yesterday_s"] == 30 * MIN
    assert v["utilisation_yesterday_pct"] == round(30 / 540 * 100, 1)
    assert v["utilisation_today_pct"] is None and v["open_now"] is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
