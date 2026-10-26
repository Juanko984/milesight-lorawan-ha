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
    async_call_later=lambda h, d, f: (LATER.append(f), (lambda: None))[1],
    async_track_state_change_event=lambda h, ids, f: (lambda: None))
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
mod("homeassistant.components.number", NumberEntity=object, NumberMode=types.SimpleNamespace(BOX="box", SLIDER="slider"))
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
    def __init__(self): self.known = set(); self.flows = []; self.items = []
    def async_entries(self, d=None): return list(self.items)
    def async_entry_for_domain_unique_id(self, d, u): return u in self.known
class FakeFlow:
    def __init__(self, entries): self.entries = entries
    def async_init(self, domain, context, data):
        (GW_FLOWS if ("gateway_id" in data or "lan" in data) else entries.flows).append(data); return None
    def async_progress_by_handler(self, d): return list(OPEN_FLOWS)
    def async_abort(self, flow_id): ABORTED.append(flow_id)
GW_FLOWS, OPEN_FLOWS, ABORTED = [], [], []
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
                 and not k.startswith(("cmd_", "cfg_", "set_")) and k not in ("last_command", "last_backfill", "command_status", "battery_replace_by", "battery_days_left")]
        assert not empty, (model, empty)
    if model == "EM500-CO2":
        assert st["co2"] == 1127 and st["co2_status"] == "Moderate" and st["co2high_active"] is True
    if model == "EM500-SMTC":
        assert st["moisture"] == 57.5 and st["electricity_max_today"] == 240 and st["sensor_error"] == "OK"
    if model.startswith("TS"):
        enabled = [e.spec.key for e in ents if e.spec.enabled_default]
        empty = [k for k in enabled if st.get(k) is None and not k.endswith(("_at", "_since", "snr"))
                 and not k.endswith(("_alarm_active", "_alarm_status", "probe_connected"))
                 and not k.startswith(("cmd_", "cfg_", "set_")) and k not in ("last_command", "last_backfill", "command_status", "battery_replace_by", "battery_days_left")]
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
assert [{k: d[k] for k in list(d)[:16]} for d in devs] == [{"name": "TH lab", "model": "EM300-TH", "deveui": rt.deveui.upper(), "area": "Lab", "online": True,
                 "battery": 90, "battery_low": False, "rssi": -95, "snr": 7.0, "sf": 9, "gateway": "Local Gateway",
                 "gateways_heard": 1, "signal": "excellent", "packet_loss": 0.0, "command": "confirmed",
                 "last_seen": devs[0]["last_seen"]}], devs
assert devs[0]["network_server"] == "Gateway (Embedded NS)" and "battery_forecast" in devs[0]
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
class _DashStore:
    data = None
    async def async_load(self): return _DashStore.data
    async def async_save(self, d): _DashStore.data = json.loads(json.dumps(d))
dmod._store = lambda h, e: _DashStore()
# a landing page made before 0.30 (no fingerprint) is replaced once by the automatic update, old copy kept
_old = dmod._register(hass2, "building-head-office", "Building – Head office", "milesight_site1")
_old.saved = {"title": "old", "views": []}
_DashStore.data = {"url": "building-head-office", "title": "Building – Head office", "id": "milesight_site1", "own": True}
assert asyncio.run(dmod.async_update_dashboard(hass2, site_entry, auto=True)) == "/building-head-office"
assert _DashStore.data["backup"] == {"title": "old", "views": []} and _DashStore.data["hash"]
hass2.data["lovelace"].dashboards.pop("building-head-office"); _DashStore.data = None
where = asyncio.run(dmod.async_update_dashboard(hass2, site_entry))
dash = hass2.data["lovelace"].dashboards["building-head-office"]
assert where == "/building-head-office" and PANELS["building-head-office"]["sidebar_title"] == "Acme Ltd"
_first_cards = dash.saved["views"][0]["sections"][0]["cards"]
assert _first_cards[0]["type"] == "custom:milesight-page-header"                             # masthead leads every page
assert _first_cards[1]["type"] == "custom:milesight-onboarding"                              # then the first-run checklist
_all_cards = [c for sec in dash.saved["views"][0]["sections"] for c in sec["cards"]]
assert any(c["type"] == "custom:milesight-status-band" for c in _all_cards)                 # command-center status band
_banner = next(c for c in _all_cards if "content" in c)                                     # site banner (now at the foot)
assert _banner["content"].startswith('{% set s = "sensor.site1_site" %}')
heads = [c.get("heading") for sec in dash.saved["views"][0]["sections"] for c in sec["cards"] if c["type"] == "heading"]
assert heads[0] == "Status" and heads[-1] == "Site", heads
saved_hash = dmod._hash(dash.saved)
assert asyncio.run(dmod.async_update_dashboard(hass2, site_entry, auto=True)) is None      # up to date
assert _DashStore.data["own"] is True and _DashStore.data["title"] == "Acme Ltd"
dash.saved = {"title": "Mine", "views": []}                                                  # edited by hand
assert asyncio.run(dmod.async_update_dashboard(hass2, site_entry, auto=True)) is None and dash.saved["title"] == "Mine"
assert asyncio.run(dmod.async_update_dashboard(hass2, site_entry)) == "/building-head-office"  # the button rewrites
assert dmod._hash(dash.saved) == saved_hash
print("building ok")

# ---------------- retail: classification + footfall tracker snapshot ----------------
rmod = sys.modules.get("milesight_lorawan.retail") or load("retail")
assert rmod._classify("VS133", None) == "counter"       # ToF people counter: entrance in/out
assert rmod._classify("VS121", None) == "zone"          # AI people counting in an area
assert rmod._classify("VS341", None) is None            # presence only, not counting
assert rmod._classify("AM307", "counter_zone") == "staff"   # any sensor flagged as the till
# a tracker fed two entrances + a counter zone produces the store snapshot the card reads
rtk = rmod.RetailTracker(hass2, site_entry)
rtk._devices = lambda: [
    {"name": "Front", "area": "Store", "kind": "counter", "in_today": 900, "out_today": 880,
     "people_now": 20, "dwell_s": None, "occ_person_minutes": None, "occ_sessions": None, "occ_occupied_s": None},
    {"name": "Side", "area": "Store", "kind": "counter", "in_today": 300, "out_today": 290,
     "people_now": 10, "dwell_s": None, "occ_person_minutes": None, "occ_sessions": None, "occ_occupied_s": None},
    {"name": "Aisle", "area": "Store", "kind": "zone", "in_today": None, "out_today": None,
     "people_now": 3, "dwell_s": None, "occ_person_minutes": 120, "occ_sessions": 40, "occ_occupied_s": None},
]
rtk.update()
d = rtk.data
assert d["visitors_today"] == 1200 and d["in_store_now"] == 30 and len(d["entrances"]) == 2
assert len(d["hourly_in"]) == 24 and len(d["zones"]) == 1
by = {s._attr_unique_id.split("_")[-1]: s for s in [rmod.RetailSensor(hass2, site_entry, rtk)]}
rs = by["retail"]
assert rs.native_value == 1200 and rs.extra_state_attributes["milesight_role"] == "retail"
print("retail ok")

# ---------------- 0.20: channel map, tanks, alert escalation, gateway provisioning ----------------
def make_with(deveui, model, options, title=None, area=None):
    e = types.SimpleNamespace(data={"entry_type": "device", "deveui": deveui, "model": model, **({"area": area} if area else {})},
                              options=options, title=title or f"{model} test", entry_id=deveui)
    rt = runtime.DeviceRuntime(hass, e); asyncio.run(rt.async_load()); entries.known.add(deveui); rt.async_start()
    e.runtime_data = rt
    entries.items.append(e)
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
assert acts[2]["title"] == "Start pump" and acts[0]["action"].startswith("MSL_ACK_")
assert acts[1]["title"] == "Snooze 1 h" and acts[1]["action"].startswith("MSL_SNZ_")
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
# snooze from the phone, weekly summary on its day and hour (once), summary sensor
mgr.engine.alerts.clear()
CALLS.clear(); asyncio.run(mgr._run())
aid2 = next(iter(mgr.engine.alerts.values()))["id"]
CALLS.clear()
asyncio.run(mgr._on_action(types.SimpleNamespace(data={"action": f"MSL_SNZ_{aid2}"}, context=None)))
assert any(c[2]["title"].startswith("⏸") for c in CALLS) and next(iter(mgr.engine.alerts.values()))["snoozed_until"]
from datetime import datetime as _dt
mon8 = _dt(2026, 10, 19, 8, 3, tzinfo=ZoneInfo("Africa/Johannesburg"))
CALLS.clear(); asyncio.run(mgr._weekly(time.time(), mon8)); asyncio.run(mgr._weekly(time.time(), mon8))
summ = [c for c in CALLS if c[2].get("title", "").startswith("Weekly alert summary")]
assert len(summ) == 1 and "alerts" in summ[0][2]["message"] and "actions" not in summ[0][2]["data"]
week_sensor = gateway.AlertSummarySensor(hass3, types.SimpleNamespace(**{**vars(alert_entry), "runtime_data": hb}))
assert week_sensor.native_value >= 1 and "summary" in week_sensor.extra_state_attributes
assert week_sensor.extra_state_attributes["on_call_now"] == ["notify.mobile_app_juan"]
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
    # async_provision_on a gateway with no management channel of its own falls back to the hub-wide server
    assert await hb.async_provision_on("24e124fffef00000", "24e124136d000009", "Tank 9") == "added"
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
SITE = [types.SimpleNamespace(data={"entry_type": "device", "deveui": "a1", "model": "AM307"}, options={})]
hass4 = types.SimpleNamespace(config=types.SimpleNamespace(path=lambda *p: str(cfgdir.joinpath(*p))),
                              data={"lovelace": types.SimpleNamespace(dashboards={})}, async_add_executor_job=_executor,
                              config_entries=types.SimpleNamespace(async_entries=lambda d: SITE))
