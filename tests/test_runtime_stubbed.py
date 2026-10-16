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
EntityCategory = StrE("EC", {"DIAGNOSTIC": "diagnostic", "CONFIG": "config"})
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
mod("homeassistant.core", HomeAssistant=object, callback=callback, Event=object)
mod("homeassistant.helpers"); mod("homeassistant.util", dt=dt_mod); mod("homeassistant.util.dt", **vars(dt_mod))
mod("homeassistant.helpers.dispatcher", async_dispatcher_connect=dispatcher_connect, async_dispatcher_send=dispatcher_send)
LATER = []
mod("homeassistant.helpers.event", async_track_time_interval=lambda h, f, i: (lambda: None),
    async_call_later=lambda h, d, f: (LATER.append(f), (lambda: None))[1])
mod("homeassistant.helpers.storage", Store=Store)
class _DevReg:
    def async_get_device(self, **kw): return None
mod("homeassistant.helpers.device_registry", DeviceInfo=dict, async_get=lambda h: _DevReg(),
    async_entries_for_area=lambda reg, area_id: [])
class _EntReg:
    def async_get_entity_id(self, platform, domain, unique_id): return f"{platform}.{unique_id}"
mod("homeassistant.helpers.entity_registry", async_get=lambda h: _EntReg())
class _AreaReg:
    def async_get_area_by_name(self, n): return None
    def async_get_area(self, i): return types.SimpleNamespace(name={"a1": "Meeting room 1", "a2": "Open office"}.get(i, i))
mod("homeassistant.helpers.area_registry", async_get=lambda h: _AreaReg())
PANELS = {}
mod("homeassistant.components.frontend", async_register_built_in_panel=lambda hass, comp, **kw: PANELS.update({kw["frontend_url_path"]: kw}),
    async_remove_panel=lambda hass, url: PANELS.pop(url, None))
class _LovelaceStorage:
    def __init__(self, hass, config): self.config, self.saved = config, None
    async def async_save(self, cfg): self.saved = cfg
    async def async_load(self, force): return self.saved
mod("homeassistant.components.lovelace"); mod("homeassistant.components.lovelace.dashboard", LovelaceStorage=_LovelaceStorage)
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
mod("homeassistant.components.button", ButtonDeviceClass=StrE("BTDC", {"RESTART": "restart", "IDENTIFY": "identify", "UPDATE": "update"}), ButtonEntity=object)
mod("homeassistant.components.select", SelectEntity=object)
mod("homeassistant.components.text", TextEntity=object, TextMode=types.SimpleNamespace(TEXT="text"))
mod("homeassistant.components.number", NumberEntity=object, NumberMode=types.SimpleNamespace(BOX="box"))
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
for n in ["const", "decoders", "analytics", "link", "models", "hub", "runtime", "entity", "gateway", "fleet", "sensor", "binary_sensor", "device_tracker", "switch", "event", "climate", "button", "number", "select", "text", "building_calc", "building", "dashboard_config", "dashboard"]:
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
                             config_entries=entries, data={}, async_create_task=lambda c: c.close() if asyncio.iscoroutine(c) else None)

hub_entry = types.SimpleNamespace(data={"entry_type": "hub", "topic": "x/#", "payload_encoding": "base64"}, options={},
                                  entry_id="h", title="Site gateway")
hb = hub.Hub(hass, hub_entry)
hass.data["milesight_lorawan"] = {"hubs": {"h": hb}}

FCNT = {}
def send(deveui, raw, **kw):
    FCNT[deveui] = FCNT.get(deveui, 0) + 1
    msg = {"devEUI": deveui.upper(), "data": base64.b64encode(raw).decode(), "fCnt": FCNT[deveui],
           "rxInfo": [{"mac": "24e124fffef00001", "name": "Local Gateway", "rssi": -95, "loRaSNR": 7.0}],
           "txInfo": {"frequency": 868100000, "dataRate": {"spreadFactor": 9}}, **kw}
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
               "climate": climate.MilesightClimate, "button": button.MilesightCommandButton,
               "number": number.MilesightNumber, "text": text.DisplayText,
               "select": select.DisplayTemplateSelect if s.key == "display_template" else select.MilesightSettingSelect,
               }.get(s.platform, binary_sensor.MilesightBinarySensor)
        ents.append(cls(rt, s))
    return rt, ents

