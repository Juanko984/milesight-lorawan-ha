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
dec = _load("decoders"); ana = _load("analytics"); mdl = _load("models"); lnk = _load("link")

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
    assert mdl.guess_model(bytes.fromhex("077d2003"))[0] == "AM103"            # CO2 only: AM103 (AM307 also sends PIR / light)
    assert mdl.guess_model(bytes.fromhex("0367f40004688005000106cb01077d2003"))[0] == "AM307"
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


def test_decode_at101():
    d = dec.decode_at101(bytes.fromhex("01756403671B01050000048836BF7701F000090722"))     # official sample
    assert d["battery"] == 100 and d["temperature"] == 28.3 and d["tilted"] is False
    assert d["latitude"] == 24.62495 and d["longitude"] == 118.030576
    assert d["motion_status"] == "moving" and d["geofence_status"] == "unset"
    d = dec.decode_at101(bytes.fromhex("06d900ffffffffffff0003" "06d901112233445566c502" "070001" "83670e0101"))
    assert d["wifi_scan_result"] == "finish" and d["wifi_ap_count"] == 1 and d["wifi"][0]["mac"] == "11:22:33:44:55:66"
    assert d["tamper"] is True and d["temperature_alarm_active"] is True and d["temperature"] == 27.0
    assert mdl.guess_model(bytes.fromhex("01756403671B01050000048836BF7701F000090722"))[0] == "AT101"


def test_distance_tracker():
    dtk = ana.DistanceTracker(CAL)
    t0 = T("2026-10-14T08:00:00")
    dtk.update(t0, -33.918861, 18.4233)
    dtk.update(t0 + 60, -33.918900, 18.4233)                 # 4 m jitter -> ignored
    dtk.update(t0 + 600, -33.928861, 18.4233)                # ~1.11 km
    dtk.update(t0 + 601, 10.0, 10.0)                         # impossible jump -> not counted
    v = dtk.values(t0 + 700)
    assert 1.10 <= v["distance_today_km"] <= 1.12 and v["distance_week_km"] == v["distance_today_km"]
    assert dtk.values(T("2026-10-15T09:00:00"))["distance_yesterday_km"] == v["distance_today_km"]


def test_decode_ws_range():
    assert dec.decode_ws101(bytes.fromhex("01755CFF2E03"))["button_events"] == [("button", "double_press")]
    assert dec.decode_ws136(bytes.fromhex("01755CFF34012150"))["button_events"] == [("button_1", "press")]
    d = dec.decode_ws156(bytes.fromhex("01755CFF34010300FF34060201"))
    assert d["button_events"] == [("button_1", "short_press"), ("button_6", "double_press")]
    assert dec.decode_ws201(bytes.fromhex("01756403823E0004D645")) == {"battery": 100, "distance": 62, "remaining": 69}
    assert dec.decode_ws202(bytes.fromhex("01755C030001040000")) == {"battery": 92, "pir": True, "daylight": "dim"}
    d = dec.decode_ws203(bytes.fromhex("01756403673401046865050000"))
    assert d == {"battery": 100, "temperature": 30.8, "humidity": 50.5, "occupancy": 0}
    assert dec.decode_ws301(bytes.fromhex("01755D030001040000")) == {"battery": 93, "magnet_status": 1, "tamper": False}
    d = dec.decode_ws302(bytes.fromhex("017564055B053F02DA016A02"))
    assert d["sound_weighting"] == "LAF" and d["sound_level"] == 57.5 and d["sound_level_eq"] == 47.4 and d["sound_level_max"] == 61.8
    assert dec.decode_ws303(bytes.fromhex("017564030001")) == {"battery": 100, "leak": 1}
    d = dec.decode_ws52x(bytes.fromhex("08700105816407c9020003742e0906834a000000048000000000"))
    assert d == {"switch_1": True, "power_factor": 100, "current": 0.002, "voltage": 235.0, "energy": 0.074, "power": 0}
    d = dec.decode_ws558(bytes.fromhex("0831000105816407C902000374B208068301000000048001000000"))
    assert d["switch_1"] is True and d["switch_2"] is False and d["voltage"] == 222.6 and d["power"] == 1 and d["current"] == 0.002
    assert dec.decode_ws502(bytes.fromhex("FF2903")) == {"switch_1": True, "switch_2": True}
    assert dec.encode_ws_switch("ff29", 3, True).hex() == "ff2944" and dec.encode_ws_switch("0831", 8, False).hex() == "088000"