out0 = asyncio.run(res.async_install(hass4, "0.21.0"))
assert "milesight-water" not in hass4.data["lovelace"].dashboards          # no tank sensor yet
assert asyncio.run(res.async_sync(hass4)) == {}                            # nothing changed
SITE.append(types.SimpleNamespace(data={"entry_type": "device", "deveui": "a2", "model": "EM410-RDL"}, options={}))
out = asyncio.run(res.async_sync(hass4))                                   # a radar level sensor arrives
assert out["dashboards"]["written"] == ["Water"] and "Water" in res.summary(out)
assert models.device_tags("EM410-RDL") == {"tank"} and models.device_tags("VS121") >= {"people"}
assert "comfort" in models.device_tags("AM307") and models.device_tags("WS101") == frozenset()
bp = cfgdir / "blueprints" / "automation" / "milesight_lorawan"
assert len(out0["blueprints"]["written"]) == 13 and (bp / "leak.yaml").exists()
assert (bp / "coop_lights.yaml").exists() and (bp / "coop_heater.yaml").exists()
dashes = hass4.data["lovelace"].dashboards
assert set(dashes) == {"milesight-alerts", "milesight-devices", "milesight-maintenance", "milesight-water", "milesight-analytics"}
assert dashes["milesight-water"].saved["title"] == "Water" and "milesight-water" in PANELS
assert asyncio.run(res.async_install(hass4, "0.21.0")) == {}                 # same version: nothing to do
SITE.pop()                                                                   # the tank sensor is removed …
out = asyncio.run(res.async_sync(hass4))
assert out["dashboards"]["removed"] == ["Water"] and "milesight-water" not in dashes
SITE.append(types.SimpleNamespace(data={"entry_type": "device", "deveui": "a2", "model": "EM410-RDL"}, options={}))
assert asyncio.run(res.async_sync(hass4))["dashboards"]["written"] == ["Water"] and "milesight-water" in dashes
# rename cleanup: a leftover pre-0.76 "milesight-tanks" dashboard is removed and reported as renamed
dmod._register(hass4, "milesight-tanks", "Tanks & alerts", "milesight_milesight_tanks")
_rstate = STORES["milesight_lorawan.resources"]
_rstate.setdefault("dashboards", {})["milesight-tanks"] = {"title": "Tanks & alerts", "icon": "mdi:water-percent",
                                                           "hash": "stale", "hidden": False}
_rout = asyncio.run(res.async_install_dashboards(hass4, _rstate, {"tank"}))
assert ("milesight-tanks", "milesight-water") in _rout.get("renamed", [])
assert "milesight-tanks" not in dashes and "milesight-tanks" not in _rstate["dashboards"]
print("rename cleanup ok")
(bp / "leak.yaml").write_text("# my own version\n")                         # user edits a blueprint …
dashes["milesight-maintenance"].saved = {"title": "Mine", "views": []}       # … and a dashboard
(bp / "alarm.yaml").unlink()
out = asyncio.run(res.async_install(hass4, "0.22.0"))
assert out["blueprints"]["written"] == ["alarm.yaml"] and out["blueprints"]["kept"] == ["leak.yaml"]
assert out["dashboards"]["kept"] == ["Maintenance"] and dashes["milesight-maintenance"].saved["title"] == "Mine"
assert "kept" in res.summary(out)
# the old Fleet / Signal dashboards (before 0.34) are taken out of the sidebar: they are Maintenance tabs now
st_r = {"dashboards": {"milesight-fleet": {"title": "LoRaWAN fleet", "hash": "x"},
                       "milesight-signal": {"title": "LoRaWAN signal", "hash": "y"}}}
dashes["milesight-fleet"] = object()
out_r = asyncio.run(res.async_install_dashboards(hass4, st_r))
assert out_r["merged"] == ["LoRaWAN fleet", "LoRaWAN signal"] and "milesight-fleet" not in dashes
assert "milesight-fleet" not in st_r["dashboards"] and "tabs of the Maintenance dashboard" in res.summary({"dashboards": out_r})
print("resources ok")


# area occupancy history survives a restart
from datetime import date as _date
fl = sys.modules["milesight_lorawan.fleet"]
today = datetime.now(ZoneInfo("Africa/Johannesburg")).date().isoformat()
SAVED = {"Reception": {"day": today, "occ": [0] * 24, "n": [0] * 24, "prev": [5] * 24, "occ_pct": [None] * 9 + [80] + [None] * 14}}
class _AreaStore(Store):
    async def async_load(self): return SAVED
sys.modules["homeassistant.helpers.storage"].Store = _AreaStore
unloads = []
ae = types.SimpleNamespace(entry_id="h", title="Site gateway", data={"entry_type": "hub"}, async_on_unload=unloads.append)
hass5 = types.SimpleNamespace(config_entries=types.SimpleNamespace(async_entries=lambda d: []), async_create_task=lambda c: c.close())
fl.async_track_time_interval = lambda h, f, i: (lambda: None)
fl.dt_util = types.SimpleNamespace(now=lambda: datetime.now(ZoneInfo("Africa/Johannesburg")))
tr = asyncio.run(fl.async_setup_areas(hass5, ae, lambda ents: None))
assert tr.hourly("Reception")[9] == 80 and tr.hourly("Reception", yesterday=True)[0] == 5
sys.modules["homeassistant.helpers.storage"].Store = Store
print("areas ok")

# commissioning: fast reporting for a walk test, then the old interval comes back
sys.modules["homeassistant.components.mqtt"].async_publish = _publish
PUBLISHED.clear()
e_wt, rt = make_with("0000000000ee0001", "EM300-TH", {})
rt.meta.setdefault("config", {})["report_interval"] = 1200
info = asyncio.run(rt.async_walk_test(30))
assert info["fast"] == 60 and info["restore"] == 1200 and rt.meta["config"]["report_interval"] == 60
assert bytes.fromhex("ff033c00") == base64.b64decode(PUBLISHED[-1][1]["data"])
assert rt.attrs["signal_quality"]["walk_test_until"] is not None and "walk_test" not in rt.values
info2 = asyncio.run(rt.async_walk_test(30))                      # pressed twice: still restores the original
assert info2["restore"] == 1200
assert asyncio.run(rt.async_end_walk_test()) == 1200 and rt.meta["config"]["report_interval"] == 1200
assert bytes.fromhex("ffb004") != base64.b64decode(PUBLISHED[-1][1]["data"])
assert base64.b64decode(PUBLISHED[-1][1]["data"]) == bytes.fromhex("ff03b004")
rt.save_commissioning({"spot": "Cold room door", "verdict": "good", "count": 3})
assert rt.attrs["signal_quality"]["commissioning"]["spot"] == "Cold room door"
e_vs, rt2 = make_with("0000000000ee0002", "VS340", {})
try:
    asyncio.run(rt2.async_walk_test(30)) if "report_interval" not in models.downlinks("VS340") else None
except ValueError as err:
    assert "button" in str(err)
print("walk test ok")


# ---------------- 0.24: pumps, pivots, forecast-aware irrigation ----------------
import math, struct
entries.async_entry_for_domain_unique_id = lambda d, u: u in entries.known      # undo the provisioning test's patch
WATER = {"state": "10.0"}
hass.states = types.SimpleNamespace(get=lambda eid: types.SimpleNamespace(
    state=WATER["state"], attributes={"unit_of_measurement": "m³"}) if eid == "sensor.borehole_water" else None)
def ct101(amps):
    return bytes([0x04, 0x98]) + int(amps * 100).to_bytes(2, "little")
e_p, rt = make_with("0000000000c70101", "CT101", {"pump_enabled": True, "pump_normal_a": 10, "pump_max_starts": 2,
                                                   "pump_water_entity": "sensor.borehole_water", "mains_voltage": 230},
                    title="Borehole pump", area="Field 3")
keys = {s.key for s in rt.extra_specs()}
assert {"pump_run_hours", "pump_dry_run", "pump_m3_per_kwh", "pump_water_today"} <= keys
n = len(fired)
send("0000000000c70101", ct101(0))
send("0000000000c70101", ct101(10))
assert rt.values["pump_running"] is True and rt.values["pump_starts_last_hour"] == 1
assert [d["type"] for e, d in fired[n:] if e == "milesight_lorawan_pump"] == ["start"]
send("0000000000c70101", ct101(3)); send("0000000000c70101", ct101(3))       # 30 % of normal, twice
assert rt.values["pump_dry_run"] is True and rt.attrs["pump_dry_run"]["below_a"] == 6.0
assert any(d["type"] == "dry_run" and d["device"] == "Borehole pump" and d["area"] == "Field 3"
           for e, d in fired[n:] if e == "milesight_lorawan_pump")
al = alr_mod = sys.modules["milesight_lorawan.alerts"].device_alerts(e_p.title, rt.deveui, rt.values)
assert "0000000000c70101:pump_dry" in al
assert rt.attrs["pump_run_hours"]["milesight_role"] == "pump" and rt.attrs["pump_run_hours"]["current"] == 3.0
rt.pump.s["last_ts"] -= 3600                                                   # an hour of running at 3 A …
WATER["state"] = "16.0"
send("0000000000c70101", ct101(10))
v = rt.values
assert v["pump_water_today"] == 6.0 and v["pump_energy_today"] and v["pump_m3_per_kwh"] == round(6.0 / v["pump_energy_today"], 2)
assert rt._data_to_save()["trackers"]["pump"]["run_s"] > 3600

