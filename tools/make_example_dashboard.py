#!/usr/bin/env python3
"""Regenerate dashboards/building_overview.example.yaml with the entity ids Home Assistant gives a gateway
added with the default uplink topic: the entry is called "Milesight gateway (milesight/uplink/#)", so its
entities are sensor.milesight_gateway_milesight_uplink_<name>."""
import importlib.util, pathlib, yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dc", ROOT / "custom_components/milesight_lorawan/dashboard_config.py")
dc = importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)

G = "sensor.milesight_gateway_milesight_uplink_"
AREAS = [("Reception", "mdi:door"), ("Open office", "mdi:desk"), ("Meeting room 1", "mdi:account-group")]


def slug(t):
    return "".join(c if c.isalnum() else "_" for c in t.lower())


ctx = {
    "title": "Building – Milesight gateway (milesight/uplink/#)", "site": G + "site",
    "health": G + "building_health", "comfort": G + "building_comfort", "air_quality": G + "air_quality",
    "systems": G + "systems_health", "people": G + "people_in_building", "alerts": G + "alerts",
    "avg": {k: G + "average_" + n for k, n in (("co2", "co2"), ("pm2_5", "pm2_5"), ("tvoc", "tvoc"),
                                               ("humidity", "humidity"), ("temperature", "temperature"),
                                               ("pm10", "pm10"), ("pressure", "pressure"))},
    "devices_online": G + "devices_online", "battery_low": G + "devices_with_low_battery",
    "gateways_online": G + "gateways_online", "uplinks": G + "uplinks_today",
    "outside": "sensor.outside_temperature", "co2_alert": 1200,
    "areas": [{"name": n, "icon": i, "comfort": f"{G}{slug(n)}_comfort", "occupancy": f"{G}{slug(n)}_occupancy",
               "co2": f"sensor.{slug(n)}_am307_co2"} for n, i in AREAS],
}


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s,
                                                            style="|" if "\n" in s else None))
HEADER = """# Milesight LoRaWAN – Building dashboard (example of what the gateway's 'Update building dashboard' button creates)
# You normally don't need this file: the button builds the dashboard with YOUR entity ids and areas.
# Entity ids below are the defaults for a gateway added with the topic milesight/uplink/#
# (gateway entry "Milesight gateway (milesight/uplink/#)" -> sensor.milesight_gateway_milesight_uplink_...).
# Another topic or a renamed gateway gives other ids: check Settings -> Devices -> your gateway.
# To use it by hand: Settings -> Dashboards -> Add dashboard -> open it -> ⋮ -> Edit -> ⋮ -> Raw configuration
# editor, paste, and adjust the entity ids.
"""
out = HEADER + yaml.dump(dc.build_config(ctx), Dumper=Dumper, allow_unicode=True, sort_keys=False, width=1000)
(ROOT / "dashboards/building_overview.example.yaml").write_text(out, encoding="utf-8")
print("written", len(out.splitlines()), "lines")
