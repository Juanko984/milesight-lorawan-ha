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
dec = _load("decoders"); ana = _load("analytics"); mdl = _load("models"); lnk = _load("link"); bc = _load("building_calc"); dcfg = _load("dashboard_config")
cms = _load("commissioning"); chm = _load("channel_map"); tnk = _load("tank"); alr = _load("alerts"); nsa = _load("ns_api")
spt = _load("setpoints"); mtp = _load("modbus_templates"); mcf = _load("modbus_config"); pmp = _load("pump"); pvt = _load("pivot"); irr = _load("irrigation"); prp = _load("purposes"); usg = _load("usage")

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



def _dev(name, online=True, battery=80, low=False, **values):
    return {"deveui": name.upper(), "name": name, "model": "AM307", "online": online, "battery": battery,
            "battery_low": low, "values": values, "units": {"tvoc": "μg/m³"}, "last_seen_text": "15 Oct 09:12",
            "command_failed": None}


def test_air_quality_levels():
    assert bc.air_quality({"co2": 600, "pm2_5": 5}) == ("Good", 100)
    level, score = bc.air_quality({"co2": 1000, "pm2_5": 5})
    assert level == "Moderate" and 80 < score < 100
    assert bc.air_quality({"co2": 1300}, co2_alert=1200)[0] == "Poor"
    assert bc.air_quality({"pm2_5": 80})[0] == "Unhealthy"
    assert bc.air_quality({"temperature": 22}) == (None, None)


def test_compute_building():
    devices = [_dev("Office AM307", co2=948, temperature=23.6, humidity=41, pm2_5=9, tvoc=200),
               _dev("Meeting AM307", co2=1340, temperature=25.1, humidity=58, pm2_5=7, tvoc=400),
               _dev("GS601", co2=None, tvoc=3),                       # TVOC index -> different unit, ignored
               _dev("Back door", online=False), _dev("Fridge", battery=14, low=True)]
    devices[2]["units"] = {"tvoc": None}
    areas = {"Open office": {"temperature": 23.6, "humidity": 41, "co2": 948, "comfort": 85, "occupied": True,
                             "people": 34},
             "Meeting room 1": {"temperature": 25.1, "humidity": 58, "co2": 1340, "comfort": 54, "occupied": True,
                                "people": 8},
             "Kitchen": {"temperature": 22.9, "humidity": 63, "co2": 720, "comfort": 72, "occupied": False,
                         "people": None}}
    gws = [{"name": "Roof", "online": True}, {"name": "Basement", "online": False}]
    b = bc.compute_building(devices, areas, gws, co2_alert=1200, area_order=["Meeting room 1", "Open office"])
    assert b["areas"] == ["Meeting room 1", "Open office"]                    # configured order, others left out
    assert b["averages"]["co2"] == 1144 and b["averages"]["tvoc"] == 300      # GS601 index not averaged
    assert b["air_quality"] == "Moderate" and b["comfort"] == 70 and b["comfortable_areas"] == 1
    assert b["systems"] == round(100 * 4 / 7)            # 3 healthy devices + 1 gateway of 5 + 2
    assert b["people"] == 42 and b["occupied_areas"] == 2
    assert b["health"] == round(0.4 * 70 + 0.4 * b["air_score"] + 0.2 * b["systems"])
    kinds = [(a["severity"], a["where"], a["what"]) for a in b["alerts"]]
    assert ("serious", "Meeting room 1", "CO₂ 1,340 ppm") in kinds and ("serious", "Back door", "Offline") in kinds
    assert ("warning", "Fridge", "Battery 14 %") in kinds and ("serious", "Basement", "Gateway offline") in kinds
    assert kinds[0][0] == "serious" and kinds[-1][0] == "warning"
    assert not any(a["where"] == "Kitchen" for a in b["alerts"])             # not on the dashboard list
    empty = bc.compute_building([], {}, [])
    assert empty["health"] is None and empty["alerts"] == [] and empty["systems"] is None


def test_dashboard_config_and_templates():
    import jinja2
    ctx = {"title": "Building – Head office", "site": "sensor.head_office_site", "health": "sensor.h",
           "comfort": "sensor.c", "air_quality": "sensor.aq", "systems": "sensor.sys", "people": "sensor.p",
           "alerts": "sensor.al", "avg": {"co2": "sensor.avg_co2", "pm2_5": "sensor.avg_pm"},
           "devices_online": "sensor.on", "battery_low": None, "gateways_online": "sensor.gw", "uplinks": None,
           "outside": None, "co2_alert": 1100, "open_alerts": "sensor.open",
           "nav": [("Farm", "milesight-farm", "mdi:tractor-variant"), ("Tanks & alerts", "milesight-tanks", "mdi:storage-tank")],
           "live": [{"type": "grid", "cards": [{"type": "heading", "heading": "Tanks and silos"},
                                               {"type": "gauge", "entity": "sensor.t1_tank_fill"}]}],
           "areas": [{"name": "Board room", "icon": "mdi:table-furniture", "comfort": "sensor.br_c",
                      "occupancy": "sensor.br_o", "co2": "sensor.br_co2"},
                     {"name": "Sam's office", "icon": None, "comfort": None, "occupancy": None, "co2": None}]}
    cfg = dcfg.build_config(ctx)
    view = cfg["views"][0]
    assert view["type"] == "sections" and [b["name"] for b in view["badges"]] == \
        ["Building health", "People in building", "Devices online", "Alerts"]
    secs = view["sections"]
    heads = [next((c.get("heading") for c in s_["cards"] if c["type"] == "heading"), None) for s_ in secs]
    assert heads == [None, "Dashboards", "Overall health", "Needs attention", "Air quality", "System health",
                     "People", "Board room", "Tanks and silos"], heads
    by_head = dict(zip(heads, secs))
    nav = by_head["Dashboards"]["cards"][1:]
    assert [n["tap_action"]["navigation_path"] for n in nav] == ["/milesight-farm", "/milesight-tanks"]
    ppl = by_head["People"]["cards"]
    assert ppl[1]["entity"] == "sensor.p" and ppl[2]["state_content"] == ["people_now", "state"]
    air = by_head["Air quality"]["cards"]
    co2 = next(c for c in air if c["type"] == "gauge" and c["name"] == "CO₂")
    assert co2["segments"][-1]["from"] == 1100 and co2["needle"] is True
    assert next(c for c in air if c["type"] == "history-graph")["entities"] == [{"entity": "sensor.br_co2",
                                                                                 "name": "Board room"}]
    assert by_head["Board room"]["cards"][1]["state_content"] == ["state", "temperature", "humidity", "co2"]
    assert all(c.get("entity") is None or c["entity"] for s_ in secs for c in s_["cards"])   # no empty entities
    json.dumps(cfg)                                                                          # storable

    env = jinja2.Environment()
    env.filters["select"] = lambda xs: [x for x in xs if x]
    site = {"logo": "/local/logo.png", "site": "Head office", "address": "1 Main Rd, Cape Town",
            "contact": "Sam Smith", "phone": "+27 21 000 0000", "email": "fm@example.com", "alerts": 2,
            "status": "2 items need attention"}
    class Now:
        def strftime(self, f): return "Wednesday 15 October 2026 · 14:32"
    banner = env.from_string(secs[0]["cards"][0]["content"]).render(
        state_attr=lambda e, a: site.get(a), states=lambda e: "Acme Facilities", now=Now)
    assert "<h2>Acme Facilities</h2>" in banner and "Head office · 1 Main Rd, Cape Town" in banner
    assert "Facilities: Sam Smith · +27 21 000 0000 · <a href=\"mailto:fm@example.com\">" in banner
    assert '<ha-alert alert-type="warning">2 items need attention</ha-alert>' in banner
    site.update(contact=None, phone=None, email=None, alerts=0, logo=None)
    banner = env.from_string(secs[0]["cards"][0]["content"]).render(
        state_attr=lambda e, a: site.get(a), states=lambda e: "Acme", now=Now)
    assert "Facilities" not in banner and "<img" not in banner and "All systems normal" in banner
    md = by_head["Needs attention"]["cards"][2]["content"]
    al = [{"severity": "serious", "where": "Meeting room 1", "what": "CO₂ 1,340 ppm", "detail": "Above", "since": "14:05"}]
    out = env.from_string(md).render(state_attr=lambda e, a: al)
    assert 'alert-type="error" title="Meeting room 1 · CO₂ 1,340 ppm"' in out and "since 14:05" in out
    heat = ppl[-1]["content"]
    assert '["Board room", "Sam\'s office"]' in heat                 # names safely quoted
    S = types.SimpleNamespace
    sensor = S(state="40", attributes={"area": "Board room", "hourly_today": [None] * 7 + [0, 30, 80] + [None] * 14,
                                        "occupied_now": True, "people_now": 3})
    env.tests["defined"] = lambda v: v is not None and not isinstance(v, jinja2.Undefined)
    out = env.from_string(heat).render(states=S(sensor=[sensor]))
    assert "**Board room** · 🧑 3 · 40 % today  \n⬜⬛🟨🟥⬜" in out, out
    oa = env.from_string(by_head["Needs attention"]["cards"][1]["content"]).render(
        state_attr=lambda e, a: [{"severity": "critical", "title": "Tank low", "message": "12 %", "since": "09:00",
                                  "status": "open", "acknowledged_by": None}])
    assert 'alert-type="error" title="Tank low"' in oa and "since 09:00 · open" in oa



def test_uc300_modbus_after_setting_reply():
    import struct
    # a reply to 'reporting interval' (ff03) or 'output control' (ff93) before the Modbus values must not hide them
    d = dec.decode_uc300(bytes.fromhex("ff035802" + "ff19000102d204"))
    assert d == {"report_interval": 600, "modbus_chn_1": 1234}
    d = dec.decode_uc300(bytes.fromhex("ff93010100000000" + "ff190104" + "07" + struct.pack("<f", 23.5).hex()
                                       + "ff1502"))
    assert d == {"modbus_chn_2": 23.5, "modbus_chn_3_alarm": "read error"}
    assert mdl.dynamic_spec("modbus_chn_2").name == "Modbus channel 2"


def test_channel_map():
    m, err = chm.parse_channel_map(
        "# comment\n3; Tank pressure; bar; 0.01\n3.2 | Flow | m³/h | 0.1 | 0 | volume_flow_rate | 1\n"
        "adc_1; Borehole level; m; 4-20>0-10; ; ; 2\npt100_1; Cold room; °C\ngpio_counter_1; Water; L; ; ; water\n"
        "ch5; ; kPa; -; 2   # inline comment\n")
    assert err == [], err
    p = m["modbus_chn_3"]
    assert (p.name, p.unit, p.device_class, p.state_class) == ("Tank pressure", "bar", "pressure", "measurement")
    assert p.apply(1234) == 12.34 and p.apply("read error") == "read error" and p.apply(True) is True
    f = m["modbus_chn_3_reg_2"]
    assert f.device_class == "volume_flow_rate" and f.decimals == 1 and f.apply(123) == 12.3
    lvl = m["adc_1"]
    assert lvl.apply(4) == 0 and lvl.apply(20) == 10 and lvl.apply(12) == 5 and lvl.device_class == "distance"
    assert m["pt100_1"].device_class == "temperature" and m["pt100_1"].scale == 1
    assert m["gpio_counter_1"].state_class == "total_increasing"
    c5 = m["modbus_chn_5"]
    assert c5.name == "Modbus channel 5" and c5.apply(10) == 12 and c5.device_class == "pressure"
    _, err = chm.parse_channel_map("x9; a\n3; a; b; abc\n2; ok\n2; dup\n4; a; u; 1; 0; colour\n6;a;;;;;9\n7;a;;;;;;sum")
    assert len(err) == 6 and "unknown channel" in err[0] and "numbers" in err[1] and "twice" in err[2]
    assert "device class" in err[3] and "decimals" in err[4] and "state class" in err[5]
    assert chm.channel_key("3/2") == "modbus_chn_3_reg_2" and chm.channel_key("ADC_2") == "adc_2"
    specs = mdl.channel_specs(m)
    assert {s.key for s in specs} == set(m) and next(s for s in specs if s.key == "adc_1").precision == 2


