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
SensorDeviceClass = StrE("SDC", {k.upper(): k for k in ["temperature","humidity","battery","signal_strength","timestamp","duration"]})
SensorStateClass = StrE("SSC", {k.upper(): k for k in ["measurement","total_increasing"]})
BinarySensorDeviceClass = StrE("BDC", {k.upper(): k for k in ["door","moisture","occupancy","problem"]})
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
hass = types.SimpleNamespace(config=types.SimpleNamespace(time_zone="Africa/Johannesburg"),
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
    "EM300-SLD": bytes([0x03, 0x67, 0x10, 0x01, 0x06, 0x00, 0x01]),
    "EM300-ZLD": bytes([0x06, 0x00, 0x00]),
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
st = states(make_device("0000000000000000", "VS121")[1])
assert st["occ_occupied"] is True and st["people_count_all"] == 2 and "2 people" in st["occ_status"]
print("all models ok")