def states(ents):
    return {e.spec.key: (e.native_value if hasattr(e, "native_value") else getattr(e, "is_on", None)) for e in ents}

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
        empty = [k for k, v in st.items() if v is None and not k.endswith(("_at", "_since")) and k not in ("snr",)
                 and not k.startswith(("cmd_", "cfg_", "set_")) and k not in ("last_command", "last_backfill", "command_status")]
        assert not empty, (model, empty)
    if model == "EM500-CO2":
        assert st["co2"] == 1127 and st["co2_status"] == "Moderate" and st["co2high_active"] is True
    if model == "EM500-SMTC":
        assert st["moisture"] == 57.5 and st["electricity_max_today"] == 240 and st["sensor_error"] == "OK"
    if model.startswith("TS"):
        enabled = [e.spec.key for e in ents if e.spec.enabled_default]
        empty = [k for k in enabled if st.get(k) is None and not k.endswith(("_at", "_since", "snr"))
                 and not k.endswith(("_alarm_active", "_alarm_status", "probe_connected"))
                 and not k.startswith(("cmd_", "cfg_", "set_")) and k not in ("last_command", "last_backfill", "command_status")]
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
        alarms = [f for f in fired if f[0] == "milesight_lorawan_alarm"]
        assert alarms and alarms[-1][1]["alarm_type"] == "fall"
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
    after = {e.spec.key: (e.native_value if hasattr(e, "native_value") else getattr(e, "is_on", None)) for e in ents}
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

# VS350: people in / out summed per day
rt, ents = make_device("00000000000d0350", "VS350")
send("00000000000d0350", bytes.fromhex("05cc03000200"))
send("00000000000d0350", bytes.fromhex("05cc04000100"))
assert rt.values["people_in_today"] == 7 and rt.values["people_out_today"] == 3 and rt.values["people_net_today"] == 4, rt.values
print("people counter ok")

# Downlink commands: buttons, interval number, UC outputs
def last_hex():
    return base64.b64decode(PUBLISHED[-1][1]["data"]).hex()
rt, ents = make_device("00000000000e0300", "UC300")
by_key = {e.spec.key: e for e in ents}
asyncio.run(by_key["cmd_reboot"].async_press()); assert last_hex() == "ff10ff"
asyncio.run(by_key["cmd_sync_time"].async_press()); assert last_hex() == "ff4aff"
asyncio.run(by_key["cmd_report_status"].async_press()); assert last_hex() == "ff94ff"
asyncio.run(by_key["cfg_report_interval"].async_set_native_value(600)); assert last_hex() == "ff035802"
assert by_key["cfg_report_interval"].native_value == 600
sw = by_key["gpio_output_2"]
assert type(sw).__name__ == "MilesightSwitch"
asyncio.run(sw.async_turn_on()); assert last_hex() == "0801ff" and sw.is_on is True
asyncio.run(rt.async_output("gpio_output_1", "on_for", 5000)); assert last_hex() == "ff93010188130000"
rt, ents = make_device("00000000000e0521", "UC521")
by_key = {e.spec.key: e for e in ents}
asyncio.run(by_key["valve_1_opening"].async_set_native_value(40)); assert last_hex() == "f919000028"
rt, ents = make_device("00000000000e0102", "AM102")
by_key = {e.spec.key: e for e in ents}
asyncio.run(by_key["cmd_sync_time"].async_press()); assert last_hex().startswith("ff11") and len(last_hex()) == 12
print("downlinks ok")

# Online / battery low / command confirmation
rt, ents = make_device("00000000000f0300", "EM300-TH")
send("00000000000f0300", bytes.fromhex("01750f03671001046860"))
assert rt.values["online"] is True and rt.values["battery_low"] is True
rt.meta["last_seen"] -= rt.max_gap_s + 60
rt._tick(None)
assert rt.values["online"] is False
asyncio.run(rt.async_command("report_interval", 600))
assert rt.values["last_command"] == "report interval: pending" and rt.meta["confirmed"]["report_interval"] is False
assert rt.values["command_status"] == "pending"
send("00000000000f0300", bytes.fromhex("01755aff035802"))          # device echoes the new interval
assert rt.values["last_command"] == "report interval: confirmed" and rt.meta["confirmed"]["report_interval"] is True
assert rt.values["command_status"] == "confirmed" and rt.commands.echoes is True
assert [e for e in fired if e[0] == "milesight_lorawan_command"][-1][1]["status"] == "confirmed"
assert rt.values["online"] is True and rt.values["battery_low"] is False

# Fleet sensors
import importlib
fleet = importlib.import_module("milesight_lorawan.fleet")
dev_entry = types.SimpleNamespace(data={"entry_type": "device", "deveui": rt.deveui, "area": "Lab"}, title="TH lab",
                                  runtime_data=rt)