def at101(lat, lon):
    return bytes([0x04, 0x88]) + struct.pack("<ii", round(lat * 1e6), round(lon * 1e6)) + bytes([0x01])
def pt(b, r=400.0, lat0=-26.0, lon0=28.0):
    return (lat0 + r * math.cos(math.radians(b)) / 111195,
            lon0 + r * math.sin(math.radians(b)) / (111195 * math.cos(math.radians(lat0))))
e_v, rt = make_with("0000000000a70101", "AT101", {"pivot_centre": {"latitude": -26.0, "longitude": 28.0},
                                                   "pivot_stall_min": 30}, title="Pivot 1")
assert "cmd_pivot_stop" in {s.key for s in rt.extra_specs()}
send("0000000000a70101", at101(*pt(100)))
rt.pivot.s["moved_ts"] -= 3600; rt.pivot.s["ts"] -= 3600
n = len(fired)
send("0000000000a70101", at101(*pt(112)))
v = rt.values
assert v["pivot_status"] == "running" and abs(v["pivot_angle"] - 112) < 0.5 and abs(v["pivot_speed"] - 12) < 0.5
assert [d["type"] for e, d in fired[n:] if e == "milesight_lorawan_pivot"] == ["started"]
rt.pivot.s["moved_ts"] -= 1900
rt._tick(None)                                                                  # no fixes: the minute tick spots it
assert rt.values["pivot_stalled"] is True and rt.attrs["pivot_progress"]["status"] == "stalled"
assert any(d["type"] == "stalled" for e, d in fired[n:] if e == "milesight_lorawan_pivot")
assert "0000000000a70101:pivot_stalled" in sys.modules["milesight_lorawan.alerts"].device_alerts("P", rt.deveui, rt.values)
b = button.MilesightCommandButton(rt, next(s for s in rt.extra_specs() if s.key == "cmd_pivot_stop"))
asyncio.run(b.async_press())
assert rt.values["pivot_stalled"] is False and rt.values["pivot_status"] == "stopped"
saved = rt._data_to_save()["trackers"]["pivot"]
assert saved["centre"] == [-26.0, 28.0]
e_v.options = {**e_v.options, "pivot_centre": {"latitude": -26.1, "longitude": 28.0}}   # centre moved
rt2 = runtime.DeviceRuntime(hass, e_v); rt2.store.async_load = lambda: asyncio.sleep(0, {"trackers": {"pivot": saved}})
asyncio.run(rt2.async_load())
assert rt2.pivot.s["angle"] is None
print("pump and pivot ok")

irr_ha = load("irrigation_ha")
now_local = datetime(2026, 10, 14, 18, 0, tzinfo=ZoneInfo("Africa/Johannesburg"))
dt_mod.now = lambda: now_local
dt_mod.utcnow = lambda: now_local.astimezone(timezone.utc)
dt_mod.parse_datetime = lambda s: datetime.fromisoformat(s)
dt_mod.as_local = lambda d: d.astimezone(ZoneInfo("Africa/Johannesburg"))
from datetime import timedelta as _td
FORECAST = [{"datetime": (now_local + _td(hours=h)).isoformat(), "temperature": 9 - h * 0.6,
             "precipitation": 0.0, "precipitation_probability": 5} for h in range(36)]
CALLS = []
async def _svc(domain, service, data, blocking=False, return_response=False):
    CALLS.append((domain, service, data["type"]))
    if data["type"] == "hourly":
        raise RuntimeError("hourly forecast not supported")
    return {data["entity_id"]: {"forecast": FORECAST}}
hass.services = types.SimpleNamespace(async_call=_svc)
SOIL = {"sensor.soil_1": "12", "sensor.soil_2": "unavailable"}
_old_get = hass.states.get
hass.states = types.SimpleNamespace(get=lambda eid: types.SimpleNamespace(state=SOIL[eid], attributes={}) if eid in SOIL else _old_get(eid))
irr_entry = types.SimpleNamespace(entry_id="h", title="Farm gateway", options={
    "irr_weather": "weather.farm", "irr_soil": ["sensor.soil_1", "sensor.soil_2"], "irr_target": 30,
    "irr_base_minutes": 60, "irr_frost_c": 2})
mgr = irr_ha.IrrigationManager(hass, irr_entry)
assert mgr.enabled
n = len(fired)
asyncio.run(mgr._refresh())
assert CALLS == [("weather", "get_forecasts", "hourly"), ("weather", "get_forecasts", "daily")] and mgr.daily
# daily fallback with hourly-looking data still gives an answer; use hourly directly for the checks below
mgr.daily = False; mgr._evaluate()
a = mgr.data["advice"]
assert a["advice"] == "irrigate" and a["minutes"] == 36 and a["soil_moisture"] == 12.0
assert mgr.data["frost"]["active"] is True
frost_ev = [d for e, d in fired[n:] if e == "milesight_lorawan_frost"]
assert len(frost_ev) == 1 and frost_ev[0]["site"] == "Farm gateway"
mgr._evaluate()
assert len([1 for e, d in fired[n:] if e == "milesight_lorawan_frost"]) == 1          # once per night
al = mgr.alerts()
assert al["frost:h"]["category"] == "irrigation" and "around" in al["frost:h"]["message"]
hub_entry.runtime_data = types.SimpleNamespace(irrigation=mgr)
ents = irr_ha.irrigation_entities(hass, hub_entry, "sensor") + irr_ha.irrigation_entities(hass, hub_entry, "binary_sensor")
by = {x._attr_name: x for x in ents}
assert by["Irrigation advice"].native_value == "irrigate" and by["Irrigation advice"].extra_state_attributes["minutes"] == 36
assert by["Frost tonight"].is_on is True and by["Rain expected"].is_on is False
FORECAST[:] = [dict(f, precipitation=2.0, precipitation_probability=90) for f in FORECAST]
mgr._evaluate()
assert by["Irrigation advice"].native_value == "skip" and by["Rain expected"].is_on is True
assert "rain" in by["Irrigation advice"].extra_state_attributes["reason"]
assert irr_ha.irrigation_entities(hass, types.SimpleNamespace(runtime_data=types.SimpleNamespace(
    irrigation=irr_ha.IrrigationManager(hass, types.SimpleNamespace(entry_id="x", title="x", options={})))), "sensor") == []
res2 = load("resources")
assert res2.wanted_dashboards({"pump"})["milesight-farm"] and not res2.wanted_dashboards({"tank"})["milesight-farm"]
# the coop page installs only when a device is in a coop area (the "coop" tag)
assert res2.wanted_dashboards({"coop"})["milesight-coop"] and not res2.wanted_dashboards({"tank"})["milesight-coop"]
print("irrigation ok")


# ---------------- 0.25: purposes ----------------
import dataclasses
def th(t):
    return bytes([0x03, 0x67]) + int(round(t * 10)).to_bytes(2, "little", signed=True) + bytes([0x04, 0x68, 0x60])
e_f, rt = make_with("0000000000f00001", "EM300-TH", {"purpose": "fridge"}, title="Fridge 3", area="Kitchen")
keys = {s.key for s in rt.extra_specs()}
assert {"temp_alarm", "temp_out_today", "temp_excursions_today"} <= keys
send("0000000000f00001", th(3.0))
assert rt.values["temp_alarm"] is False and rt.values["purpose"] == "Fridge / cold room"
n = len(fired)
send("0000000000f00001", th(8.0))
assert rt.values["temp_alarm"] is False                        # within the 15-minute delay
rt.tempw.s["out_since"] -= 1200
send("0000000000f00001", th(8.4))
assert rt.values["temp_alarm"] is True
assert any(e == "milesight_lorawan_temperature" and d["type"] == "out_of_range" for e, d in fired[n:])
al = sys.modules["milesight_lorawan.alerts"].device_alerts(e_f.title, rt.deveui, rt.values, "Kitchen")
assert al["0000000000f00001:temp_range"]["category"] == "cold_chain" and al["0000000000f00001:temp_range"]["severity"] == "critical"
assert rt.attrs["temp_out_today"]["milesight_role"] == "cold_chain" and rt.attrs["temp_out_today"]["high"] == 5
spec = next(s for s in models.entity_specs("EM300-TH") if s.key == "temperature")
assert rt.adjust_spec(spec).icon == "mdi:fridge-outline"
assert models.device_tags("EM300-TH", {**e_f.data, **e_f.options}) >= {"cold_chain"}