def test_tank_geometry():
    vc = tnk.TankConfig("vertical_cylinder", height_mm=2000, diameter_mm=1000)
    assert abs(tnk.capacity_l(vc) - 1570.8) < 0.1 and abs(tnk.volume_l(vc, 1000) - 785.4) < 0.1
    assert tnk.volume_l(vc, 5000) == tnk.capacity_l(vc) and tnk.volume_l(vc, -5) == 0
    hc = tnk.tank_config({"tank_shape": "horizontal_cylinder", "tank_diameter_mm": 1000, "tank_length_mm": 2000,
                          "install_height_mm": 1200})
    assert hc.height_mm == 1000 and hc.empty_distance_mm == 1200
    full = tnk.capacity_l(hc)
    assert abs(full - 1570.8) < 0.1 and abs(tnk.volume_l(hc, 500) - full / 2) < 0.1
    assert tnk.volume_l(hc, 250) < full * 0.25                       # less than linear near the bottom
    assert tnk.level_mm(hc, "distance", 700) == 500 and tnk.level_mm(hc, "distance", 1300) == 0
    rect = tnk.TankConfig("rectangular", height_mm=1000, length_mm=2000, width_mm=1000)
    assert tnk.capacity_l(rect) == 2000
    silo = tnk.TankConfig("cone_bottom", height_mm=6000, diameter_mm=3000, cone_mm=2000)
    cone = 3.14159265 * 1500 ** 2 * 2000 / 3 / 1e6
    assert abs(tnk.volume_l(silo, 2000) - cone) < 1 and abs(tnk.volume_l(silo, 1000) - cone / 8) < 1
    lin = tnk.TankConfig("linear", height_mm=1000, capacity_l=5000)
    assert tnk.volume_l(lin, 250) == 1250 and tnk.capacity_l(lin) == 5000
    swl = tnk.tank_config({"tank_shape": "vertical_cylinder", "tank_height_mm": 3000, "tank_diameter_mm": 2000,
                           "tank_probe_offset_mm": 100})
    assert tnk.level_mm(swl, "depth", 150) == 1600 and tnk.level_mm(swl, "depth", None) is None
    assert not tnk.tank_config({}).enabled and tnk.tank_config({"tank_shape": "rectangular"}).enabled is False
    assert mdl.tank_source("EM400-UDL") == "distance" and mdl.tank_source("EM500-SWL") == "depth"
    assert mdl.tank_source("EM400-TLD") is None and mdl.tank_source("EM300-TH") is None
    assert mdl.tank_source("EM310-UDL") == mdl.tank_source("EM410-RDL") == mdl.tank_source("EM500-UDL") == "distance"


def test_tank_usage_refill_and_drop():
    cfg = tnk.TankConfig("linear", height_mm=1000, capacity_l=10000, drop_pct=5, drop_minutes=60, density=840)
    tr = tnk.TankTracker()
    t0 = T("2026-10-01 00:00")
    for h in range(0, 48):                     # 2 days, hourly, 240 L/day with ±20 L jitter
        jitter = 20 if h % 2 else -20
        assert tr.update(cfg, t0 + h * 3600, 8000 - h * 10 + jitter) == []
    v = tr.values(cfg, t0 + 47 * 3600, 8000 - 470 + 20)
    assert 200 <= v["tank_usage_per_day"] <= 270, v
    assert 25 <= v["tank_days_left"] <= 40 and v["tank_fill"] == 75.5 and v["tank_mass"] == round(7550 * 0.84, 1)
    assert v["tank_low"] is False and v["tank_sudden_drop"] is False and v["tank_empty_at"] > t0
    t = t0 + 48 * 3600
    assert tr.update(cfg, t, 9900) == []                      # big rise: waits for confirmation
    ev = tr.update(cfg, t + 600, 9895)
    assert ev and ev[0]["type"] == "refill" and ev[0]["added"] > 2000, ev
    use = tr.values(cfg, t + 600, 9895)["tank_usage_per_day"]
    assert 200 <= use <= 270, use                              # a refill is not 'negative usage'
    # one echo glitch (drop and back) is ignored: no alarm, no refill
    assert tr.update(cfg, t + 1200, 8000) == [] and tr.update(cfg, t + 1800, 9890) == []
    assert tr.values(cfg, t + 1800, 9890)["tank_sudden_drop"] is False
    # a real drop: 600 L within 30 minutes, confirmed by the next reading
    assert tr.update(cfg, t + 2400, 9300) == []
    ev = tr.update(cfg, t + 3000, 9295)
    assert ev and ev[0]["type"] == "sudden_drop" and ev[0]["amount"] >= 595, ev
    v = tr.values(cfg, t + 3000, 9295)
    assert v["tank_sudden_drop"] is True and v["tank_drop_amount"] >= 595
    assert tr.update(cfg, t + 3600, 9290) == []                # latched, no repeat event
    tr.clear_alarm(t + 3700)
    assert tr.update(cfg, t + 4200, 9285) == []                # cleared: the old drop does not fire again
    assert tr.values(cfg, t + 4200, 9285)["tank_sudden_drop"] is False
    tr.mark_refilled(t + 5000, 9285)
    assert tr.values(cfg, t + 5000, 9285)["tank_last_refill"] == t + 5000
    low = tnk.TankConfig("linear", height_mm=1000, capacity_l=1000, low_pct=20)
    assert tnk.TankTracker().values(low, 0, 150)["tank_low"] is True
    assert tnk.TankTracker().values(low, 0, None)["tank_low"] is None
    # slow pump refill (+60 L per reading, below the 5 % step) is a refill, and does not wipe out usage
    slow = tnk.TankConfig("linear", height_mm=1000, capacity_l=1560, refill_pct=5)
    tr = tnk.TankTracker()
    for h in range(72):
        tr.update(slow, t0 + h * 3600, 1500 - h * 20)
    before = tr.values(slow, t0 + 71 * 3600, 80)["tank_usage_per_day"]
    evs = []
    for k in range(1, 6):
        evs += tr.update(slow, t0 + 71 * 3600 + k * 900, 80 + 60 * k)
    assert [e["type"] for e in evs] == ["refill"] and tr.s["last_refill"]["added"] == 300
    after = tr.values(slow, t0 + 71 * 3600 + 5 * 900, 380)["tank_usage_per_day"]
    assert before > 400 and after > 400, (before, after)
    # thinning: readings every 2 or 5 minutes keep about one sample per 10 minutes
    for step in (120, 300):
        tr = tnk.TankTracker()
        for i in range(60):
            tr.update(cfg, t0 + i * step, 5000 - i)
        assert len(tr.s["samples"]) <= 60 * step / 480 + 2, (step, len(tr.s["samples"]))
    assert tr.update(cfg, t0 - 10, 1) == []                    # out of order ignored
    st = tnk.TankTracker(json.loads(json.dumps(tr.s)))         # survives a restart
    assert st.s["samples"] == tr.s["samples"]
    st.check_config(cfg)
    assert st.s["samples"]
    st.check_config(tnk.TankConfig("linear", height_mm=1000, capacity_l=20000))   # new size: start afresh
    assert st.s["samples"] == []


def test_alert_escalation():
    cfg = alr.AlertSettings(primary=["notify.a"], backup=["notify.b"], escalate_min=15, repeat_min=30,
                            quiet_start=22, quiet_end=6, dedupe_min=30, action_title="Start pump")
    eng = alr.AlertEngine()
    day = datetime(2026, 10, 16, 14, 0, tzinfo=TZ)
    night = datetime(2026, 10, 16, 23, 0, tzinfo=TZ)
    t = T("2026-10-16 14:00")
    low = {"t:low": {"title": "Tank low – Diesel", "message": "low", "severity": "warning", "category": "tank",
                     "action": True}}
    out = eng.update(low, t, day, cfg)
    assert [m["kind"] for m in out] == ["new"] and out[0]["targets"] == ["notify.a"] and out[0]["action"] == "Start pump"
    aid = out[0]["id"]
    data = alr.notify_data(out[0])
    assert [a["action"] for a in data["data"]["actions"]] == [f"MSL_ACK_{aid}", f"MSL_SNZ_{aid}", f"MSL_RUN_{aid}"]
    assert data["data"]["tag"] == f"milesight_{aid}" and "push" not in data["data"]
    assert eng.update(low, t + 600, day, cfg) == []                    # not yet
    out = eng.update(low, t + 900, day, cfg)
    assert out[0]["kind"] == "escalated" and out[0]["targets"] == ["notify.a", "notify.b"]
    out = eng.update(low, t + 900 + 1800, day, cfg)
    assert out[0]["kind"] == "reminder" and out[0]["targets"] == ["notify.a", "notify.b"]
    acks = eng.acknowledge(aid, t + 3000, "Juan")
    assert acks[0]["kind"] == "acknowledged" and "by Juan" in acks[0]["message"] and not eng.unacknowledged()
    assert "actions" not in alr.notify_data(acks[0])["data"]
    assert eng.update(low, t + 9000, day, cfg) == []                   # acknowledged: quiet
    assert eng.update({}, t + 9100, day, cfg) == []                     # resolved – but wait 5 min for flapping
    assert eng.update(low, t + 9200, day, cfg) == [] and eng.alerts["t:low"]["flaps"] == 1   # back: continues
    assert eng.update({}, t + 9300, day, cfg) == []
    out = eng.update({}, t + 9300 + 300, day, cfg)
    assert out[0]["kind"] == "resolved" and set(out[0]["targets"]) == {"notify.a", "notify.b"}
    out = eng.update(low, t + 9300 + 600, day, cfg)                   # back after 'resolved' was sent: tell again
    assert out[0]["kind"] == "again" and out[0]["id"] == aid and out[0]["title"].startswith("Again")
    eng.update({}, t + 9300 + 700, day, cfg)
    eng.update({}, t + 9300 + 1000, day, cfg)                          # resolved again
    out = eng.update(low, t + 9300 + 1000 + 3600, day, cfg)           # much later: a new alert with a new id
    assert out[0]["kind"] == "new" and out[0]["id"] != aid
    # escalation is not postponed by reminders
    e2 = alr.AlertEngine()
    c2 = alr.AlertSettings(primary=["notify.a"], backup=["notify.b"], escalate_min=15, repeat_min=5)
    kinds = [m["kind"] for i in range(0, 21) for m in e2.update(low, t + i * 60, day, c2)]
    assert kinds[:4] == ["new", "reminder", "reminder", "escalated"], kinds
    # alerts of a device that is not loaded yet are kept, not resolved
    e3 = alr.AlertEngine()
    e3.update({"dev1:leak": {"title": "Leak", "message": "m", "severity": "critical", "category": "safety"}}, t, day, cfg)
    assert e3.update({}, t + 900, day, cfg, keep=("dev1:",)) == [] and e3.alerts["dev1:leak"]["resolved_at"] is None
    # quiet hours: warnings wait, critical go out
    eng = alr.AlertEngine()
    leak = {"d:leak": {"title": "Water leak", "message": "leak", "severity": "critical", "category": "safety"}}
    out = eng.update({**low, **leak}, t, night, cfg)
    assert [m["key"] for m in out] == ["d:leak"] and out[0]["critical"]
    crit = alr.notify_data(out[0])["data"]
    assert crit["push"]["interruption-level"] == "critical" and crit["channel"] == "alarm_stream"
    assert eng.alerts["t:low"]["held"] is True
    morning = datetime(2026, 10, 17, 6, 5, tzinfo=TZ)
    out = eng.update({**low, **leak}, t + 8 * 3600, morning, cfg)
    assert {m["key"]: m["kind"] for m in out} == {"t:low": "new", "d:leak": "escalated"}
    # categories filter and disabled
    assert alr.AlertEngine().update(low, t, day, alr.AlertSettings(primary=["notify.a"], categories=("safety",))) == []
    eng = alr.AlertEngine()
    assert eng.update(low, t, day, alr.AlertSettings()) == [] and len(eng.unacknowledged()) == 1
    assert alr.in_quiet(23.5, 22, 6) and alr.in_quiet(1, 22, 6) and not alr.in_quiet(12, 22, 6)
    assert alr.in_quiet(13, 12, 14) and not alr.in_quiet(14, 12, 14) and not alr.in_quiet(3, None, 6)
    # device alerts from values
    al = alr.device_alerts("Diesel", "abc", {"leak_active": True, "tank_low": True, "tank_fill": 12.0,
                                             "tank_days_left": 3.5, "tank_sudden_drop": True,
                                             "tank_drop_amount": 450.0, "online": False, "battery_low": True,
                                             "battery": 9}, "Yard")
    assert set(al) == {"abc:leak_active", "abc:tank_low", "abc:tank_drop", "abc:offline", "abc:battery"}
    assert al["abc:tank_low"]["message"] == "Diesel (Yard) is low (12 % left, about 3.5 days)."
    assert "450 L" in al["abc:tank_drop"]["message"] and al["abc:tank_drop"]["severity"] == "critical"
    assert alr.device_alerts("x", "e", {"online": None, "leak_active": False}) == {}