hub_entry = types.SimpleNamespace(data={"entry_type": "hub"}, entry_id="h1", title="GW", runtime_data=hb)
fake = types.SimpleNamespace(config_entries=types.SimpleNamespace(async_entries=lambda d: [hub_entry, dev_entry]))
devs = fleet.fleet_devices(fake, hub_entry)
assert devs == [{"name": "TH lab", "model": "EM300-TH", "deveui": rt.deveui.upper(), "area": "Lab", "online": True,
                 "battery": 90, "battery_low": False, "rssi": -95, "snr": 7.0, "sf": 9, "gateway": "Local Gateway",
                 "gateways_heard": 1, "signal": "excellent", "packet_loss": 0.0, "command": "confirmed",
                 "last_seen": devs[0]["last_seen"]}], devs
print("fleet ok")

# Settings (alarm thresholds, LED / child lock), stored history, pulse meter
rt, ents = make_device("0000000000100300", "EM300-TH")
by_key = {e.spec.key: e for e in ents}
cond = by_key["set_temperature_alarm__condition"]
assert cond._attr_options == ["disable", "below", "above", "between", "outside"]
asyncio.run(by_key["set_temperature_alarm__max"].async_set_native_value(30))
asyncio.run(cond.async_select_option("above"))
assert last_hex() == "ff060a" + (-300).to_bytes(2, "little", signed=True).hex() + (300).to_bytes(2, "little").hex() + "00000000", last_hex()
assert cond.current_option == "above" and by_key["set_temperature_alarm__max"].native_value == 30
rt, ents = make_device("0000000000100307", "AM307")
by_key = {e.spec.key: e for e in ents}
asyncio.run(by_key["set_led_indicator"].async_turn_off())
assert by_key["set_led_indicator"].is_on is False
asyncio.run(by_key["cmd_fetch_history"].async_press())
assert last_hex().startswith("fd6c") and len(last_hex()) == 20
# EM300-TH history record arrives -> parsed and handed to the statistics importer
rt, ents = make_device("0000000000100301", "EM300-TH")
recs = []
rt._import_history = lambda records, measures: recs.append((records, measures)) or asyncio.sleep(0)
hass.async_create_task = lambda coro: asyncio.run(coro) if asyncio.iscoroutine(coro) else None
send("0000000000100301", bytes.fromhex("20ce" + (1760000000).to_bytes(4, "little").hex() + "1001" + "60" + "00"))
assert recs and recs[0][0] == [(1760000000, {"temperature": 27.2, "humidity": 48.0})], recs
assert "temperature" in recs[0][1] and "humidity" in recs[0][1]
# pulse meter
e = types.SimpleNamespace(data={"entry_type": "device", "deveui": "0000000000100302", "model": "EM300-DI"},
                          options={"meter_type": "water", "meter_unit": "L", "meter_pulses_per_unit": 2, "meter_offset": 1000},
                          title="Water")
rt = runtime.DeviceRuntime(hass, e); asyncio.run(rt.async_load()); entries.known.add("0000000000100302"); rt.async_start()
send("0000000000100302", bytes.fromhex("05c8e8030000"))       # 1000 pulses
assert rt.values["meter_reading"] == 1500 and rt.extra_specs()[0].device_class == "water"
print("settings / history / meter ok")

# Building analytics
assert fleet.comfort_score(22, 45, 600) == 100 and fleet.comfort_score(27, 45, 1300) == 63
assert fleet.comfort_score(None, None, None) is None
print("analytics ok")

# ---------------- 0.18: downlink confirmation, signal quality, DS3604, gateway health ----------------
hass.async_create_task = lambda c: asyncio.run(c) if asyncio.iscoroutine(c) else None
fired.clear()
# switch command confirmed by the status report
rt, ents = make_device("0000000000180503", "WS503-V4")
sw3 = next(e for e in ents if e.spec.key == "switch_3")
send("0000000000180503", bytes.fromhex("ff2901"))
asyncio.run(sw3.async_turn_on())
assert rt.values["command_status"] == "pending" and sw3.is_on is True
send("0000000000180503", bytes.fromhex("ff2905"))                       # sw1 + sw3 on
assert rt.values["command_status"] == "confirmed" and rt.values["last_command"] == "switch 3: confirmed"
# not switched: resent once (retries=1), then failed and the optimistic state is undone
rt.entry.options = {"downlink_retries": 1}
n0 = len(PUBLISHED)
asyncio.run(next(e for e in ents if e.spec.key == "switch_2").async_turn_on())
for _ in range(2):
    send("0000000000180503", bytes.fromhex("ff2905"))
assert len(PUBLISHED) == n0 + 2 and PUBLISHED[-1] == PUBLISHED[-2]             # the retry
for _ in range(2):
    send("0000000000180503", bytes.fromhex("ff2905"))