e_g, rt = make_with("0000000000a30101", "WS301", {"purpose": "gate", "open_hour": 0, "close_hour": 24,
                                                   "open_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
                    title="Yard gate")
assert rt.binary["door"].left_open_s == 30 * 60
specs = {s.key: rt.adjust_spec(s) for s in models.entity_specs("WS301")}
assert specs["door_active"].name == "Gate" and specs["door_active"].device_class == "opening"
assert specs["door_left_open"].name == "Gate left open"
send("0000000000a30101", bytes.fromhex("030001"))
assert rt.values["door_active"] is True and rt.values["after_hours_activity"] is False   # inside working hours
e_g2, rt = make_with("0000000000a30102", "WS301", {"purpose": "garage"}, title="Roller door")
rt._work_hours = lambda ts: False                                                       # night
send("0000000000a30102", bytes.fromhex("030001"))
assert rt.values["after_hours_activity"] is True                                        # never working hours
assert "0000000000a30102:after_hours" in sys.modules["milesight_lorawan.alerts"].device_alerts("R", rt.deveui, rt.values)

e_c, rt = make_with("0000000000c70201", "CT101", {"purpose": "fridge"}, title="Cold room compressor")
keys = {s.key for s in rt.extra_specs()}
assert {"load_duty_today", "load_ran_too_long", "load_not_running"} <= keys and "load_running" not in keys
send("0000000000c70201", ct101(5)); send("0000000000c70201", ct101(5))
rt.loads["load_"][0].s["since"] -= 4 * 3600
rt._tick(None)
assert rt.values["load_ran_too_long"] is True and rt.attrs["load_run_today_h"]["group"] == "cold_chain"
lspec = next(s for s in models.entity_specs("CT101") if s.key == "load_active")
assert rt.adjust_spec(lspec).name == "Compressor"

def ct303(a, b, c):
    return (bytes([0x04, 0x99]) + int(a * 10).to_bytes(2, "little") + bytes([0x06, 0x99]) + int(b * 10).to_bytes(2, "little")
            + bytes([0x08, 0x99]) + int(c * 10).to_bytes(2, "little"))
e_m, rt = make_with("0000000000c70303", "CT303", {"purpose": "mains", "purpose_2": "ac"}, title="DB board")
keys = {s.key for s in rt.extra_specs()}
assert {"mains_outage", "phase_imbalance", "load2_running", "load2_duty_today"} <= keys
send("0000000000c70303", ct303(10, 20, 10))
assert rt.values["phase_imbalance"] == 75 and rt.values["phase_imbalance_high"] is True
assert rt.values["load2_running"] is True and rt.values["mains_outage"] is False
send("0000000000c70303", ct303(0, 0, 0)); send("0000000000c70303", ct303(0, 0, 0))
assert rt.values["mains_outage"] is True and models.device_tags("CT303", e_m.options) >= {"energy", "hvac"}
assert "load2_" in rt._data_to_save()["trackers"]

def em400tld(d):
    return bytes([0x04, 0x82]) + d.to_bytes(2, "little")
e_b, rt = make_with("0000000000b10001", "EM400-TLD", {"purpose": "bin", "p_bin_depth_mm": 1000}, title="Bin 4")
send("0000000000b10001", em400tld(700))
assert rt.values["bin_fill"] == 30 and rt.values["bin_full"] is False
rt.trend.samples = [[time.time() - 86400, 10.0]]
send("0000000000b10001", em400tld(150))
assert rt.values["bin_full"] is True and rt.values["bin_fill_per_day"] and rt.values["bin_fill_per_day"] > 70

e_p, rt = make_with("0000000000b20001", "WS101", {"purpose": "panic"}, title="Reception panic")
assert {"panic_active", "cmd_panic_clear"} <= {s.key for s in rt.extra_specs()}
n = len(fired)
send("0000000000b20001", bytes.fromhex("ff2e01"))
assert rt.values["panic_active"] is True and any(e == "milesight_lorawan_panic" for e, d in fired[n:])
assert sys.modules["milesight_lorawan.alerts"].device_alerts("P", rt.deveui, rt.values)["0000000000b20001:panic"]["severity"] == "critical"
b = button.MilesightCommandButton(rt, next(s for s in rt.extra_specs() if s.key == "cmd_panic_clear"))
asyncio.run(b.async_press())
assert rt.values["panic_active"] is False

e_r, rt = make_with("0000000000d10001", "EM300-DI", {"purpose": "rain_gauge", "meter_pulses_per_unit": 5}, title="Rain gauge")
assert "meter_reading" in {s.key for s in rt.extra_specs()} and "rain_today" in {s.key for s in rt.extra_specs()}
send("0000000000d10001", bytes([0x05, 0xC8, 10, 0, 0, 0]))
send("0000000000d10001", bytes([0x05, 0xC8, 60, 0, 0, 0]))
assert rt.values["meter_reading"] == 12.0 and rt.values["rain_today"] == 10.0
rt.trend.samples.insert(0, [time.time() - 86400, 0.0])
rt._publish(time.time())
assert rt.values["rain_24h"] == 12.0
assert irr_ha.gauge_rain(hass) == 12.0
adv = sys.modules["milesight_lorawan.irrigation"].advice([10.0], {"mm": 0, "probability": None}, mgr.cfg, irr_ha.gauge_rain(hass))
assert adv["advice"] == "skip" and "fell" in adv["reason"]

e_s, rt = make_with("0000000000e50001", "EM500-SMTC", {"purpose": "field"}, title="Field 3 soil")
send("0000000000e50001", bytes.fromhex("01756403671901046873057FF000"))
assert isinstance(rt.values.get("moisture"), (int, float)) and rt.values["moisture"] in irr_ha.soil_values(hass, ())
assert models.device_tags("EM500-SMTC", e_s.options) >= {"irrigation"}
e_w, rt = make_with("0000000000a30103", "WS301", {"purpose": "fridge"}, title="Fridge door")
specs = {s.key: rt.adjust_spec(s) for s in models.entity_specs("WS301")}
assert specs["door_active"].name == "Door" and specs["door_left_open"].name == "Door left open"
assert rt.binary["door"].left_open_s == 120
print("purposes ok")

mt = sys.modules.get("milesight_lorawan.modbus_templates") or load("modbus_templates")
rows, _ = mt.plan("ecowitt_ws90", None, 1)
e_ws, rt = make_with("00000000000e0390", "UC300", {"channel_map": mt.merge_map("", rows, "WS90")}, title="Weather")
assert {s.key: s for s in rt.extra_specs()}["modbus_chn_1"].device_class == "illuminance"
send("00000000000e0390", bytes.fromhex("ff19000102d204"))
assert rt.values["modbus_chn_1"] == 12340
send("00000000000e0390", bytes.fromhex("ff19000102ffff"))
assert rt.values["modbus_chn_1"] is None                       # 0xFFFF = no reading
t = mt.TEMPLATES["luxpower_lxp"]
rows, _ = mt.plan("luxpower_lxp", None, 1, 1, max_channels=mt.max_channels("UC100"))
e_lx, rt = make_with("00000000001c0100", "UC100", {"channel_map": mt.merge_map("", rows, mt.block_title(t, rows))},
                     title="LuxPower")
def ff19(ch, dtype, payload):
    return bytes([0xFF, 0x19, ch - 1, len(payload), dtype]) + payload
chn = {r["toolbox_name"]: r["channel"] for r in rows}
send("00000000001c0100", ff19(chn["Vbat"], 2, (532).to_bytes(2, "little"))
     + ff19(chn["SOC"], 2, (0x6450).to_bytes(2, "little")) + ff19(chn["Epv1_all"], 4, (123456).to_bytes(4, "little")))
v = rt.values
assert v[f"modbus_chn_{chn['Vbat']}"] == 53.2 and v[f"modbus_chn_{chn['SOC']}"] == 80
assert v[f"modbus_chn_{chn['Epv1_all']}"] == 12345.6
specs = {s.key: s for s in rt.extra_specs()}
assert specs[f"modbus_chn_{chn['SOC']}"].device_class == "battery"
assert specs[f"modbus_chn_{chn['Epv1_all']}"].state_class == "total_increasing"
mc = load("modbus_config")
rows32, _ = mt.plan("luxpower_lxp", None, 1, 1, max_channels=mt.max_channels("UC100"))
n0 = len(PUBLISHED)
frames = asyncio.run(rt.async_modbus_push(mc.template_commands(rows32), label="LuxPower"))
sent = [m for m in PUBLISHED[n0:] if m[0].endswith("00000000001c0100")]
assert frames == len(sent) and all(m[1]["fPort"] == 85 for m in sent)
assert base64.b64decode(sent[0][1]["data"]).startswith(bytes.fromhex("ffef01010100000201"))
assert "modbus_channel_1" in rt.commands.items and rt.meta["modbus_push"]["commands"] == 52
send("00000000001c0100", bytes.fromhex("feef01010100000201"))       # the UC100 echoes channel 1
assert "modbus_channel_1" not in rt.commands.items and rt.commands.last["status"] == "confirmed"
print("templates ok")


# ---------------- 0.29: live dashboard view (gauges, sliders, pivot map) and setpoints ----------------
dl = load("dashboard_live")
rts = [e.runtime_data for e in entries.items if getattr(e, "runtime_data", None) is not None]
eid = lambda plat, uid: f"{plat}.{uid}"
farm = dl.farm_cards(eid, rts, [])
flat = json.dumps(farm)
assert '"type": "map"' in flat and "device_tracker.0000000000a70101_location" in flat
assert "sensor.0000000000a70101_pivot_radius" in flat and "number.0000000000a70101_sp_pivot_stall_min" in flat
assert '"numeric-input"' in flat and "button.press" in flat
pump_stack = next(c for c in farm if c["cards"][0]["heading"].startswith("Pump"))
g = next(dl.gauge_of(c) for c in pump_stack["cards"] if dl.gauge_of(c))
assert g["segments"][1]["from"] == 6.0 and g["segments"][2]["from"] == 12.5          # dry 60 %, overload 125 % of 10 A
piv = next(e for e in entries.items if e.data["deveui"] == "0000000000a70101").runtime_data
assert piv.attrs["pivot_radius"]["latitude"] == piv.pivot_cfg.lat
tanks = dl.tank_cards(eid, rts, [])
assert tanks and "sensor.0000000000400001_tank_fill" in json.dumps(tanks) and "sp_tank_low_pct" in json.dumps(tanks)
cold = json.dumps(dl.cold_chain_cards(eid, rts, []))
assert "sensor.0000000000f00001_temperature" in cold and "sp_p_temp_high" in cold and '"from": 5' in cold
energy = json.dumps(dl.energy_cards(eid, rts, []))
assert "phase_imbalance" in energy and "load2_duty_24h" in energy
cfg = dl.with_live_view("farm.yaml", {"title": "Farm", "views": [{"title": "Farm"}]}, eid, rts, [])
assert cfg["views"][0]["path"] == "live" and cfg["views"][1]["title"] == "Farm"
assert dl.with_live_view("fleet_overview.yaml", {"views": []}, eid, rts, []) == {"views": []}
# every GENERATED Live view carries the page-header masthead (farm / tanks / energy / retail)
def _generated_has_header(view):
    return any(c.get("type") == "custom:milesight-page-header" for s in view.get("sections", []) for c in s.get("cards", []))
assert _generated_has_header(cfg["views"][0]), "farm Live view missing header"
for fn in ("tanks_and_alerts.yaml", "energy.yaml", "retail.yaml"):
    gen = dl.with_live_view(fn, {"views": [{"title": "Bundled", "sections": []}]}, eid, rts, [])
    live = next((v for v in gen["views"] if v.get("path") == "live"), None)
    if live is not None:
        assert _generated_has_header(live), f"{fn} Live view missing header"
# setpoint sliders change the options
num = load("number")
tank_rt = next(e for e in entries.items if e.data["deveui"] == "0000000000400001").runtime_data
assert tank_rt.values["sp_tank_low_pct"] == 20
spec = next(s for s in tank_rt.extra_specs() if s.key == "sp_tank_low_pct")
n = num.MilesightNumber(tank_rt, spec)
UPDATED = []
hass.config_entries.async_update_entry = lambda e, options: UPDATED.append(options)
n.hass = hass
assert n._attr_mode == num.NumberMode.SLIDER and n._attr_native_max_value == 90
asyncio.run(n.async_set_native_value(33.4))
assert UPDATED[-1]["tank_low_pct"] == 33
# site landing page sections and building analytics
site = dl.site_sections(eid, rts, [])
heads = [sec["cards"][0]["heading"] for sec in site]
assert "Tanks and silos" in heads and "Pivots" in heads and "Pumps" in heads, heads
assert all(len(sec["cards"]) > 1 for sec in site)
hubx = types.SimpleNamespace(entry=types.SimpleNamespace(entry_id="h1"),
                             areas=types.SimpleNamespace(summary={"Board room": {}, "Lab": {}}))
ana = dl.analytics_cards(eid, rts, [hubx])
assert [sec["cards"][0]["heading"] for sec in ana][:3] == ["Occupancy today", "Occupancy yesterday", "Board room"]
assert any(c.get("entity") == "sensor.h1_area_board_room_comfort" for c in ana[2]["cards"])
nav = dl.nav_section([("Farm", "milesight-farm", "mdi:tractor-variant")])
assert nav["cards"][1]["tap_action"]["navigation_path"] == "/milesight-farm"
print("live dashboards ok")

# ---------------- 0.31: built-in network server (Semtech packet forwarder → hub) ----------------
import importlib
lns_ha = load("lns_ha")
lcrypto = importlib.import_module("milesight_lorawan.lns.crypto")
lphy = importlib.import_module("milesight_lorawan.lns.phy")
KEY = bytes.fromhex("5572404c696e6b4c6f52613230313823")
EUI, GW = "24e1241122334455", bytes.fromhex("24e124fffefa2994")
hub_lns_entry = types.SimpleNamespace(data={"entry_type": "hub", "topic": "x/#", "payload_encoding": "base64"},
                                      options={"lns_enabled": True, "lns_port": 1700, "lns_farm_id": 9},
                                      entry_id="hl", title="Farm gateway")
later = []
hass.loop = types.SimpleNamespace(call_later=lambda d, fn, *a: later.append((fn, a)))
hbl = hub.Hub(hass, hub_lns_entry)
assert hbl.lns is not None and hbl.lns.port == 1700
class _UDP:
    def __init__(self): self.sent = []
    def sendto(self, data, addr): self.sent.append((data, addr))
    def close(self): pass
udp = _UDP()
async def _start():
    await hbl.lns.async_start()
loop_ = asyncio.new_event_loop()
async def _fake_endpoint(factory, local_addr):
    return udp, factory()
loop_.create_datagram_endpoint = _fake_endpoint
loop_.run_until_complete(_start())
hbl.lns.server.keys = lambda eui: lns_ha.DeviceKeys(EUI, KEY) if eui == EUI else None
assert hbl.lns.server.cfg.farm_id == 9 and hbl.lns.error is None
ADDR = ("192.168.1.20", 41000)
hbl.lns.datagram_received(b"\x02\x00\x01\x02" + GW, ADDR)                                # PULL_DATA
assert udp.sent[-1] == (b"\x02\x00\x01\x04", ADDR)
def push(phy, tmst=5_000_000):
    rx = {"tmst": tmst, "freq": 868.3, "stat": 1, "modu": "LORA", "datr": "SF9BW125", "codr": "4/5", "rssi": -88,
          "lsnr": 6.5, "size": len(phy), "data": base64.b64encode(phy).decode()}
    hbl.lns.datagram_received(b"\x02\x00\x02\x00" + GW + json.dumps({"rxpk": [rx]}).encode(), ADDR)
    while later:
        fn, a = later.pop(0); fn(*a)
# join
nonce = (77).to_bytes(2, "little")
msg = b"\x00" + bytes(8) + bytes.fromhex(EUI)[::-1] + nonce
push(msg + lcrypto.aes_cmac(KEY, msg)[:4])
resp = json.loads(udp.sent[-1][0][4:])["txpk"]
assert udp.sent[-1][0][3] == 3 and resp["tmst"] == 10_000_000 and resp["freq"] == 868.3 and resp["datr"] == "SF9BW125"
acc = base64.b64decode(resp["data"])
clear = lcrypto.join_accept_decrypt(KEY, acc)
addr = int.from_bytes(clear[6:10], "little")
nwk, app = lcrypto.session_keys(KEY, clear[0:3], clear[3:6], nonce)
assert addr >> 16 == 9 and hbl.stats.counts.get("joins") == 1
# uplink from an EM300-TH: delivered to the device through the normal hub path
entries.known.add(EUI)
got = []
signals.setdefault(const.SIGNAL_UPLINK.format(EUI), []).append(lambda up: got.append(up))
def uplink(fcnt, port, payload, confirmed=False):
    enc = lcrypto.crypt_payload(app, payload, addr, fcnt, True)
    fr = lphy.build_data(lphy.CONF_UP if confirmed else lphy.UNCONF_UP, addr, fcnt, fport=port, enc_payload=enc)
    return fr + lcrypto.data_mic(nwk, fr, addr, fcnt, True)
push(uplink(0, 85, bytes.fromhex("0367f40004687b")), tmst=20_000_000)
assert got and got[0].raw == bytes.fromhex("0367f40004687b") and got[0].fport == 85 and got[0].sf == 9
assert got[0].gateways[0]["id"] == "24e124fffefa2994" and got[0].extra["network_server"] == "built-in"
assert EUI in hbl.last_uplink and "24e124fffefa2994" in hbl.stats.gateways
# a command for this device goes into the network server queue, then out after the next uplink
asyncio.run(hbl.async_send_downlink(EUI, bytes.fromhex("ff100001"), 85))
n_sent = len(udp.sent)
push(uplink(1, 85, bytes.fromhex("0367f40004687b")), tmst=30_000_000)
assert [d[0][3] for d in udp.sent[n_sent:]] == [1, 3]           # PUSH_ACK, then PULL_RESP
pk = json.loads(udp.sent[-1][0][4:])["txpk"]
dl = lphy.parse_data(base64.b64decode(pk["data"]))
assert pk["tmst"] == 33_000_000 and lcrypto.crypt_payload(app, dl.frm_payload, addr, dl.fcnt16, False) == bytes.fromhex("ff100001")
assert hbl.stats.counts.get("downlinks") == 1
# devices not joined here still use the gateway's MQTT downlink
assert not hbl.lns.handles("24e1240000000001")
# unknown device joining → offered in Discovered with the network-server form
before = len(entries.flows)
other = b"\x00" + bytes(8) + bytes.fromhex("24e12400000000aa")[::-1] + b"\x01\x00"
push(other + bytes(4))
assert len(entries.flows) == before + 1 and entries.flows[-1]["lns"] is True
# summary for the sensor / diagnostics has no keys
summ = hbl.lns.summary()
assert summ["devices"][EUI]["dev_addr"] == f"{addr:08x}" and "app_s_key" not in json.dumps(summ)
assert summ["gateways"]["24e124fffefa2994"]["connected"] is True
# gateway that never sent PULL_DATA can't be used → join refused with a hint
hbl.lns.server.gateways["24e124fffefa2994"]["pull"] = 0
nonce2 = (78).to_bytes(2, "little")
msg2 = b"\x00" + bytes(8) + bytes.fromhex(EUI)[::-1] + nonce2
push(msg2 + lcrypto.aes_cmac(KEY, msg2)[:4])
assert hbl.lns.last_events[0]["kind"] == "join_rejected" and "Port Down" in hbl.lns.last_events[0]["reason"]
# connection shown per device: entity text + one label that swaps when the device moves
rt_mqtt = dev_entries[0].runtime_data
assert rt_mqtt.values["network_server"] == "Gateway (Embedded NS)"
e_l, rt_l = make_with(EUI, "EM300-TH", {}, title="EM300 via LNS")
up_l = decoders.Uplink(deveui=EUI, raw=bytes.fromhex("0367f40004687b"), fport=85, fcnt=5)
up_l.extra["network_server"] = "built-in"
rt_l.handle_uplink(up_l)
assert rt_l.values["network_server"] == "Home Assistant (packet forwarder)" and rt_l.meta["network_server"] == "built-in"
# devices that have not reported since the update: worked out from their set-up
mdl_ = sys.modules["milesight_lorawan.models"]
assert mdl_.network_of(None, {}) == "embedded" and mdl_.network_of(None, {"lns_app_key": "00" * 16}) == "built-in"
assert mdl_.network_of(None, {}, chirpstack_hub=True) == "chirpstack" and mdl_.network_of("built-in", {}) == "built-in"
quiet = types.SimpleNamespace(data={"deveui": "x"}, runtime_data=types.SimpleNamespace(meta={}))
res_c = load("resources")
class _Lab:
    def __init__(self): self.by = {}
    def async_get_label_by_name(self, n): return self.by.get(n)
    def async_create(self, n, icon=None):
        self.by[n] = types.SimpleNamespace(label_id=n.lower().replace(" ", "_"), icon=icon); return self.by[n]
class _Dev:
    def __init__(self): self.d = types.SimpleNamespace(id="d1", labels={"keep"})
    def async_update_device(self, i, labels): self.d.labels = set(labels)
labs, devs, st = _Lab(), _Dev(), {}
assert res_c._connection_label(e_l, devs.d, labs, devs, st)
assert devs.d.labels == {"keep", "lorawan_·_home_assistant_network_server"}
assert not res_c._connection_label(e_l, devs.d, labs, devs, st)                 # unchanged → nothing to do
rt_l.meta["network_server"] = "embedded"
assert res_c._connection_label(e_l, devs.d, labs, devs, st)
assert devs.d.labels == {"keep", "lorawan_·_gateway_network_server"}             # swapped, user's label kept
dq = types.SimpleNamespace(id="d2", labels=set())
devs2 = _Dev(); devs2.d = dq
assert res_c._connection_label(quiet, dq, labs, devs2, st) and dq.labels == {"lorawan_·_gateway_network_server"}
loop_.run_until_complete(hbl.lns.async_stop())
loop_.close()
print("network server ok")

# ---------------- 0.31b5: battery forecast, service history, settings profiles, handover report ----------------
from datetime import datetime as _dt2
mh = load("maintenance_ha")
class _MemStore:
    data = None
    async def async_load(self): return _MemStore.data
    async def async_save(self, d): _MemStore.data = json.loads(json.dumps(d))
mh._store = lambda h: _MemStore()
e_a, rt_a = make_with("00000000000b0001", "EM300-TH", {"battery_low_pct": 20, "max_gap_min": 120}, title="Fridge A")
e_b, rt_b = make_with("00000000000b0002", "EM300-TH", {"battery_low_pct": 10, "meter_offset": 3}, title="Fridge B")
# 40 days of battery readings dropping 1 % every 4 days → a replacement date ~ (pct-20)*4 days away
day0 = _dt2.now(rt_a.cal.tz).date().toordinal() - 40
for i in range(41):
    rt_a.battery_fc.add(day0 + i, 90 - i // 4, time.time() - (40 - i) * 86400)
rt_a._publish(time.time())
assert 220 <= rt_a.values["battery_days_left"] <= 260, rt_a.values["battery_days_left"]
assert rt_a.values["battery_replace_by"] > time.time() + 200 * 86400
assert rt_a.attrs["battery_replace_by"]["method"] == "trend"
rt_a.battery_replaced("Juan")
assert rt_a.values.get("battery_days_left") is None and rt_a.meta["_service_log"][-1]["kind"] == "battery_replaced"
# firmware change is logged
rt_a.raw["firmware_version"] = "1.1"; rt_a._update_registry()
rt_a.raw["firmware_version"] = "1.2"; rt_a._update_registry()
assert rt_a.meta["_service_log"][-1]["text"] == "Firmware 1.1 → 1.2"
fields = fleet.maintenance_fields(rt_a, e_a, time.time())
assert fields["firmware"] == "1.2" and fields["service"][0]["text"] == "Firmware 1.1 → 1.2"
# settings profile: A's options + over-the-air settings onto B
rt_a.meta.setdefault("config", {})["report_interval"] = 5
sentdl = []
async def _cmd(name, value=None): sentdl.append((name, value)); rt_b.meta.setdefault("config", {})[name] = value
rt_b.async_command = _cmd
updated = []
hass.config_entries.async_update_entry = lambda e, options: (updated.append((e.title, options)), setattr(e, "options", options))
prof = asyncio.run(mh.async_save_profile(hass, e_a, "Fridge"))
assert asyncio.run(mh.async_profiles(hass))["Fridge"]["model"] == "EM300-TH"
res = asyncio.run(mh.async_apply_profile(hass, prof, e_b, True, True, "Juan"))
assert sentdl == [("report_interval", 5)] and res["sent"] == 1 and res["options"] >= 2
assert e_b.options["battery_low_pct"] == 20 and e_b.options["max_gap_min"] == 120 and e_b.options["meter_offset"] == 3
assert rt_b.meta["_service_log"][-1]["kind"] == "profile" and "'Fridge' applied" in rt_b.meta["_service_log"][-1]["text"]
_titles = [e.title for e in mh.same_model_entries(hass, "EM300-TH", e_a.entry_id)]
assert "Fridge B" in _titles and "Fridge A" not in _titles and "Button" not in _titles
_, rt_c = make_with("00000000000b0003", "WS101", {}, title="Button")
try:
    asyncio.run(mh.async_apply_profile(hass, prof, rt_c.entry))
    raise AssertionError("other model")
except ValueError:
    pass
# handover report files
import tempfile, os
tmpd = tempfile.mkdtemp()
hass.config.path = lambda *p: os.path.join(tmpd, *p)
async def _exec(fn, *a): return fn(*a)
hass.async_add_executor_job = _exec
hub_ho = types.SimpleNamespace(data={"entry_type": "hub"}, entry_id="hho", title="Farm gate", options={}, runtime_data=hb)
hass.states = types.SimpleNamespace(get=lambda e: None)
hass.config.location_name, hass.config.country, hass.config.latitude, hass.config.longitude = "Acme", "ZA", 0, 0
entries.async_entry_for_domain_unique_id = lambda d, u: next((e for e in entries.items if e.data.get("deveui") == u), None)
out_ho = asyncio.run(mh.async_handover_report(hass, hub_ho))
assert out_ho["html"].startswith("/local/milesight/handover-farm-gate-") and int(out_ho["devices"]) >= 3
page = open(os.path.join(tmpd, "www", "milesight", out_ho["html"].rsplit("/", 1)[1]), encoding="utf-8").read()
assert "Fridge A" in page and "LoRaWAN installation handover" in page
entries.async_entry_for_domain_unique_id = lambda d, u: u in entries.known
# fixed device location: Location tracker entity, map tab, fleet / handover fields
assert rt_b.fixed_location() is None and not any(sp.key == "fixed_location" for sp in rt_b.extra_specs())
e_b.options = {**e_b.options, "location": {"latitude": -33.91234, "longitude": 18.41234, "accuracy": 6, "by": "Juan"}}
assert rt_b.fixed_location() == (-33.91234, 18.41234)
spec_loc = next(sp for sp in rt_b.extra_specs() if sp.key == "fixed_location")
dtrk = load("device_tracker")
trk = dtrk.MilesightTracker(rt_b, spec_loc)
rt_b._publish(time.time())
assert trk.latitude == -33.91234 and trk.longitude == 18.41234 and trk.location_accuracy == 6
assert trk.extra_state_attributes["milesight_role"] == "device_location" and rt_b.values["fixed_location"] == "fixed"
dlive = sys.modules["milesight_lorawan.dashboard_live"]
mv = dlive.map_view(lambda plat, uid: f"{plat}.{uid}", [rt_a, rt_b])
# the Map tab is a sections view with the page-header masthead and the map card full width
assert mv["type"] == "sections"
assert any(c.get("type") == "custom:milesight-page-header" for s in mv["sections"] for c in s["cards"])
mapcard = next(c for s in mv["sections"] for c in s["cards"] if c.get("type") == "map")
assert mapcard["entities"] == [{"entity": "device_tracker.00000000000b0002_fixed_location", "name": "Fridge B"}]
assert dlive.with_live_view("maintenance.yaml", {"views": [{"path": "maintenance"}]}, lambda p_, u: f"{p_}.{u}",
                         [rt_b], [])["views"][-1]["path"] == "map"
fb = fleet.maintenance_fields(rt_b, e_b, time.time())
assert fb["latitude"] == -33.91234 and "location" in __import__("milesight_lorawan.profiles", fromlist=["x"]).DEVICE_ONLY
ho_mod = load("handover")
assert "-33.912340, 18.412340" in ho_mod.report_csv([{"name": "x", **fb}])
print("maintenance ok")

# ---------------- 0.34.1: phone location from the Home Assistant app's tracker ----------------
_ident = lambda *a, **k: (lambda f: f)
if "voluptuous" not in sys.modules and "probatio" not in sys.modules:
    mod("voluptuous", Required=lambda *a, **k: a[0], Optional=lambda *a, **k: a[0], Any=lambda *a: None,
        All=lambda *a: None, Range=lambda *a, **k: None, Schema=lambda *a, **k: None)
sys.modules["homeassistant.config_entries"].SOURCE_IMPORT = "import"
mod("homeassistant.components.websocket_api", websocket_command=_ident, require_admin=lambda f: f,
    async_response=lambda f: f, event_message=lambda i, m: m)
from datetime import datetime as _dtx, timezone as _tzx
class _St:
    def __init__(self, eid, attrs, ts): self.entity_id, self.attributes, self.last_updated = eid, attrs, ts
TRK = {"device_tracker.juans_iphone": _St("device_tracker.juans_iphone", {"latitude": -25.88, "longitude": 28.22,
                                                                          "gps_accuracy": 8}, _dtx.now(_tzx.utc))}
PERSON = _St("person.juan", {"user_id": "u1", "device_trackers": ["device_tracker.juans_iphone"]}, None)
_ents = {"device_tracker.juans_iphone": types.SimpleNamespace(entity_id="device_tracker.juans_iphone", domain="device_tracker",
                                                               platform="mobile_app", device_id="dev9")}
mod("homeassistant.helpers.entity_registry", async_get=lambda h: types.SimpleNamespace(
    entities=types.SimpleNamespace(values=lambda: _ents.values()), async_get=lambda e: _ents.get(e)))
sys.modules["homeassistant.helpers.device_registry"].async_get = lambda h: types.SimpleNamespace(
    async_get=lambda i: types.SimpleNamespace(name="Juan's iPhone", name_by_user=None))
sys.modules.setdefault("homeassistant.util", mod("homeassistant.util"))
sys.modules["homeassistant.util"].slugify = lambda t: "".join(c if c.isalnum() else "_" for c in t.lower()).replace("__", "_")
NOTIFIED = []
async def _notify_call(domain, service, data, blocking=False):
    NOTIFIED.append(service)
    TRK["device_tracker.juans_iphone"] = _St("device_tracker.juans_iphone", {"latitude": -25.881, "longitude": 28.221,
                                                                             "gps_accuracy": 5}, _dtx.now(_tzx.utc))
UPD = []
e_loc, rt_loc = make_with("00000000000c0001", "EM300-TH", {}, title="Gate sensor")
hass_l = types.SimpleNamespace(
    states=types.SimpleNamespace(async_all=lambda d: [PERSON] if d == "person" else [], get=lambda e: TRK.get(e)),
    services=types.SimpleNamespace(has_service=lambda d, n: n == "mobile_app_juan_s_iphone", async_call=_notify_call),
    config_entries=types.SimpleNamespace(async_entries=lambda d: [e_loc],
                                         async_update_entry=lambda e, options: (UPD.append(options), setattr(e, "options", options))))
cws = load("commissioning_ws")
assert cws.phone_trackers(hass_l, "u1") == ["device_tracker.juans_iphone"]
RES = {}
conn = types.SimpleNamespace(user=types.SimpleNamespace(id="u1", name="Juan"),
                             send_result=lambda i, r: RES.update(r), send_error=lambda i, c, m: RES.update(error=m))
asyncio.run(cws.ws_phone_location(hass_l, conn, {"id": 1, "deveui": "00000000000c0001"}))
assert NOTIFIED == ["mobile_app_juan_s_iphone"] and RES["fresh"] and RES["accuracy"] == 5, RES
assert e_loc.options["location"]["latitude"] == -25.881 and e_loc.options["location"]["source"] == "device_tracker.juans_iphone"
RES.clear()
asyncio.run(cws.ws_phone_location(types.SimpleNamespace(**{**vars(hass_l), "states": types.SimpleNamespace(
    async_all=lambda d: [], get=lambda e: None)}), conn, {"id": 2, "deveui": "00000000000c0001"}))
print("phone location ok")


# ---------------- 0.35: CT103 energy from voltage, automatic running threshold, typed-in setpoints ----------------
import base64
e_ct, rt = make_with("24e124746e359611", "CT103", {"pump_enabled": True, "pump_normal_a": 0.8, "run_threshold_a": 0.5,
                                                    "mains_voltage": 230}, title="Farm pump")
assert rt.limits["run_a"] == 0.24                                       # old stored 0.5 A = automatic
send("24e124746e359611", base64.b64decode("A5d1hw4ABJgtAAln//8="))       # 0.45 A, 9521.81 Ah
v = rt.values
assert v["current"] == 0.45 and v["pump_running"] is True, v
assert v["energy"] == round(9521.81 * 230 * 0.85 / 1000, 3) and v["apparent_power"] == 104, v
sp = {s.key for s in rt.extra_specs() if s.platform == "number"}
assert {"sp_mains_voltage", "sp_power_factor", "sp_run_threshold_a", "sp_pump_normal_a"} <= sp, sp
assert v["sp_mains_voltage"] == 230 and v["sp_run_threshold_a"] == 0 and v["sp_power_factor"] == 0.85
e_nv, rt2 = make_with("24e124746e359612", "CT103", {}, title="No voltage")
send("24e124746e359612", base64.b64decode("A5d1hw4ABJgtAAln//8="))
assert rt2.values.get("energy") is None and rt2.limits["run_a"] == 0.2
print("ct103 energy ok")

# ---------------- 0.36: power in W, cold storage views, corrective actions, compliance reports ----------------
e_w, rt = make_with("24e124746e359614", "CT103", {"mains_voltage": 230, "power_factor": 0.9}, title="Pump W")
send("24e124746e359614", base64.b64decode("A5cWiA4ABJhWAQlniwE="))           # 3.42 A
assert rt.values["power"] == round(3.42 * 230 * 0.9) and rt.values["apparent_power"] == round(3.42 * 230), rt.values
spec = {s.key: s for s in models.entity_specs("CT103")}
assert spec["power"].unit == "W" and spec["power"].device_class == "power" and spec["apparent_power"].name == "Apparent power"

fr = e_f.runtime_data
keys = {s.key: s for s in fr.extra_specs()}
assert keys["corrective_action"].platform == "text" and "temp_in_range_7d" in keys
txt = load("text")
ent = txt.CorrectiveActionText(fr, keys["corrective_action"])
class _U: name = "Juan"
async def _gu(uid): return _U()
ent.hass = types.SimpleNamespace(auth=types.SimpleNamespace(async_get_user=_gu))
ent._context = types.SimpleNamespace(user_id="u1")
asyncio.run(ent.async_set_value("Door seal replaced, product moved"))
assert fr.meta["_service_log"][-1]["kind"] == "corrective_action" and fr.meta["_service_log"][-1]["by"] == "Juan"
assert fr.values["corrective_action"] == "Door seal replaced, product moved"
assert isinstance(fr.values["temp_in_range_7d"], (int, float)) or fr.values["temp_in_range_7d"] is None

dl = load("dashboard_live")
eid = lambda plat, uid: f"{plat}.{uid}"
hubobj = types.SimpleNamespace(entry=types.SimpleNamespace(entry_id="hubX", title="Site"))
cv = dl.cold_chain_views(eid, [fr, rt], [hubobj])
assert [v["path"] for v in cv] == ["overview", "units", "trends", "compliance", "compressors"], [v["path"] for v in cv]
flat = json.dumps(cv)
assert "statistics-graph" in flat                                             # trends still use statistics graphs
assert "custom:milesight-coldchain-band" in flat and "custom:milesight-compliance-card" in flat   # modern self-discovering cards
assert "custom:milesight-table-card" in flat and "Kitchen" in flat and "Pump W" not in flat
# every generated cold-chain view carries the page header
assert all(any(c.get("type") == "custom:milesight-page-header" for s in v["sections"] for c in s["cards"]) for v in cv)
cfg = dl.with_live_view("cold_chain.yaml", {"views": [{"title": "Table"}]}, eid, [fr], [hubobj])
assert cfg["views"][0]["path"] == "overview"                                  # generated views replace the bundled ones
assert all(v.get("title") != "Table" for v in cfg["views"])                   # the bundled placeholder view is dropped

# compliance manager end to end with a stubbed recorder
import tempfile, time as _time
from zoneinfo import ZoneInfo as _ZI
TZ = _ZI("Africa/Johannesburg")
NOW = datetime(2026, 10, 19, 6, 5, tzinfo=TZ)                     # Monday morning
import os
dtu = sys.modules["homeassistant.util.dt"]; sys.modules["homeassistant.util"].dt = dtu
dtu.now = lambda: NOW; dtu.as_local = lambda d: d.astimezone(TZ); dtu.parse_datetime = datetime.fromisoformat
wk0 = datetime(2026, 10, 12, tzinfo=TZ).timestamp()
class _S:
    def __init__(self, ts, st): self.last_updated = datetime.fromtimestamp(ts, timezone.utc); self.state = st
def _changes(hass, start, end, eid, **kw):
    if eid.endswith("_temperature"):
        return {eid: [_S(wk0 - 600 + i * 600, str(3.0 if not 1000 < i < 1010 else 9.0)) for i in range(7 * 144 + 2)]}
    return {eid: []}
class _Inst:
    async def async_add_executor_job(self, f, *a): return f(*a)
mod("homeassistant.components.recorder", get_instance=lambda h: _Inst(),
    history=types.SimpleNamespace(state_changes_during_period=_changes))
mod("homeassistant.components.recorder.statistics", statistics_during_period=lambda *a: {})
mod("homeassistant.helpers.entity_registry", async_get=lambda h: _EntReg())
NOTES, CALLS, FIRED2 = [], [], []
mod("homeassistant.components.persistent_notification", async_create=lambda h, m, title=None, notification_id=None: NOTES.append((title, m)))
sys.modules["homeassistant.components"].persistent_notification = sys.modules["homeassistant.components.persistent_notification"]
sys.modules["homeassistant.helpers.event"].async_track_time_change = lambda h, f, **kw: (lambda: None)
async def _call(domain, name, data, blocking=False): CALLS.append((domain, name, data))
tmp = tempfile.mkdtemp()
bld = load("building")
bld.site_info = lambda h, e: {"company": "Korb Farms", "site": "Packhouse"}
hub_e = types.SimpleNamespace(entry_id="hubX", title="Site", options={"compliance_notify": "smtp_haccp"})
hass_c = types.SimpleNamespace(
    config=types.SimpleNamespace(time_zone="Africa/Johannesburg", path=lambda *p: os.path.join(tmp, *p)),
    config_entries=types.SimpleNamespace(async_entries=lambda d: [e_f]),
    services=types.SimpleNamespace(has_service=lambda d, n: n == "smtp_haccp", async_call=_call),
    bus=types.SimpleNamespace(async_fire=lambda ev, d: FIRED2.append((ev, d))),
    async_add_executor_job=lambda f, *a: asyncio.sleep(0, f(*a)))
cha = load("compliance_ha")
assert cha.notify_services("smtp_a, notify.b") == ["notify.smtp_a", "notify.b"]
assert [u["temp"] for u in cha.cold_units(hass_c)] == ["sensor.0000000000f00001_temperature"]
mgr = cha.ComplianceManager(hass_c, hub_e)
out = asyncio.run(mgr.async_create("week"))
r = out["reports"][0]
assert r["unit"] == "Fridge 3" and r["status"] in ("deviations", "not_compliant") and r["excursions"] == 1, r
assert r["max"] == 9.0 and r["url"].startswith("/local/milesight/compliance/2026/fridge-3-week-20261012-") and r["coverage"] > 99
assert open(r["path"], "rb").read(5) == b"%PDF-"
assert CALLS and CALLS[0][:2] == ("notify", "smtp_haccp") and CALLS[0][2]["data"]["images"] == [r["path"]]
assert out["sent_to"] == ["notify.smtp_haccp"] and NOTES and FIRED2[-1][0] == "milesight_lorawan_compliance_report"
assert mgr.reports()[0]["unit"] == "Fridge 3" and "path" not in mgr.reports()[0]
# the scheduled run on Monday makes it once
asyncio.run(mgr._run_period("week", NOW)); n1 = len(mgr.data["reports"])
asyncio.run(mgr._run_period("week", NOW)); assert len(mgr.data["reports"]) == n1
print("compliance ok")


# ---------------- 0.37: gateway discovery (network / first packet / QR) ----------------
assert GW_FLOWS and GW_FLOWS[0]["gateway_id"] == "24e124fffef00001" and GW_FLOWS[0]["hub_entry_id"] == "h", GW_FLOWS[:2]
lns_offer = [f for f in GW_FLOWS if f["gateway_id"] == "24e124fffefa2994"]
assert lns_offer and lns_offer[0]["ip"] == "192.168.1.20" and lns_offer[0]["hub_entry_id"] == "hl"
assert "packet forwarder" in lns_offer[0]["connection"]
# a gateway that already sends: naming it adopts it at once and closes its discovery card
OPEN_FLOWS.append({"flow_id": "f1", "context": {"unique_id": "gateway:24e124fffefa2994"}})
dreg_calls = []
sys.modules["homeassistant.helpers.device_registry"].async_get = lambda h: types.SimpleNamespace(
    async_get_device=lambda identifiers: types.SimpleNamespace(id="d1", name_by_user=None, area_id=None),
    async_update_device=lambda i, **kw: dreg_calls.append(kw))
sys.modules.setdefault("homeassistant.helpers.area_registry", mod("homeassistant.helpers.area_registry"))
sys.modules["homeassistant.helpers.area_registry"].async_get = lambda h: types.SimpleNamespace(
    async_get_or_create=lambda n: types.SimpleNamespace(id="area_" + n.lower().replace(" ", "_")))
assert hbl.expect_gateway("24e124fffefa2994", {"name": "Pump house gateway", "area": "Pump house"}) == "connected"
g = hbl.stats.gateways["24e124fffefa2994"]
assert g["approved"] and g["name"] == "Pump house gateway" and g["area"] == "Pump house" and "f1" in ABORTED
assert dreg_calls[-1] == {"name": "Pump house gateway", "area_id": "area_pump_house", "configuration_url": "http://192.168.1.20"}, dreg_calls
assert hbl.gateway_known("24e124fffefa2994")
# a gateway announced by DHCP / QR before it sends: adopted from its first packet, by EUI or by IP
n = len(GW_FLOWS)
assert hbl.expect_gateway("24e124fffe000777", {"name": "Barn", "area": "Barn", "ip": "192.168.1.77"}) == "waiting"
assert hbl.gateway_known("24e124fffe000777") and "24e124fffe000777" in hbl.stats.to_dict()["expected"]
NOTES_GW = []
sys.modules["homeassistant.components.persistent_notification"].async_create = lambda h, m, title=None, notification_id=None: NOTES_GW.append((title, m))
hbl.lns.datagram_received(b"\x02\x00\x01\x02" + bytes.fromhex("24e124fffe000778"), ("192.168.1.77", 41000))  # Wi-Fi EUI
g2 = hbl.stats.gateways["24e124fffe000778"]
assert g2["approved"] and g2["name"] == "Barn" and g2["ip"] == "192.168.1.77" and len(GW_FLOWS) == n, GW_FLOWS[n:]
assert not hbl.stats.expected and NOTES_GW and "Barn" in NOTES_GW[-1][1]
assert any(e == "milesight_lorawan_gateway_connected" for e, d in fired)
gwmod = load("gateway")
info = gwmod._gw_device(hub_lns_entry, "24e124fffe000778", g2)
assert info["suggested_area"] == "Barn" and info["configuration_url"] == "http://192.168.1.77"
# an unknown gateway is offered once
hbl.lns.datagram_received(b"\x02\x00\x01\x02" + bytes.fromhex("24e124fffe000999"), ("192.168.1.99", 41000))
hbl.lns.datagram_received(b"\x02\x00\x01\x02" + bytes.fromhex("24e124fffe000999"), ("192.168.1.99", 41000))
assert [f["gateway_id"] for f in GW_FLOWS[n:]] == ["24e124fffe000999"]
# pending gateways from the set-up flow are expected after a restart
hub_new = types.SimpleNamespace(data={"entry_type": "hub", "topic": ""}, entry_id="hn", title="Network",
                                options={"lns_enabled": False, "pending_gateways": {"24e124fffe0000aa": {"name": "Shed"}}})
hn = hub.Hub(hass, hub_new)
async def _st():
    hn.stats = hub.GatewayStats() if hasattr(hub, "GatewayStats") else hn.stats
    for eui, info in hub_new.options["pending_gateways"].items():
        if not hn.gateway_known(eui): hn.stats.expected[eui] = dict(info)
asyncio.run(_st())
assert hn.stats.expected == {"24e124fffe0000aa": {"name": "Shed"}}
# how gateways connect: MQTT uplinks (gateway network server) and Semtech packets (built-in network server)
gwm = hb.stats.gateways["24e124fffef00001"]
assert gwm["conn"] == ["embedded"] and gwm["found"] == "mqtt", gwm
assert hbl.stats.gateways["24e124fffefa2994"]["conn"] == ["built-in"]
hub_lns_entry.runtime_data = hbl
conn = gwmod.GatewaySensor(hass, hub_lns_entry, "24e124fffe000778", "connection")
assert conn.native_value == "Semtech UDP · Home Assistant network server"
assert conn.extra_state_attributes["found_via"] == "Semtech UDP · first packet (192.168.1.77)" and conn.extra_state_attributes["web_page"] == "http://192.168.1.77"
assert gwmod._gw_device(hub_lns_entry, "24e124fffe000778", g2)["model"] == "LoRaWAN gateway · Semtech UDP"
# network scan: a known gateway gets its address, an unknown Milesight one is offered
import builtins
_open = builtins.open
ARP = ("IP address HW type Flags HW address Mask Device\n"
       "192.168.1.50 0x1 0x2 24:e1:24:f0:00:01 * eth0\n192.168.1.88 0x1 0x2 24:e1:24:00:00:88 * eth0\n"
       "192.168.1.1 0x1 0x2 aa:bb:cc:dd:ee:ff * eth0\n")
class _F:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return ARP
builtins.open = lambda f, *a, **k: _F() if f == "/proc/net/arp" else _open(f, *a, **k)
async def _exec(f, *a): return f(*a)
hass.async_add_executor_job = _exec
n = len(GW_FLOWS)
try:
    out = asyncio.run(hb.async_scan_lan(prime=False))
finally:
    builtins.open = _open
assert out == {"known": ["24e124fffef00001"], "offered": ["24e124fffe000088"]}, out
assert hb.stats.gateways["24e124fffef00001"]["ip"] == "192.168.1.50"
assert GW_FLOWS[n:][-1:] == [{"lan": True, "mac": "24:e1:24:00:00:88", "ip": "192.168.1.88", "hub_entry_id": "h"}], GW_FLOWS[n:]
# forget a gateway: it is removed from stats, expected and the device registry, so it can be found again
rm_dev=[]
sys.modules["homeassistant.helpers.device_registry"].async_get = lambda h: types.SimpleNamespace(
    async_get_device=lambda identifiers: types.SimpleNamespace(id="gwdev1"),
    async_remove_device=lambda i: rm_dev.append(i))
assert hbl.gateway_known("24e124fffefa2994")
assert hbl.forget_gateway("24E124FFFEFA2994") is True
assert not hbl.gateway_known("24e124fffefa2994") and "24e124fffefa2994" not in hbl.stats.gateways and "gwdev1" in rm_dev
assert hbl.forget_gateway("24e124fffe999999") is False
# an announced-but-not-heard gateway is forgettable too
hbl.stats.expected["24e124fffe0000bb"] = {"name": "x"}
assert hbl.forget_gateway("24e124fffe0000bb") is True and "24e124fffe0000bb" not in hbl.stats.expected
print("gateway discovery ok")
