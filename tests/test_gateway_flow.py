"""Config-flow test for gateway discovery (network / first packet), with a minimal Home Assistant stub.

Run: python tests/test_gateway_flow.py"""
import asyncio
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))


def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class _Key(str):
    def __new__(cls, k, default=None, description=None):
        o = str.__new__(cls, k)
        o.default, o.description = default, description
        return o


class _Schema:
    def __init__(self, d):
        self.schema = d


mod("voluptuous", Required=_Key, Optional=_Key, Schema=_Schema, In=lambda *a: None, Any=lambda *a: None,
    All=lambda *a: None, Range=lambda **k: None, Invalid=Exception, Coerce=lambda t: t)
mod("homeassistant")
mod("homeassistant.core", HomeAssistant=object, callback=lambda f: f)


class ConfigFlow:
    def __init_subclass__(cls, **kw):
        pass

    def __init__(self):
        self.context = {}
        self._uid = None

    async def async_set_unique_id(self, uid):
        self._uid = uid

    def _abort_if_unique_id_configured(self):
        if any(e.unique_id == self._uid for e in self.hass.config_entries.items):
            raise _Abort("already_configured")

    def _async_current_entries(self):
        return list(self.hass.config_entries.items)

    def async_show_form(self, step_id, data_schema=None, errors=None, description_placeholders=None):
        return {"type": "form", "step_id": step_id, "schema": data_schema, "errors": errors or {}, "placeholders": description_placeholders}

    def async_create_entry(self, title, data, options=None):
        return {"type": "create_entry", "title": title, "data": data, "options": options}

    def async_abort(self, reason, description_placeholders=None):
        return {"type": "abort", "reason": reason, "placeholders": description_placeholders}

    def async_show_menu(self, **kw):
        return {"type": "menu", **kw}


class _Abort(Exception):
    pass


mod("homeassistant.config_entries", SOURCE_IMPORT="import", ConfigEntry=object, ConfigFlow=ConfigFlow,
    ConfigFlowResult=dict, OptionsFlow=object, SOURCE_INTEGRATION_DISCOVERY="integration_discovery")
_sel = {n: (lambda *a, **k: None) for n in (
    "AreaSelector AreaSelectorConfig BooleanSelector EntitySelector EntitySelectorConfig LocationSelector "
    "LocationSelectorConfig NumberSelector NumberSelectorConfig SelectOptionDict SelectSelector "
    "SelectSelectorConfig TextSelector TextSelectorConfig DateTimeSelector TimeSelector ObjectSelector").split()}
_sel["NumberSelectorMode"] = types.SimpleNamespace(BOX="box", SLIDER="slider")
_sel["SelectSelectorMode"] = types.SimpleNamespace(LIST="list", DROPDOWN="dropdown")
_sel["TextSelectorType"] = types.SimpleNamespace(PASSWORD="password", TEL="tel", EMAIL="email", URL="url")
mod("homeassistant.helpers")
mod("homeassistant.helpers.selector", **_sel)
mod("homeassistant.helpers.config_validation", string=str, boolean=bool)


async def _src_ip(hass, target_ip=None):
    return "192.168.1.20"
