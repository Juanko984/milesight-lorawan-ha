"""What a device is used for ('purpose'): the thing it is fitted to, not the sensor type. A purpose decides the
device's label group, how its entities look, default thresholds, extra analytics and alerts, and dashboards.
Pure Python (unit-tested). One purpose per device; multi-channel clamps can have one per channel."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# label groups (= device tags) -> (label, icon). The model-based tags (tank, people, comfort …) live in models.TAGS.
GROUPS = {
    "cold_chain": ("Milesight · Cold chain", "mdi:snowflake-thermometer"),
    "pump": ("Milesight · Pumps & motors", "mdi:pump"),
    "hvac": ("Milesight · HVAC", "mdi:hvac"),
    "energy": ("Milesight · Energy", "mdi:lightning-bolt"),
    "security": ("Milesight · Security", "mdi:shield-home"),
    "water": ("Milesight · Water", "mdi:water"),
    "tank": ("Milesight · Tank / silo", "mdi:storage-tank"),
    "irrigation": ("Milesight · Irrigation", "mdi:sprinkler-variant"),
    "facilities": ("Milesight · Facilities", "mdi:broom"),
    "assets": ("Milesight · Assets & vehicles", "mdi:truck-fast"),
    "comfort": ("Milesight · Air & comfort", "mdi:air-filter"),
    "people": ("Milesight · People & occupancy", "mdi:account-group"),
}

# settings a purpose can set (defaults) and the user can override (option "p_<name>")
SETTINGS = ("temp_low", "temp_high", "temp_delay_min", "temp_rise_day", "left_open_min", "after_hours",
            "max_run_h", "no_run_h", "service_h", "run_w", "bin_depth_mm", "full_pct", "empty_distance_mm",
            "rise_cm_h", "flood_danger_cm", "co2_limit", "clean_visits", "latch_min")


@dataclass(frozen=True)
class Purpose:
    key: str
    label: str
    group: str | None
    families: frozenset[str]
    defaults: dict[str, Any] = field(default_factory=dict)
    noun: str | None = None          # replaces "Door" / "Load" in entity names
    icon: str | None = None
    contact_class: str | None = None  # binary sensor device class of the contact
    severity: str = "warning"         # alerts that come from this purpose
    meter: str | None = None          # pulse counters: meter type
    contact_noun: str | None = None   # the contact's name when it differs from the load's ("Door" on a fridge)

    @property
    def door_noun(self) -> str:
        return self.contact_noun or self.noun or "Door"


def _p(key, label, group, families, noun=None, icon=None, contact_class=None, severity="warning", meter=None,
       contact_noun=None, **defaults) -> Purpose:
    return Purpose(key, label, group, frozenset(families.split()), defaults, noun, icon, contact_class, severity,
                   meter, contact_noun)


PURPOSES: dict[str, Purpose] = {p.key: p for p in (
    # ---- cold chain (probe, door contact and compressor clamp of the same fridge share the purpose)
    _p("fridge", "Fridge / cold room", "cold_chain", "temperature load contact", "Compressor", "mdi:fridge-outline",
       "door", "critical", contact_noun="Door", temp_low=0, temp_high=5, temp_delay_min=15, left_open_min=2, max_run_h=3, no_run_h=3),
    _p("freezer", "Freezer", "cold_chain", "temperature load contact", "Compressor", "mdi:fridge-industrial-outline",
       "door", "critical", contact_noun="Door", temp_low=-25, temp_high=-15, temp_delay_min=20, left_open_min=2, max_run_h=4, no_run_h=4),
    # ---- motors
    _p("pump", "Pump", "pump", "load", "Pump", "mdi:pump"),
    _p("air_compressor", "Air compressor", "pump", "load", "Compressor", "mdi:air-filter", after_hours=True,
       max_run_h=1),
    _p("motor", "Motor / conveyor / machine", "pump", "load", "Motor", "mdi:engine", service_h=500),
    # ---- HVAC and energy
    _p("ac", "Air conditioner / heat pump", "hvac", "load", "Air conditioner", "mdi:air-conditioner",
       after_hours=True),
    _p("geyser", "Geyser / water heater", "energy", "load temperature leak", "Geyser", "mdi:water-boiler",
       temp_low=55, temp_delay_min=60),
    _p("lighting", "Lighting circuit", "energy", "load", "Lights", "mdi:lightbulb-group", after_hours=True),
    _p("mains", "Mains / distribution board", "energy", "load", "Mains", "mdi:transmission-tower"),
    _p("appliance", "Other machine / appliance", "energy", "load", "Appliance", "mdi:power-plug"),
    # ---- openings
    _p("door", "Door", "security", "contact", "Door", "mdi:door", "door", left_open_min=10, after_hours=True),
    _p("window", "Window", "security", "contact", "Window", "mdi:window-open-variant", "window", left_open_min=60),
    _p("gate", "Gate", "security", "contact", "Gate", "mdi:gate", "opening", left_open_min=30, after_hours=True),
    _p("garage", "Garage / roller door", "security", "contact", "Garage door", "mdi:garage-open-variant",
       "garage_door", left_open_min=15, after_hours=True),
    _p("cabinet", "Cabinet / safe / server rack", "security", "contact", "Cabinet", "mdi:safe", "door",
       left_open_min=5, after_hours=True),
    _p("lid", "Tank lid / hatch", "security", "contact", "Lid", "mdi:storage-tank-outline", "opening",
       left_open_min=10, after_hours=True),
    # ---- temperatures, rooms, air
    _p("room", "Room / office", "comfort", "temperature air motion"),
    _p("meeting_room", "Meeting room", "people", "air motion"),
    _p("classroom", "Classroom", "comfort", "air motion", co2_limit=1000),
    _p("warehouse", "Warehouse / factory", "comfort", "air temperature motion", co2_limit=1500),
    _p("server_room", "Server room", "security", "temperature leak air contact", "Rack door", "mdi:server",
       "door", "critical", temp_high=27, temp_delay_min=10, left_open_min=15),
    _p("pool", "Pool / water", "water", "temperature", icon="mdi:pool-thermometer"),
    _p("pipe", "Pipe (frost watch)", "water", "temperature", icon="mdi:pipe", temp_low=3, temp_delay_min=30),
    _p("outdoor", "Outdoor", "comfort", "temperature", icon="mdi:sun-thermometer"),
    # ---- water
    _p("washer", "Washing machine / dishwasher", "water", "leak load", "Washing machine", "mdi:washing-machine"),
    _p("basement", "Basement / sump", "water", "leak", icon="mdi:home-flood", severity="critical"),
    _p("roof", "Roof / ceiling", "water", "leak", icon="mdi:home-roof"),
    _p("water_tank", "Water tank", "tank", "level", icon="mdi:water-pump"),
    _p("water_trough", "Water trough (float switch)", "tank", "contact", "Trough", "mdi:water-well", "problem",
       contact_noun="Trough", left_open_min=10),
    _p("fuel_tank", "Fuel tank", "tank", "level", icon="mdi:fuel"),
    _p("silo", "Silo / grain / feed", "tank", "level temperature", icon="mdi:silo", temp_rise_day=3),
    _p("bin", "Waste bin", "facilities", "level", icon="mdi:trash-can", bin_depth_mm=1000, full_pct=80),
    _p("flood", "Flood / drain level (early warning)", "water", "level", icon="mdi:home-flood", severity="critical",
       empty_distance_mm=3000, rise_cm_h=10, flood_danger_cm=50),
    # ---- meters
    _p("water_meter", "Water meter", "water", "pulse", meter="water"),
    _p("electricity_meter", "Electricity meter", "energy", "pulse", meter="energy"),
    _p("gas_meter", "Gas meter", "energy", "pulse", meter="gas"),
    _p("rain_gauge", "Rain gauge", "irrigation", "pulse", icon="mdi:weather-pouring", meter="rain"),
    _p("counter", "Production / footfall counter", None, "pulse", meter="none"),
    # ---- people
    _p("desk", "Desk", "people", "motion"),
    _p("counter_zone", "Counter / staff zone (retail)", "people", "motion", icon="mdi:cash-register"),
    _p("toilet", "Toilet / washroom", "facilities", "motion air", icon="mdi:toilet", clean_visits=50),
    _p("intrusion", "Security (intrusion)", "security", "motion", icon="mdi:motion-sensor", after_hours=True),
    # ---- buttons
    _p("panic", "Panic / SOS button", "security", "button", icon="mdi:alarm-light", severity="critical",
       latch_min=30),
    _p("service", "Service request (cleaning, help)", "facilities", "button", icon="mdi:room-service",
       latch_min=60),
    _p("doorbell", "Doorbell", None, "button", icon="mdi:doorbell"),
    _p("scene", "Scene / light control", None, "button"),
    # ---- trackers
    _p("asset", "Asset", "assets", "tracker"),
    _p("vehicle", "Vehicle", "assets", "tracker", icon="mdi:car"),
    _p("livestock", "Livestock", "assets", "tracker", icon="mdi:cow"),
    _p("pivot", "Centre pivot", "irrigation", "tracker", icon="mdi:sprinkler-variant"),
    # ---- soil and valves
    _p("field", "Field soil", "irrigation", "soil"),
    _p("greenhouse", "Greenhouse", "irrigation", "soil temperature"),
    _p("garden", "Garden / turf", "irrigation", "soil"),
    _p("irrigation_valve", "Irrigation valve", "irrigation", "valve"),
    _p("water_valve", "Water main valve", "water", "valve"),
    # ---- poultry / chicken coop (use the usual groups so alerts and cards work; the key tags the coop page)
    _p("coop_drinker", "Coop drinker (water)", "tank", "level", icon="mdi:cup-water"),
    _p("coop_feeder", "Coop feeder (feed)", "tank", "level temperature", icon="mdi:grain"),
    _p("coop_door", "Coop pop-hole / door", "security", "contact", "Pop-hole", "mdi:door-sliding",
       "door", left_open_min=15),
    _p("coop_climate", "Coop climate", "comfort", "temperature air motion", icon="mdi:home-thermometer",
       temp_low=2, co2_limit=3000),
)}

SOIL_PURPOSES = ("field", "greenhouse", "garden")
# poultry-coop purposes: any of these on a device tags the site "coop" (installs the chicken-coop dashboard)
COOP_PURPOSES = ("coop_drinker", "coop_feeder", "coop_door", "coop_climate")
# retail: a staff / counter coverage zone (assigned to a people or occupancy sensor at the till)
RETAIL_PURPOSES = ("counter_zone",)
LOAD_ANALYTICS = ("fridge", "freezer", "air_compressor", "motor", "ac", "geyser", "lighting", "mains", "appliance",
                  "washer")


def get(key: str | None) -> Purpose | None:
    return PURPOSES.get(key or "")


def for_families(families: frozenset[str] | set[str]) -> list[Purpose]:
    """Purposes that make sense for a device with these sensor families, in catalogue order."""
    return [p for p in PURPOSES.values() if p.families & set(families)]


def settings(purpose: str | None, opts: dict[str, Any]) -> dict[str, Any]:
    """Purpose defaults, overridden by the device's options p_<name> (only names the purpose or the user set)."""
    p = get(purpose)
    out = dict(p.defaults) if p else {}
    for name in SETTINGS:
        v = opts.get(f"p_{name}")
        if v == "off":                                   # the user cleared a default limit: no alarm
            out.pop(name, None)
        elif v not in (None, ""):
            out[name] = v
    return out


