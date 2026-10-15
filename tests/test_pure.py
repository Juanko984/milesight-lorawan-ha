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
    assert d == {"battery": 100, "temperature": 26.5, "humidity": 39.0, "magnet_status": 1}


def test_decode_em300_zld_official_sample():
    # sample + expected values from Milesight's official em300-zld decoder
    d = dec.decode_em300(bytes.fromhex("01755c03673401046865050000"))
    assert d == {"battery": 92, "temperature": 30.8, "humidity": 50.5, "input_05": 0}


def test_decode_am308_official_sample():
    d = dec.decode_am300(bytes.fromhex("03670a0104685805000106cb01077dff02087de3000973fe270b7d07000c7d0800017562"))
    assert d == {"temperature": 26.6, "humidity": 44.0, "pir": 1, "light_level": 1, "co2": 767,
                 "tvoc_iaq": 2.27, "pressure": 1023.8, "pm2_5": 7, "pm10": 8, "battery": 98}


def test_decode_em300_negative_and_unknown_channel():
    d = dec.decode_em300(bytes([0x03, 0x67, 0x9C, 0xFF, 0xFE, 0x99, 0x01]))  # -10.0 °C then junk
    assert d["temperature"] == -10.0


def test_decode_vs121():
    d = dec.decode_vs121(bytes([0xFF, 0x01, 0x01, 0x04, 0xC9, 3, 2, 0x00, 0x02]))
    assert d["people_count_all"] == 3 and d["region_count"] == 2 and d["region_1"] == 0 and d["region_2"] == 1


def test_guess_model():
    assert mdl.guess_model(bytes([0x04, 0xC9, 1, 0, 0, 0]))[0] == "VS121"
    best, cands = mdl.guess_model(base64.b64decode("AXVkA2cJAQRoTgYAAQ=="))
    assert best == "EM300-MCS"
    best, cands = mdl.guess_model(bytes([0x03, 0x67, 0x09, 0x01]))        # temperature only
    assert best == "EM500-PT100" and "EM300-TH" in cands
    assert mdl.guess_model(bytes.fromhex("0367090104684e"))[0] == "EM300-TH"
    assert mdl.guess_model(bytes([0x05, 0xC8, 1, 0, 0, 0]))[0] == "EM300-DI"
    assert mdl.guess_model(bytes.fromhex("01755c03673401046865050000"))[0] == "EM300-SLD"
    am = "03670a0104685805000106cb01077dff02087de3000973fe270b7d07000c7d0800017562"
    assert mdl.guess_model(bytes.fromhex(am))[0] == "AM308"
    assert mdl.guess_model(bytes.fromhex("077d2003"))[0] == "AM307"
    assert mdl.guess_model(bytes.fromhex("077d20030a7d10000c7d0500"))[0] == "AM319-HCHO"
    assert mdl.guess_model(bytes.fromhex("077d20030d7d1000"))[0] == "AM319-O3"


def test_decode_vs_range():
    assert dec.decode_vs_occupancy(bytes.fromhex("017564030001")) == {"battery": 100, "occupancy": 1}   # official VS340 sample
    assert dec.decode_vs_occupancy(bytes.fromhex("0300010400 01".replace(" ", ""))) == {"occupancy": 1, "illuminance": "bright"}
    d = dec.decode_vs321(bytes.fromhex("0367ffff05fd030006fe03000100"))
    assert d["temperature_sensor_status"] == "read_failed" and d["people_count_all"] == 3
    assert d["region_1"] == 1 and d["region_2"] == 0 and d["region_1_enable"] == "enable"
    d = dec.decode_vs373(bytes.fromhex("07b0040010000020000006fb0100000101"))
    assert d["detection_status"] == "fall" and d["use_time_now"] == 16 and d["use_time_today"] == 32
    assert d["events"] == [{"alarm_id": 1, "alarm_type": "fall", "alarm_status": "alarm_triggered"}]


def test_guess_vs_range():
    assert mdl.guess_model(bytes.fromhex("017564030001"))[0] == "VS340"
    assert mdl.guess_model(bytes.fromhex("030001040001"))[0] == "VS370"
    assert mdl.guess_model(bytes.fromhex("0367f00005fd0200"))[0] == "VS321"
    assert mdl.guess_model(bytes.fromhex("07b0010000000000000000"))[0] == "VS373"