mod("homeassistant.components")
mod("homeassistant.components.network", async_get_source_ip=_src_ip)
mod("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda h: None)

CALLS = []
class FakeClient:
    def __init__(self, session, host, user, pw, **kw): CALLS.append(("init", host, user, pw))
    async def login(self):
        if self.bad: raise _GwErr("wrong gateway username or password")
    async def async_read_info(self): return {"model": "UG65", "eui": "24e124fffefa2994"}
    async def async_point_at_home_assistant(self, ip, band="EU868", port=1700): CALLS.append(("semtech", ip, band)); return True
    async def async_setup_mqtt(self, ip, u, pw, prefix="milesight", app_name="Home Assistant"):
        CALLS.append(("mqtt", ip, u)); return {"topic": "milesight/uplink/#", "downlink_topic": "milesight/downlink/{deveui}",
            "extra_topics": "milesight/ack, milesight/join, milesight/gateway", "ns_request_topic": "milesight/request",
            "ns_response_topic": "milesight/response"}
FakeClient.bad = False
class _GwErr(Exception): pass

import importlib  # noqa: E402
import types as _t
_ga = _t.ModuleType("milesight_lorawan.gateway_api"); _ga.GatewayClient = FakeClient; _ga.GatewayError = _GwErr
import sys as _sys
_pkg = types.ModuleType("milesight_lorawan")
_pkg.__path__ = [str(ROOT / "custom_components" / "milesight_lorawan")]
sys.modules["milesight_lorawan"] = _pkg                 # skip the package __init__ (needs all of HA)
sys.modules["milesight_lorawan.gateway_api"] = _ga
cf = importlib.import_module("milesight_lorawan.config_flow")


class Entries:
    def __init__(self):
        self.items, self.updated, self.reloaded, self.mqtt = [], [], [], []
    def async_entries(self, domain=None):
        if domain == "mqtt": return self.mqtt
        return list(self.items)

    def async_update_entry(self, e, options):
        e.options = options
        self.updated.append(options)

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


def make_flow(entries):
    f = cf.MilesightConfigFlow()
    f.context, f._uid = {}, None
    f.hass = types.SimpleNamespace(config_entries=entries, async_create_task=lambda c: c.close())
    return f


def run(coro):
    try:
        return asyncio.run(coro)
    except _Abort as a:
        return {"type": "abort", "reason": str(a)}


dhcp = types.SimpleNamespace(ip="192.168.1.50", macaddress="24e124fa2994", hostname="ug65")

# 1. a brand-new installation: the gateway sets up the network (built-in network server, no MQTT)
ents = Entries()
fl = make_flow(ents)
r = run(fl.async_step_dhcp(dhcp))
assert r["type"] == "form" and r["step_id"] == "gateway_found", r
assert r["placeholders"]["ha_ip"] == "192.168.1.20" and r["placeholders"]["eui"] == "24E124FFFEFA2994"
assert fl._uid == "gateway:24e124fffefa2994" and fl.context["title_placeholders"]["deveui"] == "LAN · 192.168.1.50"
assert r["placeholders"]["found"] == "LAN · DHCP"
assert "use_lns" not in r["schema"].schema
r = run(fl.async_step_gateway_found({"name": "Pump house", "area": "Farm"}))
assert r["type"] == "create_entry" and r["data"]["entry_type"] == "hub" and r["data"]["topic"] == ""
assert r["options"]["lns_enabled"] is True and r["options"]["lns_port"] == 1700
pend = r["options"]["pending_gateways"]["24e124fffefa2994"]
assert pend["name"] == "Pump house" and pend["area"] == "Farm" and pend["ip"] == "192.168.1.50"
assert pend["found"] == "lan_dhcp"

# 2. not a Milesight MAC
assert run(make_flow(ents).async_step_dhcp(types.SimpleNamespace(ip="1.2.3.4", macaddress="aabbccddeeff",
                                                                 hostname=None)))["reason"] == "not_milesight_gateway"


# 3. an existing MQTT site: offer to switch the built-in network server on; adopted after the reload
class Hub:
    def __init__(self):
        self.stats = types.SimpleNamespace(gateways={}, expected={})
        self.expected = []

    def gateway_known(self, eui):
        return eui in self.stats.expected

    def expect_gateway(self, eui, info):
        self.stats.expected[eui] = info
        return "waiting"


h = Hub()
mqtt_hub = types.SimpleNamespace(entry_id="h1", unique_id="hub:x/#", options={}, runtime_data=h,
                                 data={"entry_type": "hub", "topic": "x/#"})
ents = Entries()
ents.items.append(mqtt_hub)
fl = make_flow(ents)
r = run(fl.async_step_dhcp(dhcp))
assert r["step_id"] == "gateway_found" and "use_lns" in r["schema"].schema
r = run(fl.async_step_gateway_found({"name": "Barn", "use_lns": True}))
assert r["type"] == "abort" and r["reason"] == "gateway_waiting" and r["placeholders"]["port"] == "1700"
assert mqtt_hub.options["lns_enabled"] is True and "24e124fffefa2994" in mqtt_hub.options["pending_gateways"]
# keep MQTT: the gateway is only expected (adopted from the first uplink it forwards)
mqtt_hub.options = {}
fl = make_flow(ents)
run(fl.async_step_dhcp(dhcp))
r = run(fl.async_step_gateway_found({"name": "Barn", "use_lns": False}))
assert r["reason"] == "gateway_waiting" and h.stats.expected["24e124fffefa2994"]["name"] == "Barn"
assert "lns_enabled" not in mqtt_hub.options
# found again on the network: nothing to do
assert run(make_flow(ents).async_step_dhcp(dhcp))["reason"] == "already_configured"

# 4. the first packet of an unknown gateway
fl = make_flow(ents)
r = run(fl.async_step_integration_discovery({"gateway_id": "24e124fffe000999", "hub_entry_id": "h1",
                                             "ip": "192.168.1.99", "connection": "packet forwarder (Semtech UDP)"}))
assert r["step_id"] == "gateway_heard" and r["placeholders"]["gw_ip"] == "192.168.1.99"
r = run(fl.async_step_gateway_heard({"name": "Hill", "area": "North"}))
assert r["reason"] == "gateway_waiting" and h.stats.expected["24e124fffe000999"]["area"] == "North"
assert run(make_flow(ents).async_step_integration_discovery({"gateway_id": "24e124fffe000999"}))["reason"] == \
    "already_configured"
# 5. the network scan found one; and a gateway already sending is not offered again, its address is noted
fl = make_flow(ents)
r = run(fl.async_step_integration_discovery({"lan": True, "mac": "24:e1:24:00:00:88", "ip": "192.168.1.88",
                                             "hub_entry_id": "h1"}))
assert r["step_id"] == "gateway_found" and r["placeholders"]["found"] == "LAN · network scan"
h.stats.gateways["24e124fffe000042"] = {"name": "UG65_2"}
r = run(make_flow(ents).async_step_dhcp(types.SimpleNamespace(ip="192.168.1.42", macaddress="24e124000042",
                                                              hostname=None)))
assert r["reason"] == "already_configured" and h.stats.gateways["24e124fffe000042"]["ip"] == "192.168.1.42"
# first packet over Semtech: the card says so
r = run(make_flow(ents).async_step_integration_discovery({"gateway_id": "24e124fffe000555", "ip": "10.0.0.5",
                                                           "connection": "packet forwarder (Semtech UDP)"}))
assert r["placeholders"]["found"] == "Semtech UDP · first packet"
# 6. auto-configure a new gateway (no hub yet): Semtech mode sets up the built-in network server
ents = Entries()
fl = make_flow(ents)
run(fl.async_step_dhcp(dhcp))
r = run(fl.async_step_gateway_found({"name": "Depot", "auto_configure": True}))
assert r["step_id"] == "gateway_configure" and r["placeholders"]["ha_ip"] == "192.168.1.20"
CALLS.clear()
r = run(fl.async_step_gateway_configure({"username": "admin", "password": "pw", "mode": "lns", "band": "EU868"}))
assert ("semtech", "192.168.1.20", "EU868") in CALLS and r["type"] == "create_entry"
assert r["options"]["lns_enabled"] is True and "24e124fffefa2994" in r["options"]["pending_gateways"]
# MQTT mode on a fresh install: a second step collects the broker login (prefilled from HA's MQTT), then creates the hub
ents = Entries()
ents.mqtt.append(types.SimpleNamespace(data={"broker": "192.168.1.5", "port": 1883, "username": "hamqtt",
                                             "password": "secret"}, options={}))
fl = make_flow(ents); run(fl.async_step_dhcp(dhcp))
run(fl.async_step_gateway_found({"name": "Depot", "auto_configure": True}))
CALLS.clear()
r = run(fl.async_step_gateway_configure({"username": "admin", "password": "pw", "mode": "mqtt"}))
assert r["step_id"] == "gateway_mqtt" and r["placeholders"]["broker"] == "192.168.1.5" and r["placeholders"]["user"] == "hamqtt"
r = run(fl.async_step_gateway_mqtt({}))     # accept the prefilled HA credentials
assert ("mqtt", "192.168.1.5", "hamqtt") in CALLS and r["type"] == "create_entry"
assert r["data"]["topic"] == "milesight/uplink/#" and r["data"]["ns_request_topic"] == "milesight/request"
assert r["data"].get("lns_enabled") is None
# wrong password -> error on the same step, nothing created
ents = Entries(); fl = make_flow(ents); run(fl.async_step_dhcp(dhcp))
run(fl.async_step_gateway_found({"name": "Depot", "auto_configure": True}))
FakeClient.bad = True
r = run(fl.async_step_gateway_configure({"username": "admin", "password": "bad", "mode": "lns"}))
assert r["type"] == "form" and r["errors"]["base"] == "gateway_login"
FakeClient.bad = False
# 7. reconfigure a known gateway (the device-page button): no new entry, just configures it
h.stats.gateways["24e124fffef61e38"] = {"name": "UG65", "ip": "192.168.1.230", "found": "mqtt"}
fl = make_flow(ents)
r = run(fl.async_step_gateway_reconfigure({"gateway_id": "24E124FFFEF61E38", "ip": "192.168.1.230", "hub_entry_id": "h1"}))
assert r["step_id"] == "gateway_configure" and r["placeholders"]["gw_ip"] == "192.168.1.230"
CALLS.clear()
r = run(fl.async_step_gateway_configure({"username": "admin", "password": "pw", "mode": "both"}))
assert r["step_id"] == "gateway_mqtt"
r = run(fl.async_step_gateway_mqtt({"mqtt_user": "u", "mqtt_password": "p"}))
assert ("init", "192.168.1.230", "admin", "pw") in CALLS and ("semtech", "192.168.1.20", "EU868") in CALLS
assert ("mqtt", "192.168.1.20", "u") in CALLS
assert r["type"] == "abort" and r["reason"] == "gateway_configured"
# a known gateway without a stored IP: the form asks for the host
h.stats.gateways["24e124fffe00aa00"] = {"name": "UG67"}
fl = make_flow(ents)
r = run(fl.async_step_gateway_reconfigure({"gateway_id": "24e124fffe00aa00", "hub_entry_id": "h1"}))
assert "host" in r["schema"].schema
CALLS.clear()
r = run(fl.async_step_gateway_configure({"host": "192.168.1.99", "username": "admin", "password": "pw", "mode": "lns"}))
assert ("init", "192.168.1.99", "admin", "pw") in CALLS and r["reason"] == "gateway_configured"
print("gateway flow ok")