def test_guess_ws_range():
    g = mdl.guess_model
    assert g(bytes.fromhex("01755CFF2E03"))[0] == "WS101"
    assert g(bytes.fromhex("01755CFF34010300FF34060201"))[0] == "WS156"
    assert g(bytes.fromhex("01756403823E0004D645"))[0] == "WS201"
    assert g(bytes.fromhex("017564055B053F02DA016A02"))[0] == "WS302"
    assert g(bytes.fromhex("0831000105816407C902000374B208068301000000048001000000"))[0] == "WS558"
    assert g(bytes.fromhex("08700105816407c9020003742e0906834a000000048000000000"))[0] == "WS523"
    assert g(bytes.fromhex("08291105816407c902000374b208068301000000048001000000"))[0] == "WS501-EU"
    assert g(bytes.fromhex("FF2903"))[0] == "WS501" and "WS502" in g(bytes.fromhex("FF2903"))[1]
    assert "WS301" in g(bytes.fromhex("01755D030001040000"))[1] and "WS303" in g(bytes.fromhex("017564030001"))[1]
    assert mdl.guess_from_name("WS301 - back door") == "WS301" and mdl.guess_from_name("ws513-v3 kettle") == "WS513-V3"
    assert mdl.guess_from_name("Kitchen") is None


def test_decode_wt_range():
    d = dec.decode_wt101(bytes.fromhex("01756104672C0103670A01059264099000000B900000"))      # official sample
    assert d["battery"] == 97 and d["temperature"] == 26.6 and d["target_temperature"] == 30.0
    assert d["valve_opening"] == 100 and d["motor_stroke"] == 0
    d = dec.decode_wt201(bytes.fromhex("036702010467A60005E70006E80007BC00"))               # official sample
    assert d == {"temperature": 25.8, "target_temperature": 16.6, "temperature_control_mode": "heat",
                 "temperature_control_status": "standby", "fan_mode": "auto", "fan_status": "standby", "plan_type": "not executed"}
    d = dec.decode_wt303(bytes.fromhex("016a0802e40203d208040005120664071208ff1013000000c801"))
    assert d["temperature"] == 21.54 and d["humidity"] == 74 and d["temperature_control_mode"] == "heat"
    assert d["temperature_control_status"] == "cool" and d["fan_mode"] == "low" and d["fan_status"] == "medium"
    assert d["valve_opening"] == 100 and d["relay_low"] and d["valve_2"] and not d["relay_high"]
    assert dec.decode_wt303(bytes.fromhex("0913b80b"))["temperature_alarm_active"] is True
    d = dec.decode_wt102(bytes.fromhex("0e01660832340855"))
    assert d == {"temperature": 21.5, "valve_opening": 50, "target_temperature": 21.0, "battery": 85}
    d = dec.decode_wt401(bytes.fromhex("0055016608020d02080103000400066408079809"))
    assert d["temperature"] == 21.5 and d["humidity"] == 52.5 and d["occupancy"] == 1 and d["fan_mode"] == "auto"
    assert d["target_temperature"] == 21.48 and d["target_temperature_2"] == 24.56
    frame = bytes.fromhex("5502000a0f01000102282c010030")
    frame += bytes([sum(frame) & 0xFF])
    d = dec.decode_wt30x(frame)
    assert d["system_status"] is True and d["mode"] == "heat" and d["fan_speed"] == "medium" and d["temperature"] == 20.0
    assert d["target_temperature"] == 22.0 and d["card_inserted"] is True and d["server_temperature"] == 24.0
    assert dec.encode_wt("wt303", "target", 21.5, mode="heat").hex() == "6b6608"
    assert dec.encode_wt("wt30x", "target", 21.5).hex() == "55010002052b88"