EM500_SAMPLES = {   # official sample payloads from Milesight's codec files
    "EM500-CO2": ("01756403671901046873057D670406736827",
                  {"battery": 100, "temperature": 28.1, "humidity": 57.5, "co2": 1127, "pressure": 1008.8}),
    "EM500-LGT": ("017564039450000000", {"battery": 100, "illumination": 80}),
    "EM500-PP": ("017564037B0A00", {"battery": 100, "pressure_kpa": 10}),
    "EM500-PT100": ("01756403671901", {"battery": 100, "temperature": 28.1}),
    "EM500-SMTC": ("01756403671901046873057FF000", {"battery": 100, "temperature": 28.1, "moisture": 57.5, "electricity": 240}),
    "EM500-SWL": ("01756403770200", {"battery": 100, "depth": 2}),
    "EM500-UDL": ("01756403821E00", {"battery": 100, "distance": 30}),
}


def test_em500_official_samples_and_guess():
    for model, (hexstr, expected) in EM500_SAMPLES.items():
        d = mdl.MODELS[model].decoder(bytes.fromhex(hexstr))
        for k, v in expected.items():
            assert d[k] == v, (model, k, d)
        best, cands = mdl.guess_model(bytes.fromhex(hexstr))
        assert model == best or model in cands, (model, best, cands)


def test_em500_sensor_error():
    d = dec.decode_em500(bytes.fromhex("0377ffff"))
    assert "depth" not in d and d["depth_error"] == "collection failed" and d["sensor_error"] == "Depth: collection failed"
    assert dec.decode_em500(bytes.fromhex("03770a00"))["sensor_error"] == "OK"


def test_ts_alarm_normalisation():
    # TS301 current firmware: code 2 = below threshold alarm (active), 3 = its release
    d = dec.decode_ts301(bytes.fromhex("8367c8ff02"))
    assert d["temperature"] == -5.6 and d["temperature_alarm_status"] == "below_threshold_alarm" and d["temperature_alarm_active"] is True
    assert dec.decode_ts301(bytes.fromhex("8367c8ff03"))["temperature_alarm_active"] is False
    # older firmware: code 0 = release, 1 = alarm
    assert dec.decode_ts301_v1(bytes.fromhex("8367c8ff00"))["temperature_alarm_active"] is False
    assert dec.decode_ts101(bytes.fromhex("8367c8ff01"))["temperature_alarm_active"] is True
    # mutation alarm doesn't latch
    d = dec.decode_ts101(bytes.fromhex("93d7c8ff2c0102"))
    assert d["temperature_mutation"] == 3.0 and "temperature_alarm_active" not in d
    # TS302 dual channels + contact
    d = dec.decode_ts302(bytes.fromhex("0367fa000467e6ff030001"))
    assert d["temperature_1"] == 25.0 and d["temperature_2"] == -2.6 and d["magnet_status_1"] == 1
    # TS201 v2 sensor status
    assert dec.decode_ts201(bytes.fromhex("b36700"))["sensor_error"] == "Temperature: read error"


def test_ts60x():
    raw = bytes.fromhex("016404ce09000005f4010c010811d0070000")
    d = dec.decode_ts60x(raw)
    assert d["battery"] == 100 and d["temperature"] == 20.0 and d["humidity"] == 50.0 and d["probe_connected"] is True
    assert d["temperature_alarm_status"] == "below_alarm" and d["temperature_alarm_active"] is True
    assert dec.ts60x_parses_completely(raw)
    assert mdl.guess_model(raw)[0] == "TS601"


def test_guess_ts():
    assert mdl.guess_model(bytes.fromhex("017564036710010300 01".replace(" ", "")))[0] == "TS301"
    assert mdl.guess_model(bytes.fromhex("0367fa000467e6ff"))[0] == "TS302"
    assert mdl.guess_model(bytes.fromhex("0367fa0093d7fa002c0102"))[0] == "TS301-V1"
    best, cands = mdl.guess_model(bytes.fromhex("0367fa00"))
    assert "TS101" in cands


def test_uc_dynamic_specs_and_guess():
    s = mdl.dynamic_spec("modbus_chn_3_reg_2")
    assert s.name == "Modbus channel 3 register 2" and s.platform == "sensor"
    assert mdl.dynamic_spec("gpio_input_2").platform == "binary_sensor"
    assert mdl.dynamic_spec("pt100_1").unit == "°C"
    assert mdl.dynamic_spec("adc_1_max").enabled_default is False
    assert mdl.dynamic_spec("modbus_chn_4_alarm").name == "Modbus channel 4 alarm"
    assert mdl.dynamic_spec("firmware_version") is None
    assert mdl.guess_model(bytes.fromhex("f97300030a00"))[0] == "UC100-V2"
    assert mdl.guess_model(bytes.fromhex("0967350007010100"))[0] == "UC300"
    assert mdl.guess_model(bytes.fromhex("01673501026850037564"))[0] == "UC11-T1"
    d = dec.decode_uc300(bytes.fromhex("ff1900040b0000a040"))          # Modbus float type 11? -> hi word
    assert "modbus_chn_1" in d


