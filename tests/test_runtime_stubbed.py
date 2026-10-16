"""Exercise hub -> runtime -> entities with a minimal Home Assistant stub.

This checks the integration's own wiring and value mapping for every model.
It does NOT replace a test inside a real Home Assistant instance.
"""
import asyncio
import time, base64, json, pathlib, sys, time, types, enum
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components"
sys.path.insert(0, str(ROOT))

# ---------------- minimal stubs -----------------
def mod(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m

signals = {}
def dispatcher_connect(hass, sig, fn):
    signals.setdefault(sig, []).append(fn); return lambda: signals[sig].remove(fn)
def dispatcher_send(hass, sig, *a):
    for fn in list(signals.get(sig, [])): fn(*a)

class Store:
    def __init__(self, hass, v, key): self.key = key
    async def async_load(self): return None
    def async_delay_save(self, fn, d): self.saved = fn()
    async def async_save(self, d): self.saved = d
    async def async_remove(self): pass

class StrE(str, enum.Enum): pass
SensorDeviceClass = StrE("SDC", {k.upper(): k for k in ['date', 'enum', 'timestamp', 'uptime', 'absolute_humidity', 'apparent_power', 'aqi', 'area', 'atmospheric_pressure', 'battery', 'blood_glucose_concentration', 'carbon_monoxide', 'carbon_dioxide', 'conductivity', 'current', 'data_rate', 'data_size', 'distance', 'duration', 'energy', 'energy_distance', 'energy_storage', 'frequency', 'gas', 'humidity', 'illuminance', 'irradiance', 'moisture', 'monetary', 'nitrogen_dioxide', 'nitrogen_monoxide', 'nitrous_oxide', 'ozone', 'ph', 'pm1', 'pm10', 'pm25', 'pm4', 'power_factor', 'power', 'precipitation', 'precipitation_intensity', 'pressure', 'radon', 'reactive_energy', 'reactive_power', 'signal_strength', 'sound_pressure', 'speed', 'sulphur_dioxide', 'temperature', 'temperature_delta', 'volatile_organic_compounds', 'volatile_organic_compounds_parts', 'voltage', 'volume', 'volume_storage', 'volume_flow_rate', 'water', 'weight', 'wind_direction', 'wind_speed']})  # copied from HA core
SensorStateClass = StrE("SSC", {k.upper(): k for k in ["measurement","total_increasing"]})
BinarySensorDeviceClass = StrE("BDC", {k.upper(): k for k in ['battery', 'battery_charging', 'carbon_monoxide', 'cold', 'connectivity', 'door', 'garage_door', 'gas', 'glass_break', 'heat', 'light', 'lock', 'moisture', 'motion', 'moving', 'occupancy', 'opening', 'plug', 'power', 'presence', 'problem', 'running', 'safety', 'smoke', 'sound', 'tamper', 'update', 'vibration', 'window']})  # copied from HA core
EntityCategory = StrE("EC", {"DIAGNOSTIC": "diagnostic"})
callback = lambda f: f

class Entity:
    def async_on_remove(self, f): pass
    def async_write_ha_state(self): self.writes = getattr(self, "writes", 0) + 1


from datetime import datetime, timezone
dt_mod = types.SimpleNamespace(get_time_zone=lambda z: ZoneInfo(z), UTC=timezone.utc,
                               utc_from_timestamp=lambda ts: datetime.fromtimestamp(ts, timezone.utc))

mod("homeassistant"); mod("homeassistant.components")
PUBLISHED = []
async def _publish(hass, topic, payload, qos=0, retain=False): PUBLISHED.append((topic, json.loads(payload)))
mod("homeassistant.components.mqtt", ReceiveMessage=object, async_subscribe=None, async_wait_for_mqtt_client=None,
    async_publish=_publish)
mod("homeassistant.config_entries", ConfigEntry=object, SOURCE_INTEGRATION_DISCOVERY="integration_discovery")
mod("homeassistant.core", HomeAssistant=object, callback=callback)
mod("homeassistant.helpers"); mod("homeassistant.util", dt=dt_mod); mod("homeassistant.util.dt", **vars(dt_mod))
mod("homeassistant.helpers.dispatcher", async_dispatcher_connect=dispatcher_connect, async_dispatcher_send=dispatcher_send)
mod("homeassistant.helpers.event", async_track_time_interval=lambda h, f, i: (lambda: None))
mod("homeassistant.helpers.storage", Store=Store)
mod("homeassistant.helpers.device_registry", DeviceInfo=dict)
mod("homeassistant.helpers.entity", Entity=Entity, EntityCategory=EntityCategory)
mod("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
mod("homeassistant.components.sensor", SensorDeviceClass=SensorDeviceClass, SensorEntity=object, SensorStateClass=SensorStateClass)
class _Ev:
    def _trigger_event(self, t, a=None): self.last_event = t
class _HV(str, enum.Enum):
    OFF = "off"; HEAT = "heat"; COOL = "cool"; HEAT_COOL = "heat_cool"; AUTO = "auto"; DRY = "dry"; FAN_ONLY = "fan_only"
class _HA(str, enum.Enum):
    OFF = "off"; HEATING = "heating"; COOLING = "cooling"; IDLE = "idle"; FAN = "fan"
class _CF(enum.IntFlag):
    TARGET_TEMPERATURE = 1; FAN_MODE = 8; TURN_OFF = 128; TURN_ON = 256
class _Climate:
    native_target_temperature = None                   # behave like Home Assistant 2026.x
mod("homeassistant.components.climate", ClimateEntity=_Climate, ClimateEntityFeature=_CF, HVACAction=_HA, HVACMode=_HV)
mod("homeassistant.components.switch", SwitchDeviceClass=StrE("SWDC", {"OUTLET": "outlet", "SWITCH": "switch"}), SwitchEntity=object)
mod("homeassistant.components.event", EventDeviceClass=types.SimpleNamespace(BUTTON="button"), EventEntity=_Ev)
mod("homeassistant.components.device_tracker", SourceType=types.SimpleNamespace(GPS="gps"), TrackerEntity=object)
mod("homeassistant.components.binary_sensor", BinarySensorDeviceClass=BinarySensorDeviceClass, BinarySensorEntity=object)
mod("homeassistant.const", ATTR_TEMPERATURE="temperature", UnitOfTemperature=types.SimpleNamespace(CELSIUS="°C"), Platform=types.SimpleNamespace(SENSOR="sensor", BINARY_SENSOR="binary_sensor"),
    EntityCategory=EntityCategory)
mod("homeassistant.exceptions", ConfigEntryNotReady=Exception, HomeAssistantError=Exception)

# Load modules directly (skip package __init__)
import importlib.util
PKG = ROOT / "milesight_lorawan"
pkg = types.ModuleType("milesight_lorawan"); pkg.__path__ = [str(PKG)]; sys.modules["milesight_lorawan"] = pkg
def load(n):
    spec = importlib.util.spec_from_file_location(f"milesight_lorawan.{n}", PKG / f"{n}.py")
    m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m); return m
for n in ["const", "decoders", "analytics", "models", "hub", "runtime", "entity", "sensor", "binary_sensor", "device_tracker", "switch", "event", "climate"]:
    globals()[n] = load(n)

class FakeEntries:
    def __init__(self): self.known = set(); self.flows = []
    def async_entry_for_domain_unique_id(self, d, u): return u in self.known
class FakeFlow:
    def __init__(self, entries): self.entries = entries
    def async_init(self, domain, context, data): entries.flows.append(data); return None
entries = FakeEntries(); entries.flow = FakeFlow(entries)
fired = []
hass = types.SimpleNamespace(bus=types.SimpleNamespace(async_fire=lambda e, d: fired.append((e, d))),
                             config=types.SimpleNamespace(time_zone="Africa/Johannesburg"),
                             config_entries=entries, data={}, async_create_task=lambda c: None)

hub_entry = types.SimpleNamespace(data={"entry_type": "hub", "topic": "x/#", "payload_encoding": "base64"}, options={})
hb = hub.Hub(hass, hub_entry)
hass.data["milesight_lorawan"] = {"hubs": {"h": hb}}

def send(deveui, raw, **kw):
    msg = {"devEUI": deveui.upper(), "data": base64.b64encode(raw).decode(), "rssi": -95, "snr": 7.0, **kw}
    hb._message_received(types.SimpleNamespace(payload=json.dumps(msg)))

def make_device(deveui, model):
    e = types.SimpleNamespace(data={"entry_type": "device", "deveui": deveui, "model": model},
                              options={}, title=f"{model} test")
    rt = runtime.DeviceRuntime(hass, e)
    asyncio.run(rt.async_load()); entries.known.add(deveui); rt.async_start()
    ents = []
    for s in models.entity_specs(model):
        cls = {"sensor": sensor.MilesightSensor, "device_tracker": device_tracker.MilesightTracker,
               "switch": switch.MilesightSwitch, "event": event.MilesightButton,
               "climate": climate.MilesightClimate}.get(
            s.platform, binary_sensor.MilesightBinarySensor)
        ents.append(cls(rt, s))
    return rt, ents

def states(ents):
    return {e.spec.key: (e.native_value if hasattr(e, "native_value") else e.is_on) for e in ents}

# 1) discovery of unknown device
send("24e124136b322135", base64.b64decode("AXVkA2cJAQRoTgYAAQ=="))
assert entries.flows and entries.flows[0]["guess"] == "EM300-MCS", entries.flows
send("24e124136b322135", base64.b64decode("AXVkA2cJAQRoTgYAAQ=="))
assert len(entries.flows) == 1, "should announce once"

# 2) confirm -> device picks up the cached uplink immediately
rt, ents = make_device("24e124136b322135", "EM300-MCS")
st = states(ents)
assert st["temperature"] == 26.5 and st["door_active"] is True and st["door_status"].startswith("Open since")
assert st["rssi"] == -95 and st["last_seen"] is not None
send("24e124136b322135", bytes([0x06, 0x00, 0x00]))
st = states(ents)
assert st["door_active"] is False and st["door_status"] == "Closed" and st["door_last_off_at"] is not None
missing = [k for k, v in st.items() if v is None]
print("EM300-MCS ok; still-empty entities:", missing)

# 3) every model builds entities and maps values without errors
samples = {
    "VS121": bytes([0x04, 0xC9, 2, 1, 0, 1]),
    "EM300-TH": bytes([0x01, 0x75, 90, 0x03, 0x67, 0x10, 0x01, 0x04, 0x68, 0x60]),
    "EM300-SLD": bytes([0x03, 0x67, 0x10, 0x01, 0x05, 0x00, 0x01]),
    "EM300-ZLD": bytes.fromhex("01755c03673401046865050000"),
    "AM307": bytes.fromhex("03670a01046858077d5004087de300"),
    "VS321": bytes.fromhex("01755003670a01046858""05fd0200""06fe03000100""07ff01"),
    "VS340": bytes.fromhex("017564030001"),
    "TS101": bytes.fromhex("01756403670a01"),
    "TS201": bytes.fromhex("01756403670a01046850"),
    "TS301": bytes.fromhex("01756403670a018367c8ff02"),
    "TS301-V1": bytes.fromhex("01756403670a01030001"),
    "TS302": bytes.fromhex("01756403670a010467e6ff8467e6ff02"),
    "TS302-V1": bytes.fromhex("01756403670a010467e6ff"),
    "TS601": bytes.fromhex("016404ce09000005f4010c010811d0070000"),
    "TS602": bytes.fromhex("016404ce09000005f401"),
    "EM500-CO2": bytes.fromhex("01756403671901046873057D670406736827"),
    "EM500-LGT": bytes.fromhex("017564039450000000"),
    "EM500-PP": bytes.fromhex("017564037B0A00"),
    "EM500-PT100": bytes.fromhex("01756403671901"),
    "EM500-SMTC": bytes.fromhex("01756403671901046873057FF000"),
    "EM500-SWL": bytes.fromhex("01756403770200"),
    "EM500-UDL": bytes.fromhex("01756403821E00"),
    "VS341": bytes.fromhex("017564030000"),
    "VS370": bytes.fromhex("017564030001040000"),
    "VS373": bytes.fromhex("07b0040010000020000006fb0100000101""08b1026c07"),
    "AM308": bytes.fromhex("03670a0104685805000106cb01077dff02087de3000973fe270b7d07000c7d0800017562"),
    "AM319-HCHO": bytes.fromhex("077d20030a7d10000b7d07000c7d0800"),
    "AM319-HCHO-WELL": bytes.fromhex("077d20030f7d1000"),
    "AM319-O3": bytes.fromhex("077d20030d7d1000"),
    "EM300-DI": bytes([0x05, 0x00, 0x01, 0x05, 0xC8, 10, 0, 0, 0]),
}
for i, (model, raw) in enumerate(samples.items()):
    dev = f"00000000000000{i:02x}"
    entries.known.add(dev)
    rt, ents = make_device(dev, model)
    send(dev, raw)
    rt._tick(None)
    st = states(ents)
    print(model, "->", {k: st[k] for k in list(st)[:4]})
    if model == "EM300-SLD":
        assert st["leak_active"] is True and st["leak_status"].startswith("Leak since"), st
    if "feels_like" in st and st.get("temperature") is not None and st.get("humidity") is not None:
        assert st["feels_like"] is not None, model
    if model.startswith("EM500"):
        empty = [k for k, v in st.items() if v is None and not k.endswith(("_at", "_since")) and k not in ("snr",)]
        assert not empty, (model, empty)
    if model == "EM500-CO2":
        assert st["co2"] == 1127 and st["co2_status"] == "Moderate" and st["co2high_active"] is True
    if model == "EM500-SMTC":
        assert st["moisture"] == 57.5 and st["electricity_max_today"] == 240 and st["sensor_error"] == "OK"
    if model.startswith("TS"):
        enabled = [e.spec.key for e in ents if e.spec.enabled_default]
        empty = [k for k in enabled if st.get(k) is None and not k.endswith(("_at", "_since", "snr"))
                 and not k.endswith(("_alarm_active", "_alarm_status", "probe_connected"))]
        assert not empty, (model, empty)
    if model == "TS301":
        assert st["temperature"] == -5.6 and st["temperature_alarm_active"] is True and st["temperature_alarm_status"] == "Below threshold alarm"
    if model == "TS302":
        assert st["temperature_2"] == -2.6 and st["temperature_2_alarm_active"] is True and st["temperature_1_alarm_active"] is False
    if model == "TS601":
        assert st["probe_connected"] is True and st["temperature_alarm_active"] is True and st["humidity"] == 50.0
    if model == "VS321":
        assert st["occ_occupied"] is True and "2 people" in st["occ_status"] and st["region_1"] is True and st["illuminance"] == "Bright", st
    if model == "VS340":
        assert st["occ_occupied"] is True and "people" not in st["occ_status"] and "occ_peak_today" not in st, st
    if model == "VS370":
        assert st["illuminance"] == "Dim" and st["occ_occupied"] is True
    if model == "VS373":
        assert st["alarm_fall"] is True and st["detection_status"] == "Fall" and st["last_alarm"] == "Fall", st
        assert st["respiratory_rate"] == 19.0 and st["respiratory_status"] == "Normal" and st["occ_occupied"] is True
        assert fired and fired[-1][1]["alarm_type"] == "fall"
        send(dev, bytes.fromhex("06fb0100000201"))          # fall alarm deactivated
        assert states(ents)["alarm_fall"] is False
    if model == "AM307":
        assert st["co2"] == 1104 and st["co2_status"] == "Moderate" and st["co2high_active"] is True, st
    if model == "AM308":
        assert st["pm10"] == 8 and st["pir"] is True and st["co2_max_today"] == 767 and st["co2_status"] == "Good"
st = states(make_device("0000000000000000", "VS121")[1])
assert st["occ_occupied"] is True and st["people_count_all"] == 2 and "2 people" in st["occ_status"]
print("all models ok")


# ---------------- UC range: entities appear per channel as data arrives ----------------
def dynamic_device(deveui, model):
    e = types.SimpleNamespace(data={"entry_type": "device", "deveui": deveui, "model": model}, options={},
                              title=f"{model} test", async_on_unload=lambda f: None)
    rt = runtime.DeviceRuntime(hass, e)
    asyncio.run(rt.async_load()); entries.known.add(deveui)
    e.runtime_data = rt
    ents = []
    for plat, cls in (("sensor", sensor.MilesightSensor), ("binary_sensor", binary_sensor.MilesightBinarySensor)):
        entity.setup_platform_entities(e, lambda new: ents.extend(list(new)), plat, cls)
    rt.async_start()
    return rt, ents

uc_samples = {
    "UC300": "030001070101096735000b02e8030000ff1900040200fa00ff1501",
    "UC501": "017564030001ff1410050288130000000000000000000808db00302b31322e352b332e3200000000000000000000000000000000000000000000000000",
    "UC511": "0175500301010409640000000701010097b2c00"[:0] + "01755003010104c86400000007010109 7b2c01".replace(" ", ""),
    "UC521": "01755003f600320af6013a097bf4010b f50002000000000100 01".replace(" ", ""),
    "UC100": "ff190004067b000000",
    "UC100-V2": "f97300030a00",
    "UC11XX": "010001090100ff0e010214 00".replace(" ", ""),
    "UC11-N1": "0175640300010401",
}

# EM400 with fill level from the "empty distance" option
e = types.SimpleNamespace(data={"entry_type": "device", "deveui": "0000000000000400", "model": "EM400-TLD"},
                          options={"install_height_mm": 1000}, title="Bin")
rt = runtime.DeviceRuntime(hass, e); asyncio.run(rt.async_load()); entries.known.add("0000000000000400"); rt.async_start()
send("0000000000000400", bytes.fromhex("01755C036701010482fa00050000"))
assert rt.values["fill_level"] == 75 and rt.values["tilted"] is False and rt.values["distance_alarm_active"] is False, rt.values
print("em400 ok")

# CT310: running time from the current threshold, combined current and estimated power
e = types.SimpleNamespace(data={"entry_type": "device", "deveui": "0000000000000310", "model": "CT310"},
                          options={"run_threshold_a": 2, "mains_voltage": 230}, title="Compressor")
rt = runtime.DeviceRuntime(hass, e); asyncio.run(rt.async_load()); entries.known.add("0000000000000310"); rt.async_start()
send("0000000000000310", bytes.fromhex("049900000699000008990000"))     # all 0 A -> off
send("0000000000000310", bytes.fromhex("0499320006990a0008990000"))     # 5.0 A, 1.0 A, 0 A
v = rt.values
assert v["load_active"] is True and v["load_status"].startswith("Running since"), v
assert v["current_total"] == 6.0 and v["apparent_power_1"] == 1150 and v["apparent_power"] == 1380, v
assert v["current_1_alarm_active"] is False and v["sensor_error"] == "OK"
send("0000000000000310", bytes.fromhex("049905000699000008990000"))     # 0.5 A -> below threshold
assert rt.values["load_active"] is False and rt.values["load_status"] == "Off" and rt.values["load_count_today"] == 1, rt.values
print("ct ok")

# GS601: vaping alarm is latched until the device reports the deactivation
e = types.SimpleNamespace(data={"entry_type": "device", "deveui": "0000000000000601", "model": "GS601"},
                          options={}, title="Toilets")
rt = runtime.DeviceRuntime(hass, e); asyncio.run(rt.async_load()); entries.known.add("0000000000000601"); rt.async_start()
send("0000000000000601", bytes.fromhex("0050010a05200012000d6400"))         # periodic report, no alarm
assert rt.values["vape_active"] is False and rt.values["vape_status"] == "Clear", rt.values
send("0000000000000601", bytes.fromhex("021150"))                           # vaping alarm trigger
send("0000000000000601", bytes.fromhex("01400520001201"))                   # periodic report while vaping
assert rt.values["vape_active"] is True and rt.values["vape_status"].startswith("Vaping detected since"), rt.values
send("0000000000000601", bytes.fromhex("021005"))                           # deactivation
assert rt.values["vape_active"] is False and rt.values["vape_count_today"] == 1 and rt.values["occ_occupied"] is True
print("gs ok")

# AT101: map position, moving statistics and distance travelled
rt, ents = make_device("00000000000b0101", "AT101")
tracker = next(e for e in ents if e.spec.platform == "device_tracker")
send("00000000000b0101", bytes.fromhex("01755a0488" + (-33_918_861).to_bytes(4, "little", signed=True).hex()
                                       + (18_423_300).to_bytes(4, "little", signed=True).hex() + "03"),
     time=datetime.fromtimestamp(time.time() - 300, timezone.utc).isoformat())                       # Cape Town, stopped, 5 min ago
assert tracker.latitude == -33.918861 and tracker.longitude == 18.4233 and rt.values["moving_active"] is False
send("00000000000b0101", bytes.fromhex("0488" + (-33_928_861).to_bytes(4, "little", signed=True).hex()
                                       + (18_423_300).to_bytes(4, "little", signed=True).hex() + "12"))   # ~1.1 km south, moving, outside
v = rt.values
assert v["moving_active"] is True and v["away_active"] is True and v["away_status"].startswith("Outside since"), v
assert 1.0 < v["distance_today_km"] < 1.2, v["distance_today_km"]
assert tracker.extra_state_attributes == {"motion_status": "moving", "geofence_status": "outside"}
print("at ok")

# WS: button events, switch control via downlink, socket energy
fired = []
hass.bus.async_fire = lambda name, data: fired.append((name, data))
rt, ents = make_device("0000000000000156", "WS156")
btn2 = next(e for e in ents if e.spec.key == "button_2")
btn2.hass = hass; asyncio.run(btn2.async_added_to_hass())
send("0000000000000156", bytes.fromhex("01755cff34020302"))                     # button 2 long press
assert btn2.last_event == "long_press" and fired[-1] == ("milesight_lorawan_button", {
    "deveui": "0000000000000156", "device": "WS156 test", "model": "WS156", "button": "button_2", "event_type": "long_press"}), fired
rt, ents = make_device("0000000000000503", "WS503-V4")
sw3 = next(e for e in ents if e.spec.key == "switch_3")
send("0000000000000503", bytes.fromhex("ff2901037454000480200000000581640683e8030000"))   # sw1 on; 84 V, 32 W, 1 kWh
assert sw3.is_on is False and rt.values["switch_1"] is True and rt.values["energy"] == 1.0 and rt.values["voltage"] == 84
asyncio.run(sw3.async_turn_on())
assert PUBLISHED[-1] == ("milesight/downlink/0000000000000503", {"confirmed": False, "fPort": 85, "data": "/ylE"}), PUBLISHED
assert sw3.is_on is True                                                           # optimistic until the device reports
rt, ents = make_device("0000000000000523", "WS523")
send("0000000000000523", bytes.fromhex("080701"))
send("0000000000000523", bytes.fromhex("08700104800a00000007c9e803"))
assert rt.values["switch_1"] is True and rt.values["power"] == 10 and rt.values["current"] == 1.0
asyncio.run(next(e for e in ents if e.spec.key == "switch_1").async_turn_off())
assert PUBLISHED[-1][1]["data"] == base64.b64encode(bytes.fromhex("0800ffff")).decode()
print("ws ok")

# WT: thermostat state and control
rt, ents = make_device("00000000000a0303", "WT303")
th = next(e for e in ents if e.spec.platform == "climate")
send("00000000000a0303", bytes.fromhex("016a0802e40203d208040005120664071208ff1013000000c801"))
assert th.native_current_temperature == 21.54 and th.current_humidity == 74 and th.native_target_temperature == 22.58
assert th.hvac_mode == "heat" and th.hvac_action == "cooling" and th.fan_mode == "low"
assert rt.values["heating_status"] == "Idle" and rt.values["cooling_status"].startswith("Cooling since")
asyncio.run(th.async_set_temperature(temperature=21.5))
assert PUBLISHED[-1] == ("milesight/downlink/00000000000a0303", {"confirmed": False, "fPort": 85,
                                                               "data": base64.b64encode(bytes.fromhex("6b6608")).decode()})
assert th.native_target_temperature == 21.5
asyncio.run(th.async_set_hvac_mode("off"))
assert PUBLISHED[-1][1]["data"] == base64.b64encode(bytes.fromhex("6700")).decode() and th.hvac_mode == "off"
asyncio.run(th.async_set_hvac_mode("cool"))
assert [base64.b64decode(p[1]["data"]).hex() for p in PUBLISHED[-2:]] == ["6701", "6802"] and th.hvac_mode == "cool"
rt, ents = make_device("00000000000a0101", "WT101")
th = next(e for e in ents if e.spec.platform == "climate")
send("00000000000a0101", bytes.fromhex("01756104672C0103670A01059264099000000B900000"))
assert th.native_current_temperature == 26.6 and th.native_target_temperature == 30.0 and th.hvac_action == "heating"
asyncio.run(th.async_set_temperature(temperature=21))
assert base64.b64decode(PUBLISHED[-1][1]["data"]).hex() == "ffb1150a00"
rt, ents = make_device("00000000000a0201", "WT201-V2")
th = next(e for e in ents if e.spec.platform == "climate")
send("00000000000a0201", bytes.fromhex("036702010467a60005e70006e80007bc00088e01"))
asyncio.run(th.async_set_hvac_mode("cool"))
assert base64.b64decode(PUBLISHED[-1][1]["data"]).hex() == "f9450102a600", PUBLISHED[-1]
print("wt ok")

# every model's entities can be created with real HA device / state classes
for i, model in enumerate(models.MODELS):
    make_device(f"00000000000f{i:04x}", model)
print("entity classes ok")
for i, (model, hexstr) in enumerate(uc_samples.items()):
    raw = bytes.fromhex(hexstr)
    best, cands = models.guess_model(raw)
    assert model == best or model in cands, (model, best, cands)
    dev = f"00000000000001{i:02x}"
    rt, ents = dynamic_device(dev, model)
    before = {e.spec.key for e in ents}
    send(dev, raw)
    after = {e.spec.key: (e.native_value if hasattr(e, "native_value") else e.is_on) for e in ents}
    new = sorted(set(after) - before)
    assert new, (model, "no channel entities created")
    assert all(after[k] is not None for k in new), (model, {k: after[k] for k in new})
    print(model, "->", {k: after[k] for k in new})
print("uc ok")

# CTH01: channel entities appear as the meter reports them
rt, ents = dynamic_device("00000000000c0001", "CTH01")
send("00000000000c0001", bytes.fromhex(open(pathlib.Path(__file__).parent / "cth01_samples.txt").read().split()[1]))
keys = {e.spec.key: e for e in ents}
assert "active_power_a" in keys and keys["active_power_a"].spec.unit == "kW" and "forward_active_energy_ct1" in keys
assert keys["forward_active_energy_ct1"].spec.device_class == "energy" and keys["power_factor_b"].native_value == 0.9
print("cth ok")