assert rt.values["command_status"] == "failed" and rt.values["switch_2"] is False, rt.values["last_command"]
ev = [d for e, d in fired if e == "milesight_lorawan_command"]
assert [d["status"] for d in ev] == ["confirmed", "failed"] and ev[-1]["attempts"] == 2
print("confirmation ok")

# confirmed downlinks + network ACK (Milesight ACK notification on an extra topic)
rt, ents = make_device("0000000000180300", "EM300-TH")
rt.entry.options = {"confirmed_downlinks": True}
send("0000000000180300", bytes.fromhex("0175640367100104686000"))
asyncio.run(rt.async_command("reboot"))
assert PUBLISHED[-1][1]["confirmed"] is True
hb._message_received(types.SimpleNamespace(payload=json.dumps(
    {"applicationID": 1, "devEUI": "0000000000180300", "acknowledged": True, "fcnt": 12})))
assert rt.values["command_status"] == "confirmed" and rt.values["last_ack"] == "acknowledged"
assert hb.stats.counts["acks"] == 1 and hb.stats.counts["downlinks"] >= 1
hb._message_received(types.SimpleNamespace(payload=json.dumps({"devEUI": "0000000000180300", "devAddr": "01020304"})))
assert fired[-1][0] == "milesight_lorawan_device_joined" and hb.stats.counts["joins"] == 1
print("ack / join ok")

# signal quality, packet loss, duplicates
send("0000000000180300", bytes.fromhex("0175640367100104686000"))           # first frame after the join
FCNT["0000000000180300"] += 3                                              # 3 frames lost
send("0000000000180300", bytes.fromhex("0175640367100104686000"))
up_before = rt.link.received
hb._message_received(types.SimpleNamespace(payload=json.dumps({        # same frame via a second gateway
    "devEUI": "0000000000180300", "data": base64.b64encode(bytes.fromhex("0175640367100104686000")).decode(),
    "fCnt": FCNT["0000000000180300"], "rxInfo": [{"mac": "24e124fffef00002", "name": "Roof", "rssi": -118,
                                                    "loRaSNR": -9}]})))
assert rt.link.received == up_before and hb.stats.counts["duplicates"] == 1
by_key = {e.spec.key: e for e in ents}
assert rt.values["packet_loss_today"] == 50.0 and rt.values["gateways_heard"] == 2, (rt.values["packet_loss_today"], rt.values["gateways_heard"], rt.link.to_dict())
assert rt.values["signal_quality"] == "excellent" and rt.values["spreading_factor"] == 9
assert [g["name"] for g in by_key["gateway"].extra_state_attributes["gateways"]] == ["Local Gateway", "Roof"]
assert "lost" in by_key["signal_quality"].extra_state_attributes["advice"]
print("signal ok")

# DS3604: blocks packed into downlinks, confirmed per block, failures reported
rt, ents = make_device("0000000000183604", "DS3604")
by_key = {e.spec.key: e for e in ents}
send("0000000000183604", bytes.fromhex("017564"))
n0 = len(PUBLISHED)
sent = asyncio.run(rt.async_display(1, {"text_1": "Meeting room 1", "text_2": "Free",
                                        "text_3": "Next: 14:00 Board meeting"}, show=True))