def test_guess_wt_range():
    g = mdl.guess_model
    assert g(bytes.fromhex("01756104672C0103670A01059264099000000B900000"))[0] == "WT101"
    assert g(bytes.fromhex("036702010467A60005E70006E80007BC00"))[0] == "WT201-V2"
    assert g(bytes.fromhex("016a0802e40203d208040005120664071208ff1013000000c801"))[0] == "WT303"
    assert g(bytes.fromhex("0055016608020d02080103000400066408079809"))[0] == "WT401"
    assert g(bytes.fromhex("0164080664080432075000550501"))[0] == "WT102"
    frame = bytes.fromhex("5502000a0f01000102282c010030")
    assert g(frame + bytes([sum(frame) & 0xFF]))[0] == "WT301"


CTH_EX = open(pathlib.Path(__file__).parent / "cth01_samples.txt").read().split()


def test_decode_cth01():
    d = dec.decode_cth01(bytes.fromhex(CTH_EX[0]))
    assert d["temperature"] == 23.45 and d["voltage_l1"] == 230.12 and "voltage_l3" not in d
    assert d["current_ct1"] == 12.34 and d["current_ct7"] == 100.5 and "current_ct8" not in d
    assert d["sensor_error"].startswith("Read error: voltage l3") and d["power_loss_alarm"] is False
    d = dec.decode_cth01(bytes.fromhex(CTH_EX[1]))
    assert d["power_factor_ct1"] == 0.98 and d["power_factor_b"] == 0.9 and d["active_power_a"] == 1.5
    assert d["active_power_ct4"] == -0.25 and d["active_power_c"] == 4.2 and d["forward_active_energy_ct1"] == 123.456
    d = dec.decode_cth01(bytes.fromhex(CTH_EX[2]))
    assert d["current_ct4_alarm_active"] is True and d["voltage_l2_alarm_status"] == "lower_range_alarm_trigger"
    assert d["power_loss_alarm"] is True
    assert mdl.guess_model(bytes.fromhex(CTH_EX[0]))[0] == "CTH01"
    assert dec.cth01_parses_cleanly(bytes.fromhex(CTH_EX[1])) and not dec.cth01_parses_cleanly(bytes.fromhex("99016aff"))


NEW_SAMPLES = {   # official codec.json samples -> expected model
    "0175640367040104687B077DAC02": "AM103",
    "0175640367000104688206653100c2001b00056a0000": "AM104",
    "01756403ED01": "EM300-CL",
    "01756403D4000001005046": "EM320-TILT",
    "01755C03824408040001": "EM310-UDL",
    "01756202820F00038E01048E01": "VS330",
    "03D24800000004D2C800000006D20000000007D20000000009D2000000000AD2000000000CD2B41400000DD28D1A0000": "VS133",
    "01756403670C0184CC011108110185CCE803E90301": "VS350",
}


def test_guess_new_ranges():
    for hx, model in NEW_SAMPLES.items():
        best, cands = mdl.guess_model(bytes.fromhex(hx))
        assert best == model, (hx, best, cands)


def test_decode_new_ranges():
    d = dec.decode_am104(bytes.fromhex("0175640367000104688206653100c2001b00056a0000"))
    assert d["illuminance_lux"] == 49 and d["pir_activity"] == 0 and d["temperature"] == 25.6
    d = dec.decode_vs330(bytes.fromhex("01756202820F00038E01048E01"))
    assert d["occupancy"] == 1 and d["distance"] == 15 and d["battery"] == 98
    d = dec.decode_vs350(bytes.fromhex("01756403670C0184CC011108110185CCE803E90301"))
    assert d["people_total_in"] == 4353 and d["people_in"] == 1000 and d["people_out"] == 1001
    d = dec.decode_vs133(bytes.fromhex("03D24800000004D2C800000006D20000000007D20000000009D2000000000AD2000000000CD2B41400000DD28D1A0000"))
    assert d["people_total_in"] == 72 and d["line_4_total_in"] == 5300
    assert dec.decode_em300_cl(bytes.fromhex("01756403ED01"))["liquid"] == "full"
    assert dec.decode_em300_mld(bytes.fromhex("0175640500 01".replace(" ", "")))["leak"] == 1