def test_em400():
    d = dec.decode_em400(bytes.fromhex("01755C0367010104824408050001"))        # official sample
    assert d == {"battery": 92, "temperature": 25.7, "distance": 2116, "position": "tilt", "tilted": True}
    d = dec.decode_em400(bytes.fromhex("8482d00701"))
    assert d["distance"] == 2000 and d["distance_alarm_active"] is True and d["distance_alarm_status"] == "threshold_alarm"
    assert mdl.guess_model(bytes.fromhex("01755C0367010104824408050001"))[0] == "EM400-UDL"


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


def test_decode_ct_range():
    # official samples (ct-series READMEs)
    assert dec.decode_ct10x(bytes.fromhex("0397102700000498B80B")) == {"total_current": 100, "current": 30, "sensor_error": "OK"}
    d = dec.decode_ct10x(bytes.fromhex("8498B80BD007C40905"))
    assert d["current"] == 25 and d["current_max"] == 30 and d["current_min"] == 20
    assert d["current_alarm_active"] is True and d["current_alarm_status"] == "threshold_alarm, over_range_alarm"
    assert dec.decode_ct10x(bytes.fromhex("0498FFFF"))["sensor_error"] == "Current: read failed"
    assert dec.decode_ct10x(bytes.fromhex("8498B80BD007C4090A"))["current_alarm_active"] is False
    assert dec.decode_ct10x(bytes.fromhex("1063e8030000137501")) == {"energy": 10, "low_voltage_alarm": True}
    d = dec.decode_ct30x(bytes.fromhex("0499B80B0699640008990A00039710270000"))
    assert d["current_1"] == 300 and d["current_2"] == 10 and d["current_3"] == 1 and d["total_current_1"] == 100
    d = dec.decode_ct30x(bytes.fromhex("8699B80BD007C40901896710 0101".replace(" ", "")))
    assert d["current_2_alarm_active"] is True and d["temperature"] == 27.2 and d["temperature_alarm_active"] is True
    assert dec.decode_ct30x(bytes.fromhex("1263102700000967fdff")) == {"energy_3": 100, "sensor_error": "Temperature: over range"}


def test_guess_ct_range():
    assert mdl.guess_model(bytes.fromhex("0397102700000498B80B"))[0] == "CT101"
    assert mdl.guess_model(bytes.fromhex("0499B80B"))[0] == "CT303"
    best, cands = mdl.guess_model(bytes.fromhex("0899FFFF"))
    assert best == "CT303" and cands == ["CT303", "CT305", "CT310"]


def test_decode_gs_range():
    d = dec.decode_gs101(bytes.fromhex("058e01060101070100089000e1f505ff3f04"))
    assert d["gas_alarm"] is True and d["valve_status"] is True and d["relay_output_status"] is False
    assert d["life_remain"] == 100_000_000 and d["device_alarm"] == "device_will_be_invalid_soon" and d["end_of_life"] is True
    d = dec.decode_gs301(bytes.fromhex("01756402671C01036864047D0000057D0100"))      # official sample
    assert d == {"battery": 100, "temperature": 28.4, "humidity": 50.0, "nh3": 0.0, "h2s": 0.01, "sensor_error": "OK"}
    assert dec.decode_gs301(bytes.fromhex("047dfeff067d6400")) == {"h2s": 0.1, "sensor_error": "NH3: polarizing"}
    d = dec.decode_gs524n(bytes.fromhex("121164051Bff"))
    assert d["smoke_alarm"] is True and d["event"] == "alarm" and d["battery"] == 100 and d["temperature"] == 27
    assert dec.decode_gs524n(bytes.fromhex("12145a00140000")) == {}                  # not 6 bytes
    assert dec.decode_gs524n(bytes.fromhex("12145a001400"))["battery_low_alarm"] is True
    d = dec.decode_gs601(bytes.fromhex("0050013205200007300009f4000b2c010d6400120102114b"))
    assert d["battery"] == 80 and d["vaping_index"] == 75 and d["pm2_5"] == 32 and d["temperature"] == 24.4
    assert d["humidity"] == 30.0 and d["tvoc"] == 100 and d["occupancy"] == 1 and d["vaping_index_alarm_active"] is True
    assert dec.decode_gs601(bytes.fromhex("0a21"))["burning_alarm"] is True
    assert dec.decode_gs601(bytes.fromhex("0600"))["sensor_error"] == "pm2.5: collection error"


def test_guess_gs_range():
    assert mdl.guess_model(bytes.fromhex("058e00060100"))[0] == "GS101"
    assert mdl.guess_model(bytes.fromhex("01756402671C01036864047D0000057D0100"))[0] == "GS301"
    assert mdl.guess_model(bytes.fromhex("121764000019"))[0] == "GS524N"
    assert mdl.guess_model(bytes.fromhex("0050013205200007300009f4000b2c010d64001201"))[0] == "GS601"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