frames = [base64.b64decode(p[1]["data"]).hex() for p in PUBLISHED[n0:]]
assert sent == 2 and all(len(f) // 2 <= 51 for f in frames), frames
assert "".join(frames) == (dec := sys.modules["milesight_lorawan.decoders"]).encode_ds3604_content(
    1, "text_1", "Meeting room 1").hex() + dec.encode_ds3604_content(1, "text_2", "Free").hex() + \
    dec.encode_ds3604_content(1, "text_3", "Next: 14:00 Board meeting").hex() + "ff7300"
assert by_key["display_t1_text_2"].native_value == "Free"
send("0000000000183604", bytes.fromhex("fa010000fa010100"))              # text_1 + text_2 updated
assert rt.values["command_status"] == "confirmed"
send("0000000000183604", bytes.fromhex("fa010203"))                       # text_3 too long
assert rt.values["command_status"] == "failed" and rt.values["display_error"] == "text_3: content is too long"
send("0000000000183604", bytes.fromhex("fb010204" + b"Busy".hex()))       # device reports its content
assert by_key["display_t1_text_3"].native_value == "Busy"
asyncio.run(by_key["display_t1_text_1"].async_set_value("Room 2"))
assert base64.b64decode(PUBLISHED[-1][1]["data"]) == dec.encode_ds3604_content(1, "text_1", "Room 2")
asyncio.run(by_key["display_template"].async_select_option("2"))
assert base64.b64decode(PUBLISHED[-1][1]["data"]).hex() == "ff7301" and by_key["display_template"].current_option == "2"
asyncio.run(by_key["cmd_display_refresh"].async_press())
assert base64.b64decode(PUBLISHED[-1][1]["data"]).hex() == "ff3d02"
print("ds3604 ok")

# Gateway health: per-gateway devices from traffic + status reports
gw = sys.modules["milesight_lorawan.gateway"]
added = []
hub_entry = hb.entry
hub_entry.runtime_data = hb
hub_entry.async_on_unload = lambda f: None
gw.async_setup_gateway_entities(hass, hub_entry, lambda es: added.extend(es), "sensor")
gw.async_setup_gateway_entities(hass, hub_entry, lambda es: added.extend(es), "binary_sensor")
names = {(getattr(e, "gid", None), e._attr_name) for e in added}
assert ("24e124fffef00001", "Packets today") in names and ("24e124fffef00002", "Online") in names
online = next(e for e in added if getattr(e, "gid", None) == "24e124fffef00001" and e._attr_name == "Online")
assert online.is_on is True and online.extra_state_attributes["source"] == "device traffic"
pk = next(e for e in added if getattr(e, "gid", None) == "24e124fffef00001" and e._attr_name == "Packets today")
assert pk.native_value == hb.stats.gateways["24e124fffef00001"]["packets_today"] > 5
gwon = next(e for e in added if getattr(e, "kind", None) == "gateways_online")
assert gwon.native_value == 2
hb._message_received(types.SimpleNamespace(payload=json.dumps({"device_info": {
    "eui": "24E124FFFEF00009", "model": "UG63", "firmware_version": "64.0.0.5", "cpu_tempeture": "51"}})))
cpu = next(e for e in added if getattr(e, "gid", None) == "24e124fffef00009" and e.kind == "cpu_temperature")
assert cpu.native_value == 51.0 and cpu._attr_device_info["model"] == "UG63"
hb._tick()                                                                 # baseline: everything online
hb.stats.gateways["24e124fffef00002"]["last_heard"] -= 3600
hb._tick()
assert fired[-1][0] == "milesight_lorawan_gateway_offline" and fired[-1][1]["gateway"] == "Roof", fired[-1]
print("gateway ok")

# ---------------- 0.19: site information, building overview, dashboard ----------------
bmod, dmod = sys.modules["milesight_lorawan.building"], sys.modules["milesight_lorawan.dashboard"]
def am307(t, rh, co2):
    return bytes.fromhex("0367" + int(t * 10).to_bytes(2, "little").hex() + "0468" + bytes([int(rh * 2)]).hex()
                         + "077d" + co2.to_bytes(2, "little").hex())
dev_entries = []
for eui, area, payload in (("0000000000190001", "Open office", am307(23.6, 41, 948)),
                           ("0000000000190002", "Meeting room 1", am307(25.1, 58, 1340))):
    e = types.SimpleNamespace(data={"entry_type": "device", "deveui": eui, "model": "AM307", "area": area},
                              options={}, title=f"{area} AM307", entry_id=eui)
    rt = runtime.DeviceRuntime(hass, e); asyncio.run(rt.async_load()); entries.known.add(eui); rt.async_start()
    e.runtime_data = rt
    send(eui, payload)
    dev_entries.append(e)
site_entry = types.SimpleNamespace(
    data={"entry_type": "hub"}, entry_id="site1", title="Head office", runtime_data=hb,
    options={"site_address": "1 Main Rd, Cape Town", "site_contact": "person.sam", "site_phone": "+27 21 000 0000",
             "site_email": "fm@example.com", "site_areas": ["a1", "a2"], "co2_alert": 1200},
    async_on_unload=lambda f: None)
hass2 = types.SimpleNamespace(
    config=types.SimpleNamespace(location_name="Acme Facilities", time_zone="Africa/Johannesburg", country="ZA",
                                 latitude=-33.9, longitude=18.4, path=lambda f: "/tmp/" + f),
    states=types.SimpleNamespace(get=lambda e: types.SimpleNamespace(attributes={"friendly_name": "Sam Smith",
                                                                                 "entity_picture": "/api/x"})),
    config_entries=types.SimpleNamespace(async_entries=lambda d: [site_entry] + dev_entries),
    data={"lovelace": types.SimpleNamespace(dashboards={})}, bus=hass.bus, async_create_task=hass.async_create_task)
areas_tr = types.SimpleNamespace(summary=sys.modules["milesight_lorawan.fleet"].area_summary(hass2, site_entry),
                                 today_share=lambda a: 40)
hb.areas = areas_tr
tracker, bents = bmod.building_sensors(hass2, site_entry, areas_tr)
by = {e._attr_unique_id.removeprefix("site1_"): e for e in bents}
assert by["site"].native_value == "Acme Facilities"                         # Home Assistant's name
attrs = by["site"].extra_state_attributes
assert attrs["contact"] == "Sam Smith" and attrs["site"] == "Head office" and attrs["areas"] == ["Meeting room 1", "Open office"]
assert attrs["logo"] == "/local/logo.png" and attrs["country"] == "ZA"
assert by["building_air_quality"].native_value == "Moderate" and by["building_avg_co2"].native_value == 1144
assert by["building_alerts"].native_value >= 1
assert by["building_alerts"].extra_state_attributes["alerts"][0]["where"] == "Meeting room 1"
assert by["building_health"].native_value is not None and "building_avg_pm2_5" not in by   # AM307 has no PM
site_entry.options["site_company"] = "Acme Ltd"
assert by["site"].native_value == "Acme Ltd"                                # override
where = asyncio.run(dmod.async_update_dashboard(hass2, site_entry))
dash = hass2.data["lovelace"].dashboards["building-head-office"]
assert where == "/building-head-office" and PANELS["building-head-office"]["sidebar_title"] == "Building – Head office"
assert dash.saved["views"][0]["sections"][0]["cards"][0]["content"].startswith('{% set s = "sensor.site1_site" %}')
heads = [c.get("heading") for sec in dash.saved["views"][0]["sections"] for c in sec["cards"] if c["type"] == "heading"]
assert heads[-3:] == ["Meeting room 1", "Open office", "Occupancy today"], heads
print("building ok")

# ---------------- 0.20: channel map, tanks, alert escalation, gateway provisioning ----------------
def make_with(deveui, model, options, title=None, area=None):
    e = types.SimpleNamespace(data={"entry_type": "device", "deveui": deveui, "model": model, **({"area": area} if area else {})},
                              options=options, title=title or f"{model} test", entry_id=deveui)
    rt = runtime.DeviceRuntime(hass, e); asyncio.run(rt.async_load()); entries.known.add(deveui); rt.async_start()
    e.runtime_data = rt
    return e, rt

e_uc, rt = make_with("00000000000e0301", "UC300", {"channel_map": "1; Line pressure; bar; 0.01\n2.1; Flow; m³/h; 0.1"})
specs = {s.key: s for s in rt.extra_specs()}
assert specs["modbus_chn_1"].name == "Line pressure" and specs["modbus_chn_1"].device_class == "pressure"
assert specs["modbus_chn_2_reg_1"].unit == "m³/h"
send("00000000000e0301", bytes.fromhex("ff19000102d204"))
assert rt.raw["modbus_chn_1"] == 1234 and rt.values["modbus_chn_1"] == 12.34
s = sensor.MilesightSensor(rt, specs["modbus_chn_1"])
assert s.native_value == 12.34 and s._attr_native_unit_of_measurement == "bar" and s._attr_unique_id.endswith("_modbus_chn_1")
print("channel map ok")

def em400(distance_mm):
    return bytes.fromhex("0482") + distance_mm.to_bytes(2, "little")
e_tank, rt = make_with("0000000000400001", "EM400-UDL",
                       {"tank_shape": "vertical_cylinder", "tank_diameter_mm": 1000, "install_height_mm": 2100,
                        "tank_height_mm": 2000, "tank_drop_pct": 10, "tank_low_pct": 20, "tank_density": 840},
                       title="Diesel tank", area="Yard")
keys = {s.key for s in rt.extra_specs()}
assert {"tank_volume", "tank_days_left", "tank_sudden_drop", "tank_mass", "cmd_tank_refilled",
        "cmd_tank_clear_alarm"} <= keys
send("0000000000400001", em400(1100))                 # level 1000 mm = half
v = rt.values
assert v["tank_level"] == 1000 and abs(v["tank_volume"] - 785.4) < 0.1 and v["tank_fill"] == 50.0
assert abs(v["tank_capacity"] - 1570.8) < 0.1 and v["tank_low"] is False and v["tank_sudden_drop"] is False
n = len(fired)
rt.tank.s["samples"][-1][0] -= 600                    # previous reading 10 minutes ago
send("0000000000400001", em400(1500))                 # level 600: −314 L (20 %) quickly
assert rt.values["tank_sudden_drop"] is False         # one reading could be a glitch …
send("0000000000400001", em400(1502))
assert rt.values["tank_sudden_drop"] is True          # … the next one confirms it
ev = [d for e, d in fired[n:] if e == "milesight_lorawan_tank"]
assert ev and ev[0]["type"] == "sudden_drop" and ev[0]["device"] == "Diesel tank" and ev[0]["area"] == "Yard"
b = button.MilesightCommandButton(rt, next(s for s in rt.extra_specs() if s.key == "cmd_tank_clear_alarm"))
asyncio.run(b.async_press())
assert rt.values["tank_sudden_drop"] is False
send("0000000000400001", em400(1950))                 # level 150 mm < 20 %
send("0000000000400001", em400(1951))
assert rt.values["tank_low"] is True and rt.values["tank_sudden_drop"] is True    # fell fast again
asyncio.run(b.async_press())
send("0000000000400001", em400(1952))
assert rt.values["tank_sudden_drop"] is False         # cleared stays cleared
assert rt._data_to_save()["trackers"]["tank"]["samples"]
print("tank ok")

# alert escalation through the hub
CALLS = []
class _Services:
    async def async_call(self, domain, service, data, blocking=False): CALLS.append((domain, service, data))
    def async_services(self): return {"notify": {"mobile_app_juan": None, "mobile_app_sam": None}}
esc = sys.modules.get("milesight_lorawan.escalation") or load("escalation")
alert_entry = types.SimpleNamespace(data={"entry_type": "hub"}, entry_id="h", title="Site gateway",
                                    options={"alert_primary": ["notify.mobile_app_juan"],
                                             "alert_backup": ["notify.mobile_app_sam"], "alert_escalate_min": 15,
                                             "alert_categories": ["safety", "tank", "gateways"],
                                             "alert_action_entity": "switch.transfer_pump"})
hass3 = types.SimpleNamespace(config=hass.config, data=hass.data, bus=hass.bus, services=_Services(),
                              config_entries=types.SimpleNamespace(async_entries=lambda d: [e_tank, e_uc]),
                              auth=types.SimpleNamespace(async_get_user=None), async_create_task=hass.async_create_task)
mgr = esc.AlertManager(hass3, alert_entry, hb)
assert mgr.cfg.action_title == "Start pump"
for gid in hb.stats.gateways:                         # keep the gateways out of this test
    hb.stats.gateways[gid]["last_heard"] = time.time()
asyncio.run(mgr._run())
sent = [c for c in CALLS if c[1] == "mobile_app_juan"]
assert len(sent) == 1 and sent[0][2]["title"] == "Tank low – Diesel tank", CALLS
acts = sent[0][2]["data"]["actions"]
assert acts[1]["title"] == "Start pump" and acts[0]["action"].startswith("MSL_ACK_")
aid = acts[0]["action"].removeprefix("MSL_ACK_")
key = next(k for k in mgr.engine.alerts)
mgr.engine.alerts[key]["level_at"] -= 16 * 60         # nobody answered for 16 minutes
CALLS.clear(); asyncio.run(mgr._run())
assert {c[1] for c in CALLS} == {"mobile_app_juan", "mobile_app_sam"} and "Not acknowledged" in CALLS[0][2]["title"]
CALLS.clear()
asyncio.run(mgr._on_action(types.SimpleNamespace(data={"action": f"MSL_RUN_{aid}"}, context=None)))
assert ("switch", "turn_on", {"entity_id": "switch.transfer_pump"}) in CALLS
assert any(c[2].get("title", "").startswith("✔") for c in CALLS) and not mgr.engine.unacknowledged()
asyncio.run(mgr._on_action(types.SimpleNamespace(data={"action": "MSL_ACK_unknown"}, context=None)))   # ignored
alerts_sensor = gateway.OpenAlertsSensor(hass3, types.SimpleNamespace(**{**vars(alert_entry), "runtime_data": hb}))
hb.alerts = mgr
assert alerts_sensor.native_value == 0 and alerts_sensor.extra_state_attributes["alerts"][0]["status"] == "acknowledged"
print("alerts ok")

# gateway provisioning over ns-api
prov = load("provisioning")
SUBS = {}
async def _subscribe(hass_, topic, cb, qos=0):
    SUBS[topic] = cb; return lambda: SUBS.pop(topic, None)
GW_DEVICES = {"24e124136d000001": "EM300-TH Office"}
async def _publish_ns(hass_, topic, payload, qos=0, retain=False):
    req = json.loads(payload)
    if req.get("type") != "ns-api":
        return
    body = {"code": 200, "error": ""}
    if req["method"] == "GET" and req["url"].startswith("/api/urdevices"):
        body.update(deviceResult=[{"devEUI": k.upper(), "name": n, "applicationID": "1"} for k, n in GW_DEVICES.items()],
                    appResult=[{"appName": "farm", "applicationID": "1"}],
                    profileResult=[{"profileID": "p-a", "profileName": "ClassA-OTAA"}])
    elif req["method"] == "POST":
        eui = req["body"]["devEUI"]
        if eui in GW_DEVICES:
            body = {"code": 6, "error": "device already exist"}
        else:
            GW_DEVICES[eui] = req["body"]["name"]
            assert req["body"]["appKey"] == "5572404c696e6b4c6f52613230313823" and req["body"]["profileID"] == "p-a"
    asyncio.get_running_loop().call_soon(SUBS["ms/resp"], types.SimpleNamespace(
        payload=json.dumps({"type": "ns-api", "id": req["id"], "method": req["method"], "url": req["url"], "body": body})))
sys.modules["homeassistant.components.mqtt"].async_subscribe = _subscribe
sys.modules["homeassistant.components.mqtt"].async_publish = _publish_ns
async def _prov():
    loop = asyncio.get_running_loop()
    h = types.SimpleNamespace(loop=loop)
    c = prov.NsApiClient(h, "ms/req", "ms/resp")
    ov = await c.async_overview()
    assert ov["applications"] == {"1": "farm"} and ov["profiles"] == {"p-a": "ClassA-OTAA"} and len(ov["devices"]) == 1
    assert await c.async_add_device("24e124136d000002", "Pump", "1", "p-a") == "added"
    assert await c.async_add_device("24e124136d000001", "Office", "1", "p-a") == "exists"
    hb.ns, hb.ns_application, hb.ns_profile = c, "1", "p-a"
    assert hb.can_provision and await hb.async_provision("24e124136d000003", "Tank 3") == "added"
    flows = len(entries.flows)
    entries.async_entry_for_domain_unique_id = lambda d, u: u == "24e124136d000003"
    data = await hb.async_sync_devices()
    assert len(data["devices"]) == 3 and len(entries.flows) == flows + 2      # 0001 and 0002 offered, 0003 known
    assert {f["device_name"] for f in entries.flows[-2:]} == {"EM300-TH Office", "Pump"}
    assert entries.flows[-2]["guess"] == "EM300-TH"
    c2 = prov.NsApiClient(h, "ms/req", "ms/nobody")
    try:
        await c2.async_request("GET", "/api/urdevices", timeout=0.2)
    except prov.NsApiError as err:
        assert "no answer" in str(err)
    else:
        raise AssertionError("expected a timeout")
    await c.async_stop()
asyncio.run(_prov())
print("provisioning ok")


# ---------------- blueprints and dashboards shipped inside the integration ----------------
import tempfile
res = load("resources")
STORES = {}
class _MemStore(Store):
    async def async_load(self): return STORES.get(self.key)
    async def async_save(self, d): STORES[self.key] = json.loads(json.dumps(d))
res.Store = _MemStore
cfgdir = pathlib.Path(tempfile.mkdtemp())
async def _executor(fn, *a): return fn(*a)
hass4 = types.SimpleNamespace(config=types.SimpleNamespace(path=lambda *p: str(cfgdir.joinpath(*p))),
                              data={"lovelace": types.SimpleNamespace(dashboards={})}, async_add_executor_job=_executor)
out = asyncio.run(res.async_install(hass4, "0.21.0"))
bp = cfgdir / "blueprints" / "automation" / "milesight_lorawan"
assert len(out["blueprints"]["written"]) == 11 and (bp / "leak.yaml").exists()
dashes = hass4.data["lovelace"].dashboards
assert set(dashes) == {"milesight-fleet", "milesight-signal", "milesight-tanks", "milesight-analytics"}
assert dashes["milesight-tanks"].saved["title"] == "Tanks & alerts" and "milesight-tanks" in PANELS
assert asyncio.run(res.async_install(hass4, "0.21.0")) == {}                 # same version: nothing to do
(bp / "leak.yaml").write_text("# my own version\n")                         # user edits a blueprint …
dashes["milesight-fleet"].saved = {"title": "Mine", "views": []}             # … and a dashboard
(bp / "alarm.yaml").unlink()
out = asyncio.run(res.async_install(hass4, "0.22.0"))
assert out["blueprints"]["written"] == ["alarm.yaml"] and out["blueprints"]["kept"] == ["leak.yaml"]
assert out["dashboards"]["kept"] == ["LoRaWAN fleet"] and dashes["milesight-fleet"].saved["title"] == "Mine"
assert "kept" in res.summary(out)
print("resources ok")