def test_ns_api_helpers():
    rid, text = nsa.build_request("post", "/api/urdevices", {"a": 1}, "24E124FFFEF00001", rid="r1")
    msg = json.loads(text)
    assert msg == {"type": "ns-api", "id": "r1", "method": "POST", "url": "/api/urdevices",
                   "gatewayEUI": "24e124fffef00001", "body": {"a": 1}}
    assert "gatewayEUI" not in json.loads(nsa.build_request("GET", "/x")[1])
    ok = json.dumps({"type": "ns-api", "id": "r1", "method": "POST", "url": "/api/urdevices",
                     "body": {"code": 200, "error": ""}})
    assert nsa.parse_response(ok) == ("r1", 200, "", {"code": 200, "error": ""})
    dup = json.dumps({"type": "ns-api", "id": "r2", "body": json.dumps({"code": 6, "error": "device exist"})})
    assert nsa.parse_response(dup)[1:3] == (6, "device exist")
    assert nsa.parse_response('{"devEUI": "x"}') is None and nsa.parse_response(b"garbage") is None
    assert "already exists" in str(nsa.NsApiError(6)) and "no answer" in str(nsa.NsApiError(None))
    body = nsa.device_body("24E124136D000001", "Tank", "1", "uuid-a")
    assert body["devEUI"] == "24e124136d000001" and body["appKey"] == nsa.DEFAULT_APP_KEY and body["fPort"] == 85
    assert body["applicationID"] == "1" and body["profileID"] == "uuid-a"
    listing = {"code": 200, "deviceResult": [{"devEUI": "24E124136D000001", "name": "EM300-TH Office",
                                              "applicationID": "1", "profileName": "ClassA-OTAA", "active": True}],
               "appResult": [{"appName": "cloud", "applicationID": "1"}],
               "profileResult": [{"profileID": "uuid-a", "profileName": "ClassA-OTAA"}]}
    assert nsa.parse_devices(listing)[0]["deveui"] == "24e124136d000001"
    assert nsa.parse_applications(listing) == {"1": "cloud"} and nsa.parse_profiles(listing) == {"uuid-a": "ClassA-OTAA"}
    profs = {"result": [{"name": "ClassC-OTAA", "profile": {"profileID": "uuid-c", "supportsJoin": True}}]}
    assert nsa.parse_profiles(profs) == {"uuid-c": "ClassC-OTAA"}
    assert nsa.valid_key("5572404c696e6b4c6f52613230313823") and not nsa.valid_key("55")
    # a UG65's real answer: no "type", no "code", keys in the device list
    real = json.dumps({"id": "ff3f9022d28244cb", "gatewayEUI": "24E124FFFEFA2994", "method": "GET",
                       "url": "/api/urdevices?applicationID=0&offset=0&limit=9999",
                       "body": {"devTotalCount": "1", "deviceResult": [
                           {"devEUI": "24E124329F088306", "name": "EM400-MUD", "applicationID": "6",
                            "appKey": "5572404c696e6b4c6f52613230313823", "appSKey": "2ec7f93a91a5e3a835e82ec0d73d7ce6",
                            "lastSeenAt": "24 seconds ago", "lastSeenAtTime": "2026-10-16 19:16:01.926484 +0800 CST",
                            "active": True}],
                           "appResult": [{"appName": "HA Milesight Integration", "applicationID": "6"}],
                           "profileResult": [{"profileID": "33a910a5", "profileName": "ClassA-OTAA", "supportsJoin": True}]}})
    rid, code, err, body = nsa.parse_response(real)
    assert rid == "ff3f9022d28244cb" and code is None and err == ""
    d = nsa.parse_devices(body)[0]
    assert d["application_id"] == "6" and d["last_seen"].startswith("2026-10-16 19:16") and "appKey" not in d
    masked = nsa.mask_secrets(real)
    assert "5572404c" not in masked and "2ec7f93a" not in masked and '"appKey": "***"' in masked
    devs, errs = mdl.parse_bulk("24E124136D000001, EM300-TH, Office, , 00112233445566778899AABBCCDDEEFF\n"
                                "24E124136D000002, EM300-TH, , , 1234")
    assert devs[0]["app_key"] == "00112233445566778899aabbccddeeff" and "AppKey" in errs[0]


def test_envelope_gateway_codec():
    # gateway payload codec on: decoded fields next to devEUI, no "data"
    up = dec.parse_envelope(json.dumps({"devEUI": "24E124128C140924", "deviceName": "AM107", "fCnt": 5,
                                        "temperature": 22.1, "humidity": 50, "co2": 600, "rssi": -80}))
    assert up.raw is None and up.predecoded == {"temperature": 22.1, "humidity": 50, "co2": 600}
    assert mdl.guess_from_name(up.device_name) == "AM107"
    assert dec.parse_envelope(json.dumps({"devEUI": "24E124128C140924", "deviceName": "x"})).predecoded is None


def test_bundled_resources_match_repo():
    root = PKG.parents[1]
    for src, dst in ((root / "blueprints" / "automation" / "milesight_lorawan", PKG / "resources" / "blueprints"),
                     (root / "dashboards", PKG / "resources" / "dashboards")):
        for f in src.glob("*.yaml"):
            if f.name == "building_overview.example.yaml":
                continue
            assert (dst / f.name).read_bytes() == f.read_bytes(), f"run tools/sync_resources.py ({f.name})"


def test_commissioning_qr_and_walk():
    g = mdl.guess_from_name
    assert cms.parse_qr("24E124136D058239", g)["deveui"] == "24e124136d058239"
    tr = cms.parse_qr("LW:D0:24E124C0002A0001:24E124136D058239:FF0C0001:O123:S6136D05823900:C1A2B", g)
    assert tr["format"] == "tr005" and tr["deveui"] == "24e124136d058239" and tr["sn"] == "6136D05823900"
    js = cms.parse_qr('{"DevEUI":"24E124136D058239","AppKey":"5572404c696e6b4c6f52613230313823","Model":"EM300-ZLD"}', g)
    assert js["app_key"] == "5572404c696e6b4c6f52613230313823" and js["model"] == "EM300-ZLD"
    tx = cms.parse_qr("Model: AM307\nSN: 6707D1234567\nDevEUI: 24 E1 24 70 7D 22 33 93\nAppKey: 5572404C696E6B4C6F52613230313823", g)
    assert tx["deveui"] == "24e124707d223393" and tx["model"] == "AM307" and tx["app_key"].startswith("5572")
    both = cms.parse_qr("24E124136D058239 5572404c696e6b4c6f52613230313823", g)
    assert both["deveui"] == "24e124136d058239" and both["app_key"] == "5572404c696e6b4c6f52613230313823"
    assert cms.parse_qr("0004A30B0021C668 24E124126A211292", g)["deveui"] == "24e124126a211292"   # Milesight EUI first
    assert cms.parse_qr("hello", g)["deveui"] is None and cms.parse_qr("", g)["deveui"] is None
    pts = [{"rssi": -88, "snr": 6.5, "sf": 7, "quality": "good", "margin": 14, "gateways": [{"name": "UG65"}]},
           {"rssi": -109, "snr": -4, "sf": 9, "quality": "fair", "margin": 8.5, "gateways": [{"name": "UG56"}]},
           {"rssi": -60, "snr": 9, "sf": 7, "quality": "excellent", "duplicate": True}]
    s = cms.walk_summary(pts)
    assert s["count"] == 2 and s["verdict"] == "fair" and s["rssi"]["min"] == -109 and s["gateways"] == ["UG56", "UG65"]
    assert "little margin" in s["advice"] and cms.walk_summary([])["verdict"] is None
    assert cms.fast_interval({"unit": "s", "min": 60}) == (60, "s") and cms.fast_interval({"unit": "min", "min": 1}) == (1, "min")
    assert cms.fast_interval({"unit": "s", "min": 300}) == (300, "s") and cms.default_interval("min") == 10
    up = dec.Uplink(deveui="x", rssi=None, snr=None, sf=9, fcnt=4, gateways=[{"id": "gw", "name": "UG65", "rssi": -100, "snr": 2}])
    smp = cms.sample(up, False, 1.0)
    assert smp["rssi"] == -100 and smp["quality"] in ("fair", "good") and smp["gateways"][0]["name"] == "UG65"


def test_pump_analytics():
    cfg = pmp.pump_config({"pump_enabled": True, "pump_max_starts": 3, "mains_voltage": 230}, 0.5)
    assert cfg.enabled and cfg.max_starts_hour == 3 and cfg.normal_a == 0
    t, day = T("2026-10-14 06:00"), "2026-10-14"
    pt = pmp.PumpTracker()
    evs = []
    for i in range(8):                       # 8 readings, 10 A, every 5 min → learns normal = 10 A
        evs += pt.update(cfg, t + i * 300, 10.0 if i else 0.0, day)
    assert [e["type"] for e in evs] == ["start"]
    v = pt.values(cfg, t + 7 * 300, None, None)
    assert v["pump_running"] and v["pump_normal_current"] == 10.0 and abs(v["pump_run_hours"] - 0.5) < 0.01
    assert abs(v["pump_energy_today"] - 10 * 230 * 0.85 * 1800 / 3.6e6) < 0.002          # estimate from amps × volts
    # dry-run: two readings below 60 % of normal
    t2 = t + 8 * 300
    assert pt.update(cfg, t2, 4.0, day) == []
    ev = pt.update(cfg, t2 + 60, 4.0, day)
    assert ev[0]["type"] == "dry_run" and pt.values(cfg, t2 + 60, None, None)["pump_dry_run"]
    pt.update(cfg, t2 + 120, 10.0, day)
    assert not pt.values(cfg, t2 + 120, None, None)["pump_dry_run"]
    # overload, then a stop clears it
    pt.update(cfg, t2 + 180, 14.0, day)
    assert pt.update(cfg, t2 + 240, 14.0, day)[0]["type"] == "overload"
    assert pt.update(cfg, t2 + 300, 0.0, day)[0]["type"] == "stop"
    assert not pt.values(cfg, t2 + 300, None, None)["pump_overload"]
    # short-cycling: the 4th start within an hour (max 3)
    t3, kinds = t2 + 400, []
    for i in range(4):
        kinds += [e["type"] for e in pt.update(cfg, t3 + i * 600, 10.0, day)]
        pt.update(cfg, t3 + i * 600 + 120, 0.0, day)
    assert kinds.count("short_cycling") == 1
    assert pt.values(cfg, t3 + 1900, None, None)["pump_short_cycling"]
    # energy counter + water meter → m³ per kWh; a new day starts the counters again
    p2 = pmp.PumpTracker()
    p2.update(cfg, t, 10.0, day, 100.0, 50.0)
    p2.update(cfg, t + 3600, 10.0, day, 102.0, 80.0)
    v = p2.values(cfg, t + 3600, 102.0, 80.0)
    assert v["pump_energy_today"] == 2.0 and v["pump_water_today"] == 30.0 and v["pump_m3_per_kwh"] == 15.0
    p2.update(cfg, t + 86400, 10.0, "2026-10-15", 110.0, 90.0)
    assert p2.values(cfg, t + 86400, 110.0, 90.0)["pump_energy_today"] == 0.0
    # restored from storage
    assert pmp.PumpTracker(json.loads(json.dumps(p2.s))).s == p2.s
    assert pmp.pump_config({}, 0.5).enabled is False


def _pivot_point(b, r=400.0, lat0=-26.0, lon0=28.0):
    import math
    return (lat0 + r * math.cos(math.radians(b)) / 111195,
            lon0 + r * math.sin(math.radians(b)) / (111195 * math.cos(math.radians(lat0))))


def test_pivot_analytics():
    cfg = pvt.pivot_config({"pivot_centre": {"latitude": -26.0, "longitude": 28.0}, "pivot_stall_min": 30})
    assert cfg.enabled and cfg.sector == 360 and not pvt.pivot_config({}).enabled
    assert abs(pvt.bearing(-26.0, 28.0, *_pivot_point(90)) - 90) < 0.1
    assert abs(pvt.distance_m(-26.0, 28.0, *_pivot_point(200)) - 400) < 1
    pt, t = pvt.PivotTracker(), T("2026-10-14 06:00")
    assert pt.update(cfg, t, *_pivot_point(10)) == []                       # first fix
    ev = pt.update(cfg, t + 3600, *_pivot_point(25))                         # 15°/h clockwise
    assert ev[0]["type"] == "started" and ev[0]["direction"] == "clockwise"
    pt.update(cfg, t + 7200, *_pivot_point(40))
    v = pt.values(cfg, t + 7200)
    assert v["pivot_status"] == "running" and abs(v["pivot_angle"] - 40) < 0.2 and abs(v["pivot_speed"] - 15) < 0.3
    assert abs(v["pivot_progress"] - 30 / 360 * 100) < 0.2 and abs(v["pivot_finish_in"] - 330 / 15) < 0.5
    assert v["pivot_radius"] and abs(v["pivot_radius"] - 400) < 1
    # GPS noise does not count as movement; no movement for 30 min = stalled
    assert pt.update(cfg, t + 7200 + 600, *_pivot_point(40.3)) == []
    assert pt.check(cfg, t + 7200 + 1500) == []
    st = pt.check(cfg, t + 7200 + 1800)
    assert st[0]["type"] == "stalled" and pt.values(cfg, t + 9000)["pivot_stalled"] is True
    assert pt.check(cfg, t + 9100) == []                                     # once
    assert pt.values(cfg, t + 9000)["pivot_finish_in"] is None
    pt.update(cfg, t + 10800, *_pivot_point(55))                             # moves again: stall clears
    assert pt.values(cfg, t + 10800)["pivot_stalled"] is False
    # a bad fix far away is ignored
    assert pt.update(cfg, t + 10900, -25.0, 28.0) == [] and abs(pt.values(cfg, t + 10900)["pivot_angle"] - 55) < 0.3
    # complete the round (crossing north)
    ts, ang, fin = t + 10800, 55, []
    while ang < 380 and not fin:
        ang += 15; ts += 3600
        fin = [e for e in pt.update(cfg, ts, *_pivot_point(ang % 360)) if e["type"] == "finished"]
    assert fin and pt.values(cfg, ts)["pivot_status"] == "finished" and pt.values(cfg, ts)["pivot_progress"] == 100
    # the 'Pivot stopped' button clears a stall
    p2 = pvt.PivotTracker(json.loads(json.dumps(pt.s)))
    p2.update(cfg, ts + 3600, *_pivot_point(30)); p2.update(cfg, ts + 7200, *_pivot_point(45))
    p2.check(cfg, ts + 7200 + 3600)
    assert p2.values(cfg, ts + 11000)["pivot_stalled"]
    p2.stop()
    assert p2.values(cfg, ts + 11000)["pivot_stalled"] is False and p2.values(cfg, ts + 11000)["pivot_status"] == "stopped"
    # part circle (90°) that reverses
    c90 = pvt.pivot_config({"pivot_centre": {"latitude": -26.0, "longitude": 28.0}, "pivot_sector": 90})
    p3 = pvt.PivotTracker()
    p3.update(c90, t, *_pivot_point(0)); p3.update(c90, t + 3600, *_pivot_point(30))
    assert p3.values(c90, t + 3600)["pivot_progress"] == round(30 / 90 * 100, 1)
    p3.update(c90, t + 7200, *_pivot_point(10))                             # reversed: a new pass
    v = p3.values(c90, t + 7200)
    assert v["pivot_direction"] == "anticlockwise" and abs(v["pivot_progress"] - 20 / 90 * 100) < 0.5


