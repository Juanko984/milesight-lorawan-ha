"""Exercise hub -> runtime -> entities with a minimal Home Assistant stub.

This checks the integration's own wiring and value mapping for every model.
It does NOT replace a test inside a real Home Assistant instance.
"""
import asyncio, base64, json, pathlib, sys, time, types, enum
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
SensorDeviceClass = StrE("SDC", {k.upper(): k for k in ["temperature","humidity","battery","signal_strength","timestamp","duration","carbon_dioxide","volatile_organic_compounds","atmospheric_pressure","pm25","pm10","illuminance","pressure","distance","moisture","conductivity"]})
SensorStateClass = StrE("SSC", {k.upper(): k for k in ["measurement","total_increasing"]})
BinarySensorDeviceClass = StrE("BDC", {k.upper(): k for k in ["door","moisture","occupancy","problem","motion","safety","connectivity","battery"]})
EntityCategory = StrE("EC", {"DIAGNOSTIC": "diagnostic"})
callback = lambda f: f

class Entity:
    def async_on_remove(self, f): pass
    def async_write_ha_state(self): self.writes = getattr(self, "writes", 0) + 1


from datetime import datetime, timezone
dt_mod = types.SimpleNamespace(get_time_zone=lambda z: ZoneInfo(z), UTC=timezone.utc,
                               utc_from_timestamp=lambda ts: datetime.fromtimestamp(ts, timezone.utc))

mod("homeassistant"); mod("homeassistant.components")
mod("homeassistant.components.mqtt", ReceiveMessage=object, async_subscribe=None, async_wait_for_mqtt_client=None)
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
mod("homeassistant.components.binary_sensor", BinarySensorDeviceClass=BinarySensorDeviceClass, BinarySensorEntity=object)
mod("homeassistant.const", Platform=types.SimpleNamespace(SENSOR="sensor", BINARY_SENSOR="binary_sensor"))
mod("homeassistant.exceptions", ConfigEntryNotReady=Exception)

# Load modules directly (skip package __init__)
import importlib.util
PKG = ROOT / "milesight_lorawan"
pkg = types.ModuleType("milesight_lorawan"); pkg.__path__ = [str(PKG)]; sys.modules["milesight_lorawan"] = pkg
def load(n):
    spec = importlib.util.spec_from_file_location(f"milesight_lorawan.{n}", PKG / f"{n}.py")
    m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m); return m
for n in ["const", "decoders", "analytics", "models", "hub", "runtime", "entity", "sensor", "binary_sensor"]:
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
        cls = sensor.MilesightSensor if s.platform == "sensor" else binary_sensor.MilesightBinarySensor
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