def test_bulk_parse():
    text = """DevEUI,Model,Name,Area
24E124136B322135, EM300-MCS, Back door, Warehouse
24-e1-24-13-6b-32-21-36;ws501 v4;Light
24e124136b322137\tvs350\t\tEntrance
bad, EM300-TH
24e124136b322138, nonsense
24E124136B322135, EM300-TH
"""
    devices, errors = mdl.parse_bulk(text)
    assert [d["model"] for d in devices] == ["EM300-MCS", "WS501-V4", "VS350"]
    assert devices[0] == {"deveui": "24e124136b322135", "model": "EM300-MCS", "name": "Back door", "area": "Warehouse"}
    assert devices[1]["name"] == "Light" and devices[1]["area"] is None and devices[2]["name"] is None
    assert len(errors) == 3 and "invalid DevEUI" in errors[0] and "unknown model" in errors[1] and "twice" in errors[2]



def test_envelope_radio_metadata():
    ms = {"devEUI": "24E124126B316403", "fCnt": 12, "fPort": 85, "data": "AXVk",
          "rxInfo": [{"loRaSNR": -3, "mac": "24e124fffefa0aaa", "rssi": -110},
                     {"loRaSNR": 6.2, "mac": "24e124fffefa0fa8", "name": "Local Gateway", "rssi": -49}],
          "txInfo": {"frequency": 904700000, "dataRate": {"modulation": "LORA", "bandwidth": 125, "spreadFactor": 8}}}
    up = dec.parse_envelope(json.dumps(ms))
    assert [g["id"] for g in up.gateways] == ["24e124fffefa0fa8", "24e124fffefa0aaa"]      # strongest first
    assert up.rssi == -49 and up.snr == 6.2 and up.sf == 8 and up.frequency == 904700000 and up.fcnt == 12
    cs = {"deviceInfo": {"devEui": "0102030405060708"}, "fCnt": 5, "data": "AXVk",
          "rxInfo": [{"gatewayId": "0016C001FF10A235", "rssi": -80, "snr": 9.5}],
          "txInfo": {"modulation": {"lora": {"spreadingFactor": 12}}}}
    up = dec.parse_envelope(json.dumps(cs))
    assert up.gateways[0]["id"] == "0016c001ff10a235" and up.sf == 12
    ttn = {"end_device_ids": {"dev_eui": "0102030405060709"},
           "uplink_message": {"frm_payload": "AXVk", "f_cnt": 7,
                              "rx_metadata": [{"gateway_ids": {"gateway_id": "roof", "eui": "B827EBFFFE000001"},
                                               "rssi": -101, "snr": 2.5}],
                              "settings": {"data_rate": {"lora": {"spreading_factor": 10}}, "frequency": "868300000"}}}
    up = dec.parse_envelope(json.dumps(ttn))
    assert up.gateways == [{"id": "b827ebfffe000001", "name": "roof", "rssi": -101, "snr": 2.5}]
    assert up.sf == 10 and up.fcnt == 7 and up.frequency == 868300000