def test_irrigation_advice_and_frost():
    tz = TZ
    now = datetime(2026, 10, 14, 17, 0, tzinfo=tz)
    hourly = [{"datetime": (now.replace(minute=0) + __import__("datetime").timedelta(hours=h)).isoformat(),
               "temperature": 12 - h * 0.8, "precipitation": 0.0, "precipitation_probability": 10} for h in range(30)]
    cfg = irr.irrigation_config({"irr_weather": "weather.home", "irr_soil": ["sensor.soil"], "irr_target": 30,
                                 "irr_frost_c": 2, "irr_base_minutes": 60})
    r = irr.rain_ahead(hourly, now, 24)
    assert r["mm"] == 0 and r["probability"] == 10 and r["periods"] == 24
    a = irr.advice([15.0, 15.0], r, cfg)
    assert a["advice"] == "irrigate" and a["minutes"] == 30 and a["soil_moisture"] == 15
    assert irr.advice([31.0], r, cfg)["advice"] == "skip"
    assert irr.advice([29.0], r, cfg)["advice"] == "skip"                     # < 5 min needed
    assert irr.advice([], r, cfg)["minutes"] == 60                             # no soil sensor: full time
    wet = [dict(f, precipitation=1.0, precipitation_probability=80) for f in hourly]
    rw = irr.rain_ahead(wet, now, 24)
    assert rw["mm"] == 24 and irr.advice([10.0], rw, cfg)["advice"] == "skip" and "rain" in irr.advice([10.0], rw, cfg)["reason"]
    unlikely = [dict(f, precipitation=1.0, precipitation_probability=30) for f in hourly]
    a2 = irr.advice([15.0], irr.rain_ahead(unlikely, now, 24), cfg)
    assert a2["advice"] == "irrigate" and a2["minutes"] < 30                    # some rain credited, not skipped
    # frost: lowest temperature until 10:00 tomorrow
    f = irr.frost_tonight(hourly, now, 2)
    assert f["expected"] and f["active"] and f["low"] <= 2
    noon = datetime(2026, 10, 14, 12, 0, tzinfo=tz)
    hf = [dict(x, datetime=(noon + __import__("datetime").timedelta(hours=i)).isoformat()) for i, x in enumerate(hourly)]
    fn = irr.frost_tonight(hf, noon, 2)
    assert fn["expected"] and not fn["active"]                                # known at noon, warned from 15:00
    warm = [dict(x, temperature=15) for x in hourly]
    assert not irr.frost_tonight(warm, now, 2)["expected"]
    # daily forecasts: tomorrow's templow, rain of the days in the window
    daily = [{"datetime": "2026-10-14T00:00:00+02:00", "temperature": 18, "templow": 9, "precipitation": 10},
             {"datetime": "2026-10-15T00:00:00+02:00", "temperature": 14, "templow": 1, "precipitation": 2}]
    fd = irr.frost_tonight(daily, now, 2, daily=True)
    assert fd["active"] and fd["low"] == 1
    rd = irr.rain_ahead(daily, now, 24, daily=True)
    assert abs(rd["mm"] - (10 * 7 / 24 + 2)) < 0.11


def test_pump_pivot_alerts_and_categories():
    v = {"pump_dry_run": True, "pump_short_cycling": True, "pump_starts_last_hour": 9, "pivot_stalled": True,
         "pivot_angle": 123.4}
    al = alr.device_alerts("Borehole", "abc", v, "North")
    assert al["abc:pump_dry"]["severity"] == "critical" and al["abc:pump_dry"]["category"] == "pumps"
    assert "9 times" in al["abc:pump_cycling"]["message"] and "123°" in al["abc:pivot_stalled"]["message"]
    assert al["abc:pivot_stalled"]["category"] == "irrigation"
    assert "pumps" in alr.effective_categories({}) and "irrigation" in alr.effective_categories({})
    old = {"alert_categories": ["safety", "devices"]}                          # saved before 0.24
    assert set(alr.effective_categories(old)) == {"safety", "devices"} | (set(alr.DEFAULT_CATEGORIES) - set(alr._CATEGORIES_V1))
    new = {"alert_categories": ["safety"], "alert_categories_known": list(alr.CATEGORIES)}
    assert alr.effective_categories(new) == ("safety",)
    assert "pump" not in mdl.device_tags("CT101") and {"pump"} <= mdl.device_tags("CT101", {"pump_enabled": True})
    assert "irrigation" not in mdl.device_tags("AT101")
    assert "irrigation" in mdl.device_tags("AT101", {"pivot_centre": {"latitude": 1, "longitude": 2}})
    assert "irrigation" in mdl.device_tags("UC511")
    assert mdl.pump_capable("CT103") and not mdl.pump_capable("AM307")
    assert {s.key for s in mdl.pump_specs(True)} >= {"pump_m3_per_kwh", "pump_dry_run"}
    assert "cmd_pivot_stop" in {s.key for s in mdl.pivot_specs()}


def test_purposes_catalogue():
    assert mdl.families("CT101") == {"load"} and "load" in mdl.families("WS523")
    assert {"contact", "temperature"} <= mdl.families("EM300-MCS") and "contact" in mdl.families("TS301")
    assert mdl.families("EM300-TH") == {"temperature"} and "temperature" not in mdl.families("CT101")
    assert {"leak", "temperature"} <= mdl.families("EM300-SLD") and "level" in mdl.families("EM400-TLD")
    assert "button" in mdl.families("WS101") and "pulse" in mdl.families("EM300-DI") and "soil" in mdl.families("EM500-SMTC")
    keys = [p.key for p in mdl.purposes_for("WS301")]
    assert {"door", "window", "gate", "fridge", "cabinet"} <= set(keys) and "pump" not in keys
    assert {"fridge", "ac", "pump", "mains"} <= {p.key for p in mdl.purposes_for("CT303")} and mdl.load_channels("CT303") == 3
    for k, p in prp.PURPOSES.items():
        assert p.group is None or p.group in prp.GROUPS, k
        assert set(p.defaults) <= set(prp.SETTINGS), k
        assert any(mdl.families(m) & p.families for m in mdl.MODELS), f"no model fits {k}"
    cfg = prp.settings("fridge", {"p_temp_high": 8})
    assert cfg["temp_low"] == 0 and cfg["temp_high"] == 8 and cfg["left_open_min"] == 2
    assert prp.settings(None, {}) == {} and prp.settings("door", {})["after_hours"] is True
    assert "temp_low" not in prp.settings("geyser", {"p_temp_low": "off"})           # a default limit switched off
    assert prp.PURPOSES["fridge"].door_noun == "Door" and prp.PURPOSES["gate"].door_noun == "Gate"
    assert prp.resolve("Fridge / cold room") == "fridge" and prp.resolve("fridge") == "fridge"
    assert prp.resolve("gate") == "gate" and prp.resolve("AC") == "ac" and prp.resolve("nonsense") is None
    assert "temp_low" in prp.setting_fields("fridge", mdl.families("EM300-MCS"))
    assert "left_open_min" in prp.setting_fields("fridge", mdl.families("EM300-MCS"))
    assert "max_run_h" in prp.setting_fields("fridge", {"load"}) and prp.setting_fields("doorbell", {"button"}) == []
    tz = TZ
    assert prp.in_hours(datetime(2026, 10, 14, 9, 0, tzinfo=tz), 8, 17, (0, 1, 2, 3, 4))           # Wednesday
    assert not prp.in_hours(datetime(2026, 10, 14, 19, 0, tzinfo=tz), 8, 17, (0, 1, 2, 3, 4))
    assert not prp.in_hours(datetime(2026, 10, 17, 9, 0, tzinfo=tz), 8, 17, (0, 1, 2, 3, 4))          # Saturday
    assert prp.in_hours(datetime(2026, 10, 14, 23, 0, tzinfo=tz), 22, 6, ())                          # night shift
    assert mdl.device_tags("EM300-TH", {"purpose": "fridge"}) >= {"cold_chain", "comfort"}
    assert mdl.device_tags("CT303", {"purpose_1": "ac", "purpose_2": "lighting"}) >= {"hvac", "energy"}
    assert mdl.TAGS["cold_chain"][0] == "Milesight · Cold chain"
    devs, errs = mdl.parse_bulk("24E124136B322135, EM300-MCS, Cold room door, Kitchen, , fridge\n"
                                "24E124136B322136, WS301, Gate, Yard, , pump")
    assert devs[0]["purpose"] == "fridge" and "does not fit" in errs[0]


def test_load_tracker():
    t0 = T("2026-10-14 00:00"); day = "2026-10-14"
    tr = usg.LoadTracker()
    cfg = prp.settings("fridge", {})
    # compressor cycles 20 min on / 40 min off for 6 hours, readings every 10 min
    for i in range(37):
        ts = t0 + i * 600
        tr.update(ts, (i % 6) < 2, day, t0, False)
    v = tr.values(t0 + 36 * 600, cfg)
    assert 30 <= v["load_duty_today"] <= 37 and v["load_starts_today"] == 6 and not v["load_ran_too_long"]
    assert v["load_duty_24h"] is not None and 30 <= v["load_duty_24h"] <= 37
    # stuck on for 3 hours → ran too long
    ts = t0 + 37 * 600
    for i in range(20):
        tr.update(ts + i * 600, True, day, t0, False)
    v = tr.values(ts + 19 * 600, cfg)
    assert v["load_ran_too_long"] and v["load_running_for_h"] >= 3
    # stops and stays off for 3 h → not running
    ts2 = ts + 20 * 600
    tr.update(ts2, False, day, t0, False)
    tr.update(ts2 + 3 * 3600, False, day, t0, False)
    assert tr.values(ts2 + 3 * 3600, cfg)["load_not_running"] is True
    # after hours: an AC running 40 min outside working hours, reset when work starts
    ac = usg.LoadTracker(); acfg = prp.settings("ac", {})
    evs = []
    for i in range(5):
        evs += ac.update(t0 + 20 * 3600 + i * 600, True, day, t0, False)
    assert ac.values(t0 + 20 * 3600 + 2400, acfg)["load_after_hours"] and [e["type"] for e in evs].count("after_hours") == 1
    ac.update(t0 + 32 * 3600, True, "2026-10-15", t0 + 86400, True)
    assert ac.values(t0 + 32 * 3600, acfg)["load_after_hours"] is False
    # service interval
    m = usg.LoadTracker(); mcfg = {"service_h": 2}
    for i in range(14):
        m.update(t0 + i * 600, True, day, t0, True)
    assert m.values(t0 + 13 * 600, mcfg)["load_service_due"] is True
    m.serviced()
    assert m.values(t0 + 13 * 600, mcfg)["load_service_due"] is False
    assert usg.LoadTracker(json.loads(json.dumps(tr.s))).s == tr.s