def in_hours(dt: datetime, open_hour: int, close_hour: int, days: tuple[int, ...]) -> bool:
    """Working hours (days: weekday numbers, Monday = 0)."""
    if days and dt.weekday() not in days:
        return False
    h = dt.hour + dt.minute / 60
    return open_hour <= h < close_hour if open_hour < close_hour else (h >= open_hour or h < close_hour)


def channel_purposes(opts: dict[str, Any], channels: int) -> dict[int, str]:
    """Multi-channel clamps: purpose per channel (purpose_1 …), only those that are set."""
    out = {}
    for n in range(1, channels + 1):
        p = opts.get(f"purpose_{n}")
        if p in PURPOSES:
            out[n] = p
    return out


def setting_fields(purpose: str | None, families: frozenset[str] | set[str]) -> list[str]:
    """Settings the purpose step shows for this purpose on a device with these sensor families."""
    p = get(purpose)
    if p is None:
        return []
    fam, d, out = p.families & set(families), p.defaults, []
    if "temperature" in fam:
        out += ["temp_low", "temp_high", "temp_delay_min"] + (["temp_rise_day"] if "temp_rise_day" in d else [])
    if "contact" in fam:
        out += ["left_open_min", "after_hours"]
    if "load" in fam and p.key in LOAD_ANALYTICS:
        out += ["max_run_h", "no_run_h", "service_h", "after_hours", "run_w"]
    if "motion" in fam and p.key == "intrusion":
        out.append("after_hours")
    if "motion" in fam and p.key == "toilet":
        out.append("clean_visits")
    if "level" in fam and p.key == "bin":
        out += ["bin_depth_mm", "full_pct"]
    if "level" in fam and p.key == "flood":
        out += ["empty_distance_mm", "rise_cm_h", "flood_danger_cm"]
    if "air" in fam:
        out.append("co2_limit")
    if "button" in fam and p.key in ("panic", "service"):
        out.append("latch_min")
    return list(dict.fromkeys(out))


def resolve(text: str | None) -> str | None:
    """A purpose from its key or label (bulk lists): 'fridge', 'Fridge / cold room', 'fridge/cold room'."""
    t = (text or "").strip().lower()
    if not t:
        return None
    norm = "".join(ch for ch in t if ch.isalnum())
    for p in PURPOSES.values():
        if t == p.key or norm == "".join(ch for ch in p.label.lower() if ch.isalnum()) or norm == p.key.replace("_", ""):
            return p.key
    for p in PURPOSES.values():                         # first word of the label: 'fridge', 'gate', 'pump'
        if norm and "".join(ch for ch in p.label.lower().split(" ")[0] if ch.isalnum()) == norm:
            return p.key
    return None