def test_notifications():
    ack = dec.parse_notification(json.dumps({"applicationID": 1, "devEUI": "24E124527F418093", "acknowledged": True,
                                             "fcnt": 4996, "time": "2026-03-12T06:10:30Z"}))
    assert ack["kind"] == "ack" and ack["deveui"] == "24e124527f418093" and ack["acknowledged"] and ack["fcnt"] == 4996
    join = dec.parse_notification(json.dumps({"devEUI": "24e124527f418093", "devAddr": "0642fa41"}))
    assert join["kind"] == "join" and join["dev_addr"] == "0642fa41"
    info = dec.parse_notification(json.dumps({"tunnel_support": True, "device_info": {
        "eui": "24E124FFFEF00001", "model": "UG63", "firmware_version": "64.0.0.5", "cpu_tempeture": "47"},
        "network_info": {"wan_status": 1, "wan_ip": "10.0.0.2"}}))
    assert info["kind"] == "gateway_info" and info["gateway_id"] == "24e124fffef00001"
    assert info["info"]["cpu_tempeture"] == "47" and info["info"]["wan_ip"] == "10.0.0.2"
    st = dec.parse_notification(json.dumps({"gatewayId": "0016c001ff10a235", "rxPacketsReceived": 10,
                                            "rxPacketsReceivedOk": 9, "txPacketsReceived": 2, "txPacketsEmitted": 2}))
    assert st == {"kind": "gateway_stats", "gateway_id": "0016c001ff10a235", "rx_received": 10, "rx_ok": 9,
                  "tx_received": 2, "tx_emitted": 2}
    conn = dec.parse_notification(json.dumps({"gatewayId": "0016c001ff10a235", "state": "OFFLINE"}))
    assert conn == {"kind": "gateway_state", "gateway_id": "0016c001ff10a235", "online": False}
    # device uplinks are not notifications
    assert dec.parse_notification(json.dumps({"devEUI": "24e1", "data": "AXVk", "fCnt": 1})) is None
    assert dec.parse_notification(json.dumps({"deviceInfo": {"devEui": "0102"}, "devAddr": "01", "fCnt": 3,
                                              "data": "AXVk"})) is None


def test_commands_echo_retry_fail():
    pc = lnk.PendingCommands()
    pc.add("report_interval", bytes.fromhex("ff035802"), 85, 0)
    # first uplink after sending (delivers the downlink) – nothing yet
    assert pc.on_uplink("017564", {}, 10, retries=2) == ([], [])
    # device never answered a setting so far -> unconfirmable: 'sent', and it learns the device does not echo
    resend, done = pc.on_uplink("017564", {}, 20, retries=2)
    assert not resend and done[0]["status"] == "sent" and pc.echoes is False
    # a device that does echo: retried twice, then failed
    pc = lnk.PendingCommands({"echoes": True})
    pc.add("report_interval", bytes.fromhex("ff035802"), 85, 0)
    statuses = []
    for t in range(1, 8):
        resend, done = pc.on_uplink("017564", {}, t, retries=2)
        statuses += [("resend", r["attempts"]) for r in resend] + [(d["status"], d["attempts"]) for d in done]
    assert statuses == [("resend", 2), ("resend", 3), ("failed", 3)], statuses
    # echo on fe channel confirms
    pc.add("report_interval", bytes.fromhex("ff035802"), 85, 100)
    resend, done = pc.on_uplink("0175" + "fe035802", {}, 101, retries=2)
    assert done[0]["status"] == "confirmed" and pc.last["status"] == "confirmed" and not pc.items