def test_temp_watch_and_trend():
    t0 = T("2026-10-14 08:00"); day = "2026-10-14"
    w, cfg = usg.TempWatch(), prp.settings("fridge", {})
    evs = []
    seq = [3, 3, 7, 4, 3]                     # door opening: 10 min out of range – no alarm
    for i, t in enumerate(seq):
        evs += w.update(t0 + i * 600, t, day, cfg)
    assert not evs and w.values(t0 + 2400, cfg)["temp_alarm"] is False and w.values(t0 + 2400, cfg)["temp_out_today"] == 10
    for i in range(4):                       # 7 °C for 30 min → alarm after 15 min
        evs += w.update(t0 + 3000 + i * 600, 7.5, day, cfg)
    assert [e["type"] for e in evs] == ["out_of_range"] and w.values(t0 + 4800, cfg)["temp_alarm"]
    evs = w.update(t0 + 5400, 4, day, cfg)
    assert evs[0]["type"] == "back_in_range" and w.values(t0 + 5400, cfg)["temp_excursions_today"] == 1
    # door open: the delay only starts once it closes
    dw = usg.TempWatch()
    for i in range(4):
        dw.update(t0 + i * 600, 9, day, cfg, door_open=True)
    assert dw.values(t0 + 1800, cfg)["temp_alarm"] is False
    dw.update(t0 + 2400, 9, day, cfg); dw.update(t0 + 2400 + 900, 9, day, cfg)
    assert dw.values(t0 + 3300, cfg)["temp_alarm"] is True
    w.update(t0 + 86400, 3, "2026-10-15", cfg)
    assert w.s["log"][-1]["day"] == day and w.s["log"][-1]["max"] == 7.5 and w.s["log"][-1]["excursions"] == 1
    # silo hot spot: +4 °C in a day
    sw, scfg = usg.TempWatch(), prp.settings("silo", {})
    for h in range(26):
        sw.update(t0 + h * 3600, 20 + h * 0.17, day if h < 16 else "2026-10-15", scfg)
    v = sw.values(t0 + 25 * 3600, scfg)
    assert v["temp_rise_24h"] >= 3.9 and v["temp_hot_spot"] is True and "temp_alarm" not in v
    tr = usg.Trend()
    for i in range(13):
        tr.add(t0 + i * 600, 50 + i)          # +6 per hour
    assert abs(tr.rate_per_h(t0 + 7200, 1) - 6) < 0.01 and tr.change(t0 + 7200, 24) is None
    assert usg.bin_fill(300, 1000) == 70 and usg.water_level_cm(2500, 3000) == 50.0


def test_purpose_alerts():
    v = {"purpose": "Fridge / cold room", "purpose_group": "cold_chain", "purpose_severity": "critical",
         "temp_alarm": True, "temperature_now": 8.2, "temp_out_today": 25, "door_left_open": True, "door_current_s": 300,
         "load_ran_too_long": True, "load_label": "Compressor", "load_group": "cold_chain", "load_running_for_h": 3.5}
    al = alr.device_alerts("Fridge 3", "f3", v, "Kitchen")
    assert al["f3:temp_range"]["category"] == "cold_chain" and al["f3:temp_range"]["severity"] == "critical"
    assert "8.2 °C" in al["f3:temp_range"]["message"] and "5 min" in al["f3:left_open"]["message"]
    assert al["f3:load_long"]["severity"] == "critical" and "3.5 h" in al["f3:load_long"]["message"]
    al2 = alr.device_alerts("AC", "a1", {"purpose": "Air conditioner / heat pump", "purpose_group": "hvac",
                                         "load_after_hours": True, "load_label": "Air conditioner", "load_group": "hvac"})
    assert al2["a1:load_after"]["category"] == "energy"
    al3 = alr.device_alerts("B", "b", {"panic_active": True, "bin_full": True, "bin_fill": 85, "water_rising": True,
                                       "mains_outage": True, "load1_service_due": True, "load1_label": "Motor 1"})
    assert al3["b:panic"]["severity"] == "critical" and al3["b:bin_full"]["category"] == "facilities"
    assert al3["b:flood"]["severity"] == "critical" and "b:outage" in al3 and "b:load1_service" in al3
    assert {"cold_chain", "security", "energy", "facilities"} <= set(alr.effective_categories(
        {"alert_categories": ["safety"], "alert_categories_known": list(alr._CATEGORIES_V2)}))



def test_config_flow_selectors_have_no_none_options():
    """HA's selector schemas reject None values (e.g. unit_of_measurement=None) – the form then shows an empty Error."""
    src = (PKG / "config_flow.py").read_text()
    import re as _re
    assert "unit_of_measurement=unit" not in src
    for call in _re.findall(r"_float_box\(([^()]*)\)", src):
        args = [a.strip() for a in call.split(",")]
        assert len(args) < 3 or args[2] != "None", call

def test_modbus_templates():
    # Ecowitt WS90 on channels 1–10 (UC300): the raw values the UC300 reported
    rows, errs = mtp.plan("ecowitt_ws90", None, 1)
    assert not errs and [r["channel"] for r in rows] == list(range(1, 11)) and rows[0]["address"] == 357
    m, problems = chm.parse_channel_map(mtp.merge_map("1; Wind Speed; KM/h;1\nadc_1; Level; m", rows, "WS90"))
    assert not problems and m["modbus_chn_1"].name == "Light" and "adc_1" in m
    raw = {1: 4409, 2: 30, 3: 629, 4: 43, 5: 12, 6: 25, 7: 202, 8: 3, 9: 8576}
    got = {m[f"modbus_chn_{c}"].name: m[f"modbus_chn_{c}"].apply(v) for c, v in raw.items()}
    assert got["Light"] == 44090 and got["UV index"] == 3.0 and got["Temperature"] == 22.9 and got["Humidity"] == 43
    assert got["Wind speed"] == 1.2 and got["Wind direction"] == 202 and got["Gust speed"] == 2.5
    assert got["Rainfall"] == 0.3 and got["Pressure"] == 857.6
    assert m["modbus_chn_3"].apply(65535) is None and m["modbus_chn_3"].device_class == "temperature"
    tb = mtp.toolbox_table(mtp.TEMPLATES["ecowitt_ws90"], rows)
    assert "| 1 | Light | 144 | 357 | 1 | Holding Register(INT16) | AB | ☐ |" in tb

    # UC50x: CWT 7-in-1 NPK on slave 1 (channels 1–9) + WoMaster WS101LL on slave 2 (channels 10–16), as in ToolBox
    npk, errs = mtp.plan("cwt_soil_thcph", None, 1)
    assert not errs and [r["address"] for r in npk] == list(range(9)) and npk[0]["slave_id"] == 1
    assert [r["toolbox_name"] for r in npk] == ["Humidity", "Temperature", "Conductivity", "PH", "Nitrogen",
                                                 "Phosphorus", "Potassium", "Salinity", "TDS"]
    assert all(r["signed"] and r["type"] == "Input Register(INT16)" for r in npk)
    lvl_t = mtp.TEMPLATES["womaster_ws101ll"]
    lvl, errs = mtp.plan("womaster_ws101ll", [r.key for r in lvl_t.regs], 10, 2)
    assert not errs and [(r["channel"], r["toolbox_name"], r["address"]) for r in lvl] == [
        (10, "Unit Type", 2), (11, "Decimal Points", 3), (12, "Measure Value", 4), (13, "Zero Point", 5),
        (14, "Full Point", 6), (15, "Offset", 13), (16, "SlaveID", 2000)]
    assert [r["name"] for r in mtp.plan("womaster_ws101ll", None, 10, 2)[0]] == [
        "Level unit code", "Level decimal points", "Water level", "Level full point"]          # defaults
    t_npk = mtp.TEMPLATES["cwt_soil_thcph"]
    text = mtp.merge_map(mtp.merge_map("", npk, mtp.block_title(t_npk, npk)), lvl, mtp.block_title(lvl_t, lvl))
    m, problems = chm.parse_channel_map(text)
    assert not problems and len(m) == 16 and m["modbus_chn_1"].name == "Soil moisture"
    assert m["modbus_chn_2"].apply(254) == 25.4 and m["modbus_chn_2"].apply(0xFF9B) == -10.1
    assert m["modbus_chn_4"].apply(30) == 3.0 and m["modbus_chn_4"].device_class == "ph"
    assert m["modbus_chn_3"].device_class == "conductivity" and m["modbus_chn_5"].name == "Soil nitrogen (N)"
    assert m["modbus_chn_12"].name == "Water level" and m["modbus_chn_12"].device_class == "distance"
    assert m["modbus_chn_14"].apply(3000) == 3000 and m["modbus_chn_16"].apply(2) == 2
    assert "Input Register(INT16) | AB | ☑ |" in mtp.toolbox_table(t_npk, npk)
    assert mtp.plan("cwt_soil_thcph", None, 9)[1]                     # 9 values from channel 9 do not fit
    again = mtp.merge_map(text, lvl, mtp.block_title(lvl_t, lvl))     # re-applying replaces, does not duplicate
    assert len(chm.parse_channel_map(again)[0]) == 16 and again.count("WoMaster") == 1

    # remove a template again: its channels and title go, other lines stay
    left = mtp.remove_from_map(text, 10, 16, mtp.block_title(lvl_t, lvl))
    assert set(chm.parse_channel_map(left)[0]) == {f"modbus_chn_{c}" for c in range(1, 10)}
    assert "WoMaster" not in left and "CWT" in left
    old = "# Ecowitt WS90 / WN90LP weather station (RS485) (slave 144)\n1; Light; lx; 10"   # 0.26.0 format
    assert mtp.remove_from_map(old, 1, 10, None, mtp.TEMPLATES["ecowitt_ws90"].name) == ""
    assert "Ecowitt" in mtp.describe_applied([{"template": "ecowitt_ws90", "first": 1, "last": 10, "slave_id": 1}])
    assert mtp.plan("nope", None, 1)[1] and mtp.plan("ecowitt_ws90", [], 1)[1]


def test_luxpower_template_uc100():
    t = mtp.TEMPLATES["luxpower_lxp"]
    assert mtp.max_channels("UC100") == 32 and mtp.max_channels("UC300") == 32 and mtp.max_channels("UC501") == 16
    assert mtp.plan("luxpower_lxp", None, 1, 1)[1]                                   # 26 values do not fit a UC50x
    rows, errs = mtp.plan("luxpower_lxp", None, 1, 1, max_channels=mtp.max_channels("UC100"))
    assert not errs and len(rows) == len(t.defaults()) == 26 and rows[-1]["channel"] == 26
    by = {r["toolbox_name"]: r for r in rows}
    assert by["Epv1_all"]["quantity"] == 2 and by["Epv1_all"]["type"] == "Input Register(INT32)"
    assert by["Epv1_all"]["byte_order"] == "CDAB" and by["Vbat"]["type"] == "Input Register(INT16)"
    assert by["SOC"]["address"] == 5 and "SOH" not in by
    rows, errs = mtp.plan("luxpower_lxp", [k for k in t.defaults() if k != "fault"] + ["soh"], 1, 1, max_channels=32)
    m, problems = chm.parse_channel_map(mtp.merge_map("", rows, mtp.block_title(t, rows)))
    assert not errs and not problems and len(m) == 26
    ch = {c.name: c for c in m.values()}
    assert ch["Battery SOC"].apply(0x6450) == 80 and ch["Battery SOH"].apply(0x6450) == 100
    assert ch["Battery voltage"].apply(532) == 53.2
    assert ch["Battery current"].apply(0xFF38) == -2.0 and ch["Cell voltage max"].apply(3345) == 3.345
    assert ch["PV1 energy total"].apply(123456) == 12345.6 and ch["PV1 energy total"].state_class == "total_increasing"
    assert ch["Grid import total"].device_class == "energy" and ch["Battery SOC"].device_class == "battery"
    assert mtp.plan("luxpower_lxp", [r.key for r in t.regs], 1, 1, max_channels=32)[1]   # 46 > 32 channels



def test_modbus_config_downlinks():
    # byte-identical to Milesight's uc100-encoder.js / uc100-v2-encoder.js (checked with node)
    cmds = (mcf.channel_cmd(1, 1, 0, 2) + mcf.channel_cmd(28, 1, 40, 6, 2) + mcf.channel_cmd(11, 1, 98, 2, 1, True)
            + mcf.name_cmd(1, "State") + mcf.remove_cmd(5))
    assert cmds.hex() == "ffef01010100000201ffef011c0128000602ffef010b0162000211ffef0201055374617465ffef0005"
    assert mcf.serial_cmd(19200, 8, 1, "N").hex() == "f978004b0000080100"
    assert mcf.parse_serial("8N1") == (8, "N", 1)
    assert mcf.register_type("input", 1, "AB") == 2 and mcf.register_type("input", 2, "CDAB") == 6
    assert mcf.register_type("holding", 1, "AB") == 14 and mcf.register_type("holding", 2, "ABCD") == 16
    assert mcf.register_type("input", 2, "CDAB", True) == 12 and mcf.kind_of("Holding Register(INT16)") == "holding"
    assert mcf.can_push("UC100") and mcf.can_push("UC100-V2") and not mcf.can_push("UC300")
    assert len(mcf.name_cmd(3, "A very long channel name")) == 5 + 16
    # the LuxPower template on a UC100: 32 channels + names, packed into downlinks of at most 50 bytes
    rows, errs = mtp.plan("luxpower_lxp", None, 1, 1, max_channels=mtp.max_channels("UC100"))
    assert not errs and len(rows) == 26 and mtp.max_channels("UC100") == 32
    commands = mcf.template_commands(rows)
    assert len(commands) == 52 and commands[0] == ("modbus_channel_1", bytes.fromhex("ffef01010100000201"))
    by = {r["toolbox_name"]: r for r in rows}
    epv = dict(commands)[f"modbus_channel_{by['Epv1_all']['channel']}"]
    assert epv[7] == 6 and epv[8] == 0x02                       # INT32 CDAB, quantity 2
    ibat = dict(commands)[f"modbus_channel_{by['BatCurrent']['channel']}"]
    assert ibat[8] == 0x11                                       # signed, 1 register
    frames = mcf.pack(commands)
    assert all(sum(len(c) for _, c in f) <= 50 for f in frames) and sum(len(f) for f in frames) == 52
    assert [c for f in frames for c in f] == commands             # order kept
    assert mcf.remove_commands(3, 4) == [("modbus_remove_3", b"\xff\xef\x00\x03"), ("modbus_remove_4", b"\xff\xef\x00\x04")]
    # the UC100 echoes the commands: decoded, not mistaken for measurements
    up = dec.decode_uc100(bytes.fromhex("feef01060100000612feef020606535441544531ff190102023412"))
    assert up["modbus_channels_set"][0] == {"channel": 6, "slave_id": 1, "address": 0, "type": 6, "quantity": 2,
                                            "signed": True}
    assert up["modbus_channels_named"][0]["name"] == "STATE1" and up["modbus_chn_2"] == 0x1234
    assert dec.decode_uc100_v2(bytes.fromhex("ffef0006"))["modbus_channels_removed"] == [6]


def test_setpoints():
    sp = spt.DEVICE["tank_low_pct"]
    assert spt.clamp(sp, 33.4) == 33 and spt.clamp(sp, 120) == 90 and spt.clamp(sp, -5) == 0
    t = spt.DEVICE["p_temp_high"]
    assert spt.clamp(t, 5.2) == 5.0 and spt.clamp(t, 5.3) == 5.5 and spt.key("irr_target") == "sp_irr_target"
    assert set(spt.hub_values(irr.irrigation_config({}))) == set(spt.HUB)


def test_edit_applied_template():
    t = mtp.TEMPLATES["luxpower_lxp"]
    rows, _ = mtp.plan("luxpower_lxp", None, 1, 1, max_channels=32)
    sent = {label: cmd.hex() for label, cmd in mcf.template_commands(rows)}
    applied = {"template": t.key, "first": 1, "last": len(rows), "slave_id": 1, "keys": [r["key"] for r in rows],
               "prefix": "", "sent_to_device": True, "sent": sent}
    d = mtp.applied_defaults(t, applied)
    assert d["values"] == t.defaults() and d["first_channel"] == 1 and d["slave_id"] == 1
    # add one value at the end: only that channel (and its name) is sent again
    rows2, _ = mtp.plan("luxpower_lxp", t.defaults() + ["bms_warning"], 1, 1, max_channels=32)
    changed = mcf.changed_commands(mcf.template_commands(rows2), sent)
    assert {c[0] for c in changed} == {f"modbus_channel_{len(rows2)}", f"modbus_name_{len(rows2)}"}
    # change the address: every channel changes, names do not
    rows3, _ = mtp.plan("luxpower_lxp", None, 1, 2, max_channels=32)
    changed = mcf.changed_commands(mcf.template_commands(rows3), sent)
    assert len(changed) == len(rows3) and all(l.startswith("modbus_channel_") for l, _ in changed)
    assert mcf.changed_commands(mcf.template_commands(rows), sent) == []
    # records saved before 0.30 (names only, with a prefix)
    old = {"template": "cwt_soil_thcph", "first": 11, "last": 16, "slave_id": 2,
           "values": ["Field Soil moisture", "Field Soil temperature", "Field Soil pH"]}
    d = mtp.applied_defaults(mtp.TEMPLATES["cwt_soil_thcph"], old)
    assert d["values"] == ["moisture", "temperature", "ph"] and d["prefix"] == "Field" and d["first_channel"] == 11


def test_bundled_dashboard_templates_render():
    """The markdown cards of the shipped dashboards render (phone-friendly: no wide tables)."""
    import jinja2
    import yaml
    S = types.SimpleNamespace
    env = jinja2.Environment(extensions=["jinja2.ext.loopcontrols"])
    env.filters["int"] = lambda v, d=0: int(float(v)) if str(v).replace(".", "", 1).lstrip("-").isdigit() else d
    env.filters["timestamp_custom"] = lambda v, f: "17 Oct 09:00"
    sensors = [
        S(state="72", attributes={"kind": "comfort", "area": "Lab", "temperature": 22.5, "humidity": 48, "co2": None}),
        S(state="40", attributes={"area": "Lab", "hourly_today": [0] * 7 + [30, 80] + [None] * 15,
                                   "hourly_yesterday": [0] * 24, "occupied_now": True, "people_now": 2,
                                   "utilisation_today": None}),
        S(state="1200", attributes={"milesight_role": "tank", "device": "Tank 1", "area": "Yard", "fill": 34.6,
                                     "capacity_l": 5000, "usage_per_day": 210.4, "days_left": 8, "low": False,
                                     "sudden_drop": False}),
        S(state="1", attributes={"milesight_role": "alerts_open", "alerts": [
            {"severity": "critical", "title": "Pump dry-run", "message": "2.1 A", "since": "08:10", "status": "open"}]}),
        S(state="12", attributes={"milesight_role": "pump", "device": "Borehole", "area": None, "running": True,
                                   "dry_run": True, "overload": False, "short_cycling": False, "current": 2.1,
                                   "normal_current": 9.8, "starts_last_hour": 1}),
        S(state="55", attributes={"milesight_role": "pivot", "device": "Pivot 1", "status": "running", "angle": 198.2,
                                   "speed": 12, "finish_in_h": 3.24}),
        S(state="irrigate", attributes={"milesight_role": "irrigation", "site": "Farm", "minutes": 40, "reason": "dry",
                                         "soil_moisture": 18, "target_moisture": 30, "rain_window_h": 24,
                                         "rain_mm": 0.4, "rain_probability": 10, "forecast_error": None}),
    ]
    states = S(sensor=sensors, binary_sensor=[S(state="off", attributes={"milesight_role": "frost", "expected": False})])
    out = {}
    for f in ("building_analytics", "tanks_and_alerts", "farm"):
        cfg = yaml.safe_load((PKG.parents[1] / "dashboards" / f"{f}.yaml").read_text(encoding="utf-8"))
        for view in cfg["views"]:
            for sec in view["sections"]:
                for card in sec["cards"]:
                    if card["type"] == "markdown":
                        text = env.from_string(card["content"]).render(states=states, as_timestamp=lambda v: 0)
                        assert "|---|" not in text, (f, text)          # no wide tables any more
                        out[f"{f}:{sec['cards'][0]['heading']}"] = text
    assert "**Lab** · 🟡 72 / 100" in out["building_analytics:Comfort per area"]
    assert "🌡️ 22.5 °C · 💧 48 %" in out["building_analytics:Comfort per area"]
    assert "**Lab** · 🧑 2 · 40 % today" in out["building_analytics:Occupancy today"]
    assert "closed today / outside opening hours" in out["building_analytics:Utilisation today (opening hours)"]
    assert "🟦🟦🟦⬜⬜⬜⬜⬜⬜⬜ **34 %**" in out["tanks_and_alerts:Tanks and silos"]
    assert 'title="Pump dry-run"' in out["tanks_and_alerts:Open alerts"]
    assert "**DRY-RUN**" in out["farm:Pumps"] and "finishes in 3.2 h" in out["farm:Centre pivots"]
    assert "Irrigate about 40 min" in out["farm:Irrigation and frost"]


# ---------------------------------------------------------------- built-in network server (lns/)
def _lns():
    sub = types.ModuleType("mlw.lns"); sub.__path__ = [str(PKG / "lns")]; sys.modules["mlw.lns"] = sub
    import importlib
    return (importlib.import_module("mlw.lns.crypto"), importlib.import_module("mlw.lns.phy"),
            importlib.import_module("mlw.lns.semtech"), importlib.import_module("mlw.lns.server"),
            importlib.import_module("mlw.lns.region"))


class _Device:
    """A LoRaWAN 1.0.x end device, written from the device's point of view (decrypts the join-accept with AES
    *encrypt*, derives its own keys) to check the server end to end."""
    def __init__(self, crypto, phy, dev_eui, join_eui, app_key):
        self.c, self.p = crypto, phy
        self.dev_eui, self.join_eui, self.app_key = dev_eui, join_eui, app_key
        self.nonce, self.fcnt, self.addr, self.nwk, self.app = 0x1234, 0, None, None, None

    def join_request(self):
        self.nonce += 1
        msg = b"\x00" + bytes.fromhex(self.join_eui)[::-1] + bytes.fromhex(self.dev_eui)[::-1] \
            + self.nonce.to_bytes(2, "little")
        return msg + self.c.aes_cmac(self.app_key, msg)[:4]

    def join_accept(self, phy):
        clear = self.c.join_accept_decrypt(self.app_key, phy)
        body, mic = clear[:-4], clear[-4:]
        assert self.c.aes_cmac(self.app_key, phy[:1] + body)[:4] == mic, "join-accept MIC"
        jn, nid, self.addr = body[0:3], body[3:6], int.from_bytes(body[6:10], "little")
        self.dl, self.rxdelay, self.cflist = body[10], body[11], body[12:]
        self.nwk, self.app = self.c.session_keys(self.app_key, jn, nid, self.nonce.to_bytes(2, "little"))
        self.fcnt = 0

    def uplink(self, port, payload, confirmed=False, fopts=b"", ack=False, adr_ack_req=False):
        enc = self.c.crypt_payload(self.app if port else self.nwk, payload, self.addr, self.fcnt, True)
        frame = self.p.build_data(self.p.CONF_UP if confirmed else self.p.UNCONF_UP, self.addr, self.fcnt, ack=ack,
                                  fopts=fopts, fport=port, enc_payload=enc, adr_ack_req=adr_ack_req)
        frame += self.c.data_mic(self.nwk, frame, self.addr, self.fcnt, True)
        self.fcnt += 1
        return frame

    def downlink(self, phy):
        df = self.p.parse_data(phy)
        assert df.dev_addr == self.addr
        assert self.c.data_mic(self.nwk, df.signed, self.addr, df.fcnt16, False) == df.mic, "downlink MIC"
        data = self.c.crypt_payload(self.app if df.fport else self.nwk, df.frm_payload, self.addr, df.fcnt16, False)
        return df, data


def _rxpk(phy, rssi=-90, snr=7.5, tmst=1_000_000, freq=868.1, datr="SF7BW125"):
    return {"tmst": tmst, "freq": freq, "chan": 0, "rfch": 0, "stat": 1, "modu": "LORA", "datr": datr,
            "codr": "4/5", "rssi": rssi, "lsnr": snr, "size": len(phy), "data": base64.b64encode(phy).decode()}


def test_lns_crypto_reference_vector():
    crypto, phy, *_ = _lns()
    # lora-packet's published example: "test" on FPort 1, DevAddr 49be7df1, FCnt 2
    p = bytes.fromhex("40F17DBE4900020001954378762B11FF0D")
    df = phy.parse_data(p)
    nwk, app = bytes.fromhex("44024241ed4ce9a68c6a8bc055233fd3"), bytes.fromhex("ec925802ae430ca77fd3dd73cb2cc588")
    assert df.dev_addr == 0x49BE7DF1 and df.fcnt16 == 2 and df.fport == 1
    assert crypto.data_mic(nwk, df.signed, df.dev_addr, 2, True) == df.mic
    assert crypto.crypt_payload(app, df.frm_payload, df.dev_addr, 2, True) == b"test"
    assert phy.full_fcnt(None, 5) == 5 and phy.full_fcnt(0x1FFFE, 3) == 0x20003 and phy.full_fcnt(70000, 4463) == 4463 + 65536