def test_commands_state_ack_display():
    pc = lnk.PendingCommands()
    pc.add("switch_1", bytes.fromhex("080100ff"), 85, 0, state={"switch_1": True}, prev={"switch_1": False})
    _, done = pc.on_uplink("", {"switch_1": "on"}, 1, retries=1)
    assert done[0]["status"] == "confirmed" and done[0]["detail"] == "device reports the new state"
    # still the old state after two uplinks -> resent, then failed with prev kept for the revert
    pc.add("switch_1", bytes.fromhex("080100ff"), 85, 0, state={"switch_1": True}, prev={"switch_1": False})
    r1, _ = pc.on_uplink("", {"switch_1": False}, 1, retries=1)
    r2, _ = pc.on_uplink("", {"switch_1": False}, 2, retries=1)
    assert not r1 and r2 and r2[0]["attempts"] == 2
    pc.on_uplink("", {}, 3, retries=1)
    _, done = pc.on_uplink("", {}, 4, retries=1)
    assert done[0]["status"] == "failed" and done[0]["prev"] == {"switch_1": False}
    # confirmed downlink with nothing else to check: the network ACK confirms it
    pc = lnk.PendingCommands({"echoes": False})
    pc.add("reboot", bytes.fromhex("ff10ff"), 85, 0, confirmed=True)
    done = pc.on_ack(True, 5)
    assert done[0]["status"] == "confirmed" and done[0]["detail"] == "acknowledged by the device"
    # NACK -> resent at the next uplink
    pc.add("reboot", bytes.fromhex("ff10ff"), 85, 10, confirmed=True)
    assert pc.on_ack(False, 11) == [] and pc.items["reboot"]["status"] == "not acknowledged"
    resend, _ = pc.on_uplink("", {}, 12, retries=2)
    assert resend and resend[0]["attempts"] == 2
    # DS3604: per-block results
    pc = lnk.PendingCommands()
    pc.add("display text_1, text_2", b"\xfb\x01", 85, 0, results=[[1, 0], [1, 1]])
    _, done = pc.on_uplink("", {"update_content_result": [{"template_id": 1, "block_id": 0, "result": "success"}]}, 1, 2)
    assert not done and pc.items["display text_1, text_2"]["results"] == [[1, 1]]
    _, done = pc.on_uplink("", {"update_content_result": [{"template_id": 1, "block_id": 1, "block_name": "text_2",
                                                            "result": "content is too long"}]}, 2, 2)
    assert done[0]["status"] == "failed" and done[0]["detail"] == "text_2: content is too long"
    # migration from the 0.17 format
    meta = {"pending": {"report_interval": {"hex": "ff035802", "value": 600, "sent": 5}}}
    pc = lnk.PendingCommands.from_meta(meta)
    assert pc.items["report_interval"]["value"] == 600 and "pending" not in meta


def test_commands_regressions():
    # a device that echoes settings must not get a reboot resent (reboot is never echoed)
    pc = lnk.PendingCommands({"echoes": True})
    pc.add("reboot", bytes.fromhex("ff10ff"), 85, 0, echo=False)
    pc.on_uplink("017564", {}, 1, retries=2)
    resend, done = pc.on_uplink("017564", {}, 2, retries=2)
    assert not resend and done[0]["status"] == "sent" and pc.echoes is True
    # an un-echoed reboot does not teach "this device never echoes"
    pc = lnk.PendingCommands()
    pc.add("reboot", bytes.fromhex("ff10ff"), 85, 0, echo=False)
    pc.on_uplink("", {}, 1, 2); pc.on_uplink("", {}, 2, 2)
    assert pc.echoes is None
    # the ACK of a resend belongs to the resend, not to the next command
    pc = lnk.PendingCommands({"echoes": True})
    pc.add("report_interval", bytes.fromhex("ff035802"), 85, 0, confirmed=True)
    pc.on_ack(True, 1)                                       # delivered, waiting for the echo
    pc.on_uplink("", {}, 2, 2)
    resend, _ = pc.on_uplink("", {}, 3, 2)                   # no echo -> resent
    pc.add("led_indicator", bytes.fromhex("ff2f01"), 85, 4, confirmed=True)
    pc.on_ack(True, 5)
    assert pc.items["report_interval"]["status"] == "delivered" and "delivered" not in pc.items["led_indicator"]
    # byte-aligned echo match only
    pc = lnk.PendingCommands({"echoes": True})
    pc.add("x", bytes.fromhex("ff0358"), 85, 0)
    _, done = pc.on_uplink("0ff03580", {}, 1, 2)             # 'ff0358' appears half a byte off
    assert not done