def test_lns_semtech_protocol():
    _c, _p, sem, *_ = _lns()
    gw = bytes.fromhex("24e124fffefa2994")
    push = b"\x02\xab\xcd\x00" + gw + json.dumps({"rxpk": [{"data": "QA==", "stat": 1}], "stat": {"rxok": 3}}).encode()
    d = sem.parse(push)
    assert d.ident == sem.PUSH_DATA and d.gateway == "24e124fffefa2994" and d.body["stat"]["rxok"] == 3
    assert sem.ack(d) == b"\x02\xab\xcd\x01"
    pull = sem.parse(b"\x02\x01\x02\x02" + gw)
    assert pull.ident == sem.PULL_DATA and sem.ack(pull) == b"\x02\x01\x02\x04"
    pk = sem.txpk(b"\x60\x01", 868.1, "SF7BW125", 4_294_967_000 + 3_000_000)
    assert pk["tmst"] == (4_294_967_000 + 3_000_000) & 0xFFFFFFFF and pk["ipol"] is True and pk["size"] == 2
    dg, tok = sem.pull_resp(pk, 2, b"\x00\x07")
    assert dg[:4] == b"\x02\x00\x07\x03" and json.loads(dg[4:])["txpk"]["data"] == "YAE="
    assert sem.rxpk_phy({"stat": -1, "data": "QA=="}) is None
    assert sem.rxpk_radio({"rsig": [{"rssic": -101, "lsnr": -3.5}]})["rssi"] == -101
    ack = sem.parse(b"\x02\x00\x07\x05" + gw + b'{"txpk_ack":{"error":"TOO_LATE"}}')
    assert ack.ident == sem.TX_ACK and ack.body["txpk_ack"]["error"] == "TOO_LATE"


def test_lns_join_uplink_downlink():
    crypto, phy, sem, srv, region = _lns()
    key = bytes.fromhex("5572404c696e6b4c6f52613230313823")
    dev = _Device(crypto, phy, "24e124136b316453", "24e124c0002a0001", key)
    keys = {"24e124136b316453": srv.DeviceKeys("24e124136b316453", key)}
    ns = srv.NetworkServer(lambda eui: keys.get(eui), srv.Settings(farm_id=7, rx1_delay=3))
    gw1, gw2 = "24e124fffefa2994", "24e124fffe000001"
    ns.gateway_seen(gw1, 100.0, pull=True)
    ns.gateway_seen(gw2, 100.0, pull=True)

    # join heard by two gateways: one join-accept through the stronger one, 5 s after the request
    jr = dev.join_request()
    assert ns.receive(gw1, _rxpk(jr, -110, -2.0, tmst=10_000_000), 101.0) == jr
    assert ns.receive(gw2, _rxpk(jr, -80, 9.0, tmst=50_000_000), 101.1) is None          # copy
    ev = ns.process(jr, 101.3)
    kinds = [e.kind for e in ev]
    assert kinds == ["join", "tx"], kinds
    tx = ev[1].data["tx"]
    assert tx.gateway == gw2 and tx.tmst == 55_000_000 and tx.freq == 868.1 and tx.datr == "SF7BW125"
    dev.join_accept(tx.phy)
    assert dev.addr >> 16 == 7 and dev.rxdelay == 3 and dev.cflist[:3] == (8671000).to_bytes(3, "little")
    assert ns.has_session("24e124136b316453") and ns.receive(gw1, _rxpk(jr), 102.0) is None   # late copy ignored

    # same DevNonce again → replay refused
    dev.nonce -= 1
    jr2 = dev.join_request()
    ns.gateway_seen(gw1, 200.0, pull=True); ns.gateway_seen(gw2, 200.0, pull=True)
    ns.receive(gw1, _rxpk(jr2), 200.0)
    assert ns.process(jr2, 200.3)[0].kind == "join_rejected"
    dev.nonce += 0
    # wrong key → refused, unknown device → offered
    bad = _Device(crypto, phy, "24e124136b316453", "24e124c0002a0001", bytes(16))
    jr3 = bad.join_request(); jr3 = jr3[:-4] + crypto.aes_cmac(bytes(16), jr3[:-4])[:4]
    ns.gateway_seen(gw1, 201.0, pull=True); ns.gateway_seen(gw2, 201.0, pull=True)
    ns.receive(gw1, _rxpk(jr3), 201.0)
    assert "wrong AppKey" in ns.process(jr3, 201.3)[0].data["reason"]
    other = _Device(crypto, phy, "24e1240000000099", "0000000000000000", key).join_request()
    ns.gateway_seen(gw1, 202.0, pull=True); ns.gateway_seen(gw2, 202.0, pull=True)
    ns.receive(gw1, _rxpk(other), 202.0)
    e = ns.process(other, 202.3)[0]
    assert e.kind == "join_unknown" and e.dev_eui == "24e1240000000099"

    # uplink (AM307-style payload) decoded and delivered once, best gateway first
    payload = bytes.fromhex("0367f600046882")
    up = dev.uplink(85, payload)
    ns.gateway_seen(gw1, 300.0, pull=True); ns.gateway_seen(gw2, 300.0, pull=True)
    ns.receive(gw1, _rxpk(up, -100, 1.0, tmst=20_000_000), 300.0)
    ns.gateway_seen(gw1, 300.05, pull=True); ns.gateway_seen(gw2, 300.05, pull=True)
    ns.receive(gw2, _rxpk(up, -70, 10.0, tmst=60_000_000), 300.05)
    ev = ns.process(up, 300.3)
    assert [e.kind for e in ev] == ["uplink"]
    u = ev[0].data
    assert u["payload"] == payload and u["fport"] == 85 and u["fcnt"] == 0 and u["gateways"][0]["id"] == gw2
    assert u["sf"] == 7 and u["frequency"] == 868100000
    # replay of the same frame later → nothing
    ns.gateway_seen(gw1, 400.0, pull=True); ns.gateway_seen(gw2, 400.0, pull=True)
    ns.receive(gw1, _rxpk(up), 400.0)
    assert [e.kind for e in ns.process(up, 400.3)] == []

    # queued downlink goes out in RX1 after the next uplink, 3 s later, through the best gateway
    assert ns.enqueue("24E124136B316453", 85, bytes.fromhex("ff03b004"), confirmed=True, item_id="cmd1")
    up2 = dev.uplink(85, payload)
    ns.gateway_seen(gw1, 500.0, pull=True); ns.gateway_seen(gw2, 500.0, pull=True)
    ns.receive(gw1, _rxpk(up2, tmst=70_000_000), 500.0)
    ev = ns.process(up2, 500.3)
    assert [e.kind for e in ev] == ["uplink", "tx"]
    tx = ev[1].data["tx"]
    assert tx.tmst == 73_000_000 and ev[1].data["id"] == "cmd1" and ev[1].data["confirmed"]
    df, data = dev.downlink(tx.phy)
    assert data == bytes.fromhex("ff03b004") and df.fport == 85 and df.mtype == phy.CONF_DOWN and df.fcnt16 == 0
    # the device acknowledges in its next uplink → ack event
    up3 = dev.uplink(85, payload, ack=True)
    ns.gateway_seen(gw1, 600.0, pull=True); ns.gateway_seen(gw2, 600.0, pull=True)
    ns.receive(gw1, _rxpk(up3), 600.0)
    ev = ns.process(up3, 600.3)
    assert ev[0].kind == "ack" and ev[0].data["acknowledged"] is True and ev[0].data["id"] == "cmd1"

    # confirmed uplink + LinkCheckReq + DeviceTimeReq in FOpts → ACK with both answers, no payload
    up4 = dev.uplink(85, payload, confirmed=True, fopts=bytes([0x02, 0x0D]))
    ns.gateway_seen(gw1, 1_760_000_000.0, pull=True); ns.gateway_seen(gw2, 1_760_000_000.0, pull=True)
    ns.receive(gw2, _rxpk(up4, -75, 8.0, tmst=90_000_000), 1_760_000_000.0)
    ev = ns.process(up4, 1_760_000_000.5)
    tx = next(e for e in ev if e.kind == "tx").data["tx"]
    df, data = dev.downlink(tx.phy)
    assert df.ack and df.fport is None and df.fopts[0] == 0x02 and df.fopts[1] == 15 and df.fopts[2] == 1
    gps = int.from_bytes(df.fopts[4:8], "little")
    assert gps == int(1_760_000_000.5 - 315964800 + 18) and df.fcnt16 == 1

    # frame with a broken MIC, and a frame from another network (unknown address)
    bad_up = bytearray(dev.uplink(85, payload)); bad_up[-1] ^= 0xFF
    ns.gateway_seen(gw1, 700.0, pull=True); ns.gateway_seen(gw2, 700.0, pull=True)
    ns.receive(gw1, _rxpk(bytes(bad_up)), 700.0)
    assert ns.process(bytes(bad_up), 700.3)[0].kind == "mic_failed"
    foreign = phy.build_data(phy.UNCONF_UP, 0x26011234, 1, fport=1, enc_payload=b"x") + b"\0\0\0\0"
    ns.gateway_seen(gw1, 701.0, pull=True); ns.gateway_seen(gw2, 701.0, pull=True)
    ns.receive(gw1, _rxpk(foreign), 701.0)
    assert ns.process(foreign, 701.3)[0].kind == "foreign"

    # too long for the data rate → dropped with a reason; gateway that never pulled → no route
    assert ns.enqueue("24e124136b316453", 85, bytes(60))
    up5 = dev.uplink(85, payload)
    ns.gateway_seen(gw1, 800.0, pull=True); ns.gateway_seen(gw2, 800.0, pull=True)
    ns.receive(gw1, _rxpk(up5, datr="SF12BW125"), 800.0)
    ev = ns.process(up5, 800.3)
    assert any(e.kind == "dropped" and "too long" in e.data["reason"] for e in ev)

    # state survives a restart (sessions only, keys in Home Assistant's storage), info has no keys
    state = json.loads(json.dumps(ns.to_dict()))
    ns2 = srv.NetworkServer(lambda eui: keys.get(eui), srv.Settings(farm_id=7), state)
    info = ns2.session_info("24e124136b316453")
    assert info["fcnt_up"] == dev.fcnt - 1 and "nwk_s_key" not in info and "app_s_key" not in json.dumps(info)
    ns2.gateway_seen(gw1, 900.0, pull=True)
    up6 = dev.uplink(85, payload)
    ns2.gateway_seen(gw1, 900.0, pull=True); ns2.gateway_seen(gw2, 900.0, pull=True)
    ns2.receive(gw1, _rxpk(up6), 900.0)
    assert ns2.process(up6, 900.3)[0].kind == "uplink"
    # a confirmed uplink repeated by the device (it missed our ACK) is ACKed again but delivered once
    up7 = dev.uplink(85, payload, confirmed=True)
    for t in (1000.0, 1006.0):
        ns2.gateway_seen(gw1, t, pull=True)
        ns2.receive(gw1, _rxpk(up7), t)
        ev = ns2.process(up7, t + 0.3)
        assert [e.kind for e in ev] == (["uplink", "tx"] if t == 1000.0 else ["tx"]), ev
        assert dev.downlink(ev[-1].data["tx"].phy)[0].ack
    assert region.EU868.rx1(868.1, "SF7BW250")[1] == "SF7BW250"
    assert region.airtime_ms(7, 13) < region.airtime_ms(12, 13) and 40 < region.airtime_ms(7, 13) < 50


def test_smart_alerts_rota_snooze_summary():
    # on-call rota: weekdays by day, an overnight shift, weekends; first matching line wins
    rota = alr.parse_rota("""
        Mon-Fri 07:00-17:00: notify.mobile_app_juan
        weekdays 17-07: notify.mobile_app_piet   # overnight
        Weekend: notify.mobile_app_sam, notify.mobile_app_ann
    """)
    assert len(rota) == 3 and rota[2].targets == ("notify.mobile_app_sam", "notify.mobile_app_ann")
    cfg = alr.AlertSettings(primary=["notify.boss"], rota=rota, backup=["notify.b1", "notify.b2"], escalate_min=10,
                            category_quiet=alr.parse_category_quiet("building: 18-07\nsafety: none"),
                            quiet_start=22, quiet_end=6,
                            dashboards={"tank": "/milesight-tanks", "*": "/building-farm"})
    fri_day, fri_night = datetime(2026, 10, 16, 9, 0, tzinfo=TZ), datetime(2026, 10, 16, 23, 0, tzinfo=TZ)
    sat_early, sat_noon = datetime(2026, 10, 17, 5, 0, tzinfo=TZ), datetime(2026, 10, 17, 12, 0, tzinfo=TZ)
    assert cfg.first_line(fri_day) == ["notify.mobile_app_juan"]
    assert cfg.first_line(fri_night) == ["notify.mobile_app_piet"]
    assert cfg.first_line(sat_early) == ["notify.mobile_app_piet"]          # Friday's night shift runs into Saturday
    assert cfg.first_line(sat_noon) == ["notify.mobile_app_sam", "notify.mobile_app_ann"]
    assert alr.AlertSettings(primary=["notify.boss"]).first_line(fri_day) == ["notify.boss"]
    evening = datetime(2026, 10, 16, 19, 0, tzinfo=TZ)
    assert cfg.quiet("building", evening) and not cfg.quiet("tank", evening)
    assert cfg.quiet("tank", fri_night) and not cfg.quiet("safety", fri_night)
    for bad in ("Mon-Fri 07-17 notify.x", "Funday 07-17: notify.x", "Mon 25-26: notify.x"):
        try:
            alr.parse_rota(bad)
            raise AssertionError(bad)
        except alr.RotaError:
            pass
    try:
        alr.parse_category_quiet("kitchen: 18-07")
        raise AssertionError("unknown category")
    except alr.RotaError:
        pass

    # escalation one person at a time along the backup list; Open dashboard link per category
    eng = alr.AlertEngine()
    t = T("2026-10-16 09:00")
    low = {"t1:tank_low": {"title": "Tank low – Diesel", "message": "low", "severity": "warning", "category": "tank"}}
    out = eng.update(low, t, fri_day, cfg)
    assert out[0]["targets"] == ["notify.mobile_app_juan"] and out[0]["url"] == "/milesight-tanks"
    d = alr.notify_data(out[0])["data"]
    assert [a["title"] for a in d["actions"]] == ["Acknowledge", "Snooze 1 h", "Open dashboard"]
    assert d["actions"][2] == {"action": "URI", "title": "Open dashboard", "uri": "/milesight-tanks"}
    assert d["clickAction"] == d["url"] == "/milesight-tanks"
    out = eng.update(low, t + 600, fri_day, cfg)
    assert out[0]["kind"] == "escalated" and out[0]["targets"] == ["notify.b1", "notify.mobile_app_juan"]
    out = eng.update(low, t + 1200, fri_day, cfg)
    assert out[0]["targets"] == ["notify.b1", "notify.b2", "notify.mobile_app_juan"]
    assert eng.update(low, t + 1800, fri_day, cfg) == []                 # end of the list, no reminders set

    # snooze: no escalation for an hour, then 'still active' to everyone notified so far
    eng2 = alr.AlertEngine()
    out = eng2.update(low, t, fri_day, cfg)
    aid2 = out[0]["id"]
    sn = eng2.snooze(aid2, t + 60, 60, "Juan")
    assert sn[0]["kind"] == "snoozed" and "Snoozed for 1 h by Juan" in sn[0]["message"]
    assert [a["title"] for a in alr.notify_data(sn[0])["data"]["actions"]] == ["Acknowledge", "Open dashboard"]
    assert eng2.update(low, t + 1200, fri_day, cfg) == []                # would have escalated at +10 min
    out = eng2.update(low, t + 3700, fri_day, cfg)
    assert out[0]["kind"] == "snooze_over" and out[0]["title"].startswith("Still active")
    out = eng2.update(low, t + 3700 + 600, fri_day, cfg)
    assert out[0]["kind"] == "escalated"                                  # the clock restarted after the snooze
    assert eng2.snooze("nope", t, 60) == []

    # weekly summary: counts, categories, noisiest sources, mean time to acknowledge
    eng3 = alr.AlertEngine()
    leak = {"d9:leak_active": {"title": "Water leak – Kitchen", "message": "m", "severity": "critical",
                               "category": "safety"}}
    a1 = eng3.update(low, t, fri_day, cfg)[0]["id"]
    eng3.acknowledge(a1, t + 300, "Juan")                                  # 5 min
    eng3.update({**low, **leak}, t + 400, fri_day, cfg)
    leak_id = eng3.alerts["d9:leak_active"]["id"]
    eng3.acknowledge(leak_id, t + 400 + 900, "Sam")                        # 15 min
    eng3.update({}, t + 2000, fri_day, cfg)
    eng3.update({}, t + 2400, fri_day, cfg)
    eng3.update(low, t + 2500, fri_day, cfg)                              # tank low flaps back
    s = eng3.summary(t + 3000, names={"t1": "Diesel tank"})
    assert s["alerts"] == 2 and s["critical"] == 1 and s["mtta_min"] == 10.0 and s["acknowledged"] == 2, s
    assert s["by_category"] == {"tank": 1, "safety": 1}
    assert s["noisiest"][0] == {"source": "Diesel tank", "alerts": 1, "flaps": 1}
    text = alr.summary_text(s)
    assert "2 alerts (1 critical)" in text and "Mean time to acknowledge: 10 min" in text
    assert "Diesel tank 1 (+1 repeats)" in text
    assert alr.summary_text(alr.AlertEngine().summary(t)).startswith("No alerts")
    st = json.loads(json.dumps(eng3.to_dict()))
    assert alr.AlertEngine(st).summary(t + 3000)["alerts"] == 2           # survives a restart
    assert eng3.summary(t + 9 * 86400)["alerts"] == 0                      # only the last 7 days


def test_battery_forecast():
    bat = _load("battery")
    fc = bat.BatteryForecast()
    day0, t0 = 740000, T("2026-01-01 12:00")
    assert fc.forecast(day0, 20)["reason"] == "no battery readings yet"
    for i in range(10):
        fc.add(day0 + i, 100, t0 + i * 86400)
    assert fc.forecast(day0 + 9, 20)["reason"].startswith("collecting")
    for i in range(10, 40):
        fc.add(day0 + i, 100, t0 + i * 86400)
    f = fc.forecast(day0 + 39, 20)
    assert f["days_left"] is None and f["method"] == "flat" and "no drop yet" in f["reason"]
    # 1 % every 6 days from day 40: ~5 % per month
    fc2 = bat.BatteryForecast()
    for i in range(0, 120):
        fc2.add(day0 + i, 100 - i // 6, t0 + i * 86400)
        fc2.add(day0 + i, 100 - i // 6, t0 + i * 86400 + 600)      # two readings a day: lowest kept, count 2
    f = fc2.forecast(day0 + 119, 20)
    assert f["method"] == "trend" and -5.5 < f["pct_per_month"] < -4.5 and fc2.days[-1][2] == 2
    now_pct = 100 - 119 // 6
    assert abs(f["days_left"] - (now_pct - 20) * 6) <= 6 and f["replace_on"] == day0 + 119 + f["days_left"]
    # reporting twice as often now → drains twice as fast
    f2 = fc2.forecast(day0 + 119, 20, uplinks_per_day_now=4)
    assert abs(f2["days_left"] - f["days_left"] / 2) <= 3 and "adjusted" in f2["method"]
    # new batteries: history restarts, replacement noted; a jump to a low value is not a replacement
    fc2.add(day0 + 120, 55, t0 + 120 * 86400)
    assert fc2.add(day0 + 121, 100, t0 + 121 * 86400) is True and len(fc2.days) == 1 and fc2.replaced
    fc3 = bat.BatteryForecast()
    fc3.add(day0, 30, t0)
    assert fc3.add(day0 + 1, 60, t0 + 86400) is False
    assert fc3.forecast(day0 + 1, 40)["method"] is None
    low = bat.BatteryForecast({"days": [[day0, 15, 1]]})
    assert low.forecast(day0, 20)["days_left"] == 0
    assert bat.pct_from_voltage(3.6) == 100 and bat.pct_from_voltage(3.3) == 50 and bat.pct_from_voltage(2.5) == 0
    assert bat.BatteryForecast(json.loads(json.dumps(fc2.to_dict()))).replaced == fc2.replaced


def test_settings_profiles():
    prf = _load("profiles")
    opts = {"model": "EM300-TH", "battery_low_pct": 25, "max_gap_min": 60, "purpose": "fridge", "p_temp_high": 8,
            "channel_map": "1; x", "pivot_centre": {"lat": 1}, "meter_offset": 5, "channel_templates": [{"t": 1}]}
    meta = {"config": {"report_interval": 5}, "settings": {"temperature_alarm": {"condition": "above", "max": 8}}}
    p = prf.capture("EM300-TH", opts, meta, "Fridge", "Fridge 1", 1.0)
    assert "pivot_centre" not in p["options"] and "meter_offset" not in p["options"] and "model" not in p["options"]
    assert p["options"]["p_temp_high"] == 8 and p["config"] == {"report_interval": 5}
    target = {"model": "EM300-TH", "battery_low_pct": 10, "meter_offset": 2, "channel_map": "2; y", "old": 1}
    new = prf.merged_options(target, p, channels=False)
    assert new["battery_low_pct"] == 25 and new["meter_offset"] == 2 and new["channel_map"] == "2; y"
    assert new["model"] == "EM300-TH" and "old" not in new and new["purpose"] == "fridge"
    assert prf.merged_options(target, p)["channel_map"] == "1; x"
    steps = prf.over_the_air(p, {"config": {"report_interval": 5}, "settings": {}})
    assert steps == [("setting", ("temperature_alarm", {"condition": "above", "max": 8}))]
    assert prf.over_the_air(p, meta) == []
    assert "Fridge (EM300-TH, 5 options, 2 device settings, from Fridge 1)" == prf.describe(p)


def test_handover_report():
    ho = _load("handover")
    devs = [{"name": "Cold room", "model": "EM300-TH", "deveui": "24E1", "area": "Kitchen", "purpose": "Freezer",
             "network_server": "Gateway (Embedded NS)", "online": True, "signal": "good", "rssi": -98, "snr": 6.5,
             "sf": 9, "gateway": "UG65", "gateways_heard": 2, "packet_loss": 0, "battery": 93,
             "battery_replace_by": "2029-03-01", "firmware": "1.3", "last_seen": "2026-10-17T09:00:00+00:00",
             "battery_low": False, "walk_test": {"verdict": "good", "spot": "door", "count": 12}},
            {"name": "Gate <b>", "model": "WS101", "deveui": "24E2", "area": None, "online": False, "signal": "poor",
             "gateways_heard": 1, "battery": 15, "battery_low": True, "last_seen": None}]
    csv_text = ho.report_csv(devs)
    rows = csv_text.strip().splitlines()
    assert rows[0].startswith("Device,Model,DevEUI,Area") and rows[1].startswith("Cold room,EM300-TH")
    assert "good at door (12 readings)" in rows[1] and "2026-10-17 09:00" in rows[1] and ",no," in rows[2]
    todo = ho.checks(devs)
    assert any(t.startswith("Offline: Gate") for t in todo) and any("No area set" in t for t in todo)
    page = ho.report_html({"site": "Farm", "company": "Acme", "address": "R1", "contact": "Juan"}, devs,
                          [{"id": "24e124fffefa2994", "name": "UG65", "packets_today": 120}], "17 October 2026 10:00")
    assert "Gate &lt;b&gt;" in page and "<b>2</b> devices" in page and "window.print()" in page
    assert "UG65" in page and "due 2029-03-01" in page and "Installer – name" in page


def test_maintenance_dashboard_renders():
    import jinja2
    import yaml
    env = jinja2.Environment(extensions=["jinja2.ext.loopcontrols", "jinja2.ext.do"])
    env.filters["timestamp_custom"] = lambda v, f: "17 Oct"
    S = types.SimpleNamespace
    devs = [{"name": "Cold room", "model": "EM300-TH", "area": "Kitchen", "online": True, "battery": 40,
             "battery_low": False, "battery_days_left": 45, "battery_replace_by": "2026-12-01",
             "battery_forecast": "trend", "signal": "fair", "rssi": -112, "snr": -6, "sf": 10, "gateways_heard": 1,
             "packet_loss": 2, "firmware": "1.2", "offline_hours": None, "last_seen": "x",
             "service": [{"at": "2026-10-10T09:00:00", "kind": "battery_replaced", "text": "Battery replaced", "by": "Juan"}]},
            {"name": "Freezer", "model": "EM300-TH", "area": None, "online": False, "battery": 90, "battery_low": False,
             "battery_days_left": None, "battery_replace_by": None, "battery_forecast": "collecting", "signal": "good",
             "rssi": -90, "snr": 8, "sf": 7, "gateways_heard": 2, "packet_loss": 0, "firmware": "1.3",
             "offline_hours": 30.5, "last_seen": "x", "service": []}]
    states = S(sensor=[S(state="2", attributes={"milesight_role": "fleet_total", "devices": devs})])
    cfg = yaml.safe_load((PKG.parents[1] / "dashboards" / "maintenance.yaml").read_text(encoding="utf-8"))
    out = {}
    for sec in cfg["views"][0]["sections"]:
        for card in sec["cards"]:
            if card["type"] == "markdown":
                head = next((c.get("heading") for c in sec["cards"] if c["type"] == "heading"), "summary")
                out[head] = env.from_string(card["content"]).render(states=states, as_timestamp=lambda v: 0, dict=dict)
    assert "**2 devices** · 🔋 1 batteries due in 90 days · 📴 1 offline > 24 h · 📶 0 weak signal" in out["summary"]
    assert "🟠 **Cold room** · Kitchen · 40 %" in out["Batteries"] and "replace by **2026-12-01** (45 days)" in out["Batteries"]
    assert "No forecast yet: Freezer" in out["Batteries"]
    assert "📴 **Freezer**" in out["Offline more than 24 h"] and "1.3 days" in out["Offline more than 24 h"]
    assert "🟠 **Cold room**" in out["Weak signal"]
    assert "⚠ mixed: 1.2 (1), 1.3 (1)" in out["Firmware"] and "Older than 1.3: Cold room" in out["Firmware"]
    assert "🔋 **Cold room**" in out["Service history"] and "Battery replaced · Juan" in out["Service history"]

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