def test_link_stats_and_quality():
    ls = lnk.LinkStats()
    for f in (1, 2, 3, 6, 7):                       # 4 and 5 lost
        ls.update("2026-10-15", f * 600.0, f, [{"id": "gw1", "name": "Roof", "rssi": -100, "snr": 3}])
    assert ls.received == 5 and ls.expected == 7 and ls.loss() == 28.6
    assert ls.is_duplicate(7, 7 * 600.0 + 2) and not ls.is_duplicate(8, 7 * 600.0 + 2)
    ls.update("2026-10-15", 5000.0, 1, [])           # counter reset (rejoin) is not loss
    assert ls.expected == 8 and ls.received == 6
    ls.update("2026-10-16", 90000.0, 2, [])
    assert ls.loss_yesterday == 25.0 and ls.received == 1 and ls.heard_by(90000.0, 86400)[0]["name"] == "Roof"
    assert lnk.link_quality(-60, 9, 7) == "excellent"        # margin 16.5
    assert lnk.link_quality(-110, -6, 12) == "good"          # margin 14
    assert lnk.link_quality(-115, -14, 12) == "fair"         # margin 6
    assert lnk.link_quality(-121, -18, 12) == "poor"
    assert lnk.link_quality(-127, 9, 7) == "poor"            # RSSI cap
    assert lnk.link_quality(None, None, 7) is None
    assert "SF12" in lnk.link_advice("fair", 12, None, 1) and lnk.link_advice("excellent", 7, 0, 2) == "OK"


def test_gateway_stats():
    gs = lnk.GatewayStats()
    rx = [{"id": "gw1", "name": "Local Gateway", "rssi": -60}, {"id": "gw2", "name": None, "rssi": -100}]
    assert gs.uplink("2026-10-15", 3600 * 10 + 5, "dev1", rx) == ["gw1", "gw2"]
    assert gs.uplink("2026-10-15", 3600 * 10 + 65, "dev2", rx[:1]) == []
    gs.uplink("2026-10-15", 3600 * 10 + 70, "dev2", rx[:1], duplicate=True)
    assert gs.counts["uplinks"] == 2 and gs.counts["duplicates"] == 1
    assert gs.gateways["gw1"]["packets_today"] == 3 and gs.gateways["gw1"]["devices_today"] == ["dev1", "dev2"]
    assert gs.packets_last_hour("gw1", 3600 * 10 + 100) == 3 and gs.hourly("gw1", 3600 * 10 + 100)[-1] == 3
    assert gs.online("gw2", 3600 * 10 + 300, 900) is True and gs.online("gw2", 3600 * 12, 900) is False
    gs.state("gw2", 3600 * 12 + 1, True)                      # ChirpStack connection state wins
    assert gs.online("gw2", 3600 * 12 + 2, 900) is True
    assert gs.info("gw3", 50000, {"model": "UG63", "cpu_tempeture": "45"}) and gs.gateways["gw3"]["name"] == "UG63 gw3"
    gs.count("joins", "2026-10-16")
    assert gs.counts == {"uplinks": 0, "duplicates": 0, "downlinks": 0, "joins": 1, "acks": 0, "nacks": 0,
                         "errors": 0} and gs.gateways["gw1"]["packets_today"] == 0


def test_ds3604_encode_and_decode():
    f = dec.encode_ds3604_content(2, "text_3", "Free")
    assert f.hex() == "fb0142" + "04" + b"Free".hex()
    d = dec.decode_ds3604(bytes.fromhex("fb0100054d696c6573" + "fa010000" + "fa010a03" + "ff7301"))
    assert d["template_1"] == {"text_1": "Miles"} and d["current_template_id"] == 2
    assert d["update_content_result"] == [{"template_id": 1, "block_id": 0, "block_name": "text_1", "result": "success"},
                                          {"template_id": 1, "block_id": 10, "block_name": "qrcode",
                                           "result": "content is too long"}]
    frames = [dec.encode_ds3604_content(1, f"text_{n}", "x" * 20) for n in range(1, 6)]   # 24 bytes each
    assert [len(p) for p in dec.ds3604_frames(frames, 51)] == [48, 48, 24]
    try:
        dec.ds3604_frames([dec.encode_ds3604_content(1, "text_1", "x" * 60)], 51)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
