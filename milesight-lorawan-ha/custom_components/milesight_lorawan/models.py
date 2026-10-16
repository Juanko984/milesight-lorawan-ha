"""Device model registry and entity specifications (pure Python)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .decoders import decode_em300, decode_vs121


@dataclass(frozen=True)
class EntitySpec:
    """Describes one Home Assistant entity, independent of HA classes."""

    key: str                       # key in the runtime values dict
    name: str
    platform: str = "sensor"       # "sensor" | "binary_sensor"
    kind: str = "plain"            # plain | duration (seconds -> min) | timestamp (epoch) | text
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    diagnostic: bool = False
    enabled_default: bool = True
    precision: int | None = None


@dataclass(frozen=True)
class Model:
    key: str
    label: str
    decoder: Callable[[bytes], dict]
    features: frozenset[str] = field(default_factory=frozenset)
    beta: bool = False


MODELS: dict[str, Model] = {
    "VS121": Model("VS121", "VS121 AI people counter", decode_vs121, frozenset({"occupancy"})),
    "EM300-TH": Model("EM300-TH", "EM300-TH temperature & humidity", decode_em300, frozenset({"env"})),
    "EM300-MCS": Model("EM300-MCS", "EM300-MCS magnetic contact (door/window)", decode_em300, frozenset({"env", "door"})),
    "EM300-SLD": Model("EM300-SLD", "EM300-SLD spot leak detector", decode_em300, frozenset({"env", "leak"})),
    "EM300-ZLD": Model("EM300-ZLD", "EM300-ZLD zone leak detector", decode_em300, frozenset({"env", "leak"})),
    "EM300-DI": Model("EM300-DI", "EM300-DI digital input / pulse (beta)", decode_em300, frozenset({"env", "input", "pulse"}), beta=True),
}


def guess_model(raw: bytes | None) -> tuple[str | None, list[str]]:
    """Best guess + candidate list from a raw payload."""
    if not raw:
        return None, list(MODELS)
    vs = decode_vs121(raw)
    if "people_count_all" in vs:
        return "VS121", ["VS121"]
    em = decode_em300(raw)
    if "pulse_count" in em or "gpio" in em:
        return "EM300-DI", ["EM300-DI"]
    if "status_input" in em:
        return "EM300-MCS", ["EM300-MCS", "EM300-SLD", "EM300-ZLD"]
    if "temperature" in em or "humidity" in em:
        return "EM300-TH", ["EM300-TH", "EM300-MCS", "EM300-SLD", "EM300-ZLD", "EM300-DI"]
    return None, list(MODELS)


# --------------------------------------------------------------------------
# Entity specs
# --------------------------------------------------------------------------
def _common() -> list[EntitySpec]:
    return [
        EntitySpec("rssi", "RSSI", unit="dBm", device_class="signal_strength",
                   state_class="measurement", diagnostic=True),
        EntitySpec("snr", "SNR", unit="dB", state_class="measurement", icon="mdi:access-point", diagnostic=True),
        EntitySpec("last_seen", "Last seen", kind="timestamp", device_class="timestamp", diagnostic=True),
    ]


def _env() -> list[EntitySpec]:
    t = dict(unit="°C", device_class="temperature", state_class="measurement")
    h = dict(unit="%", device_class="humidity", state_class="measurement")
    return [
        EntitySpec("temperature", "Temperature", **t),
        EntitySpec("humidity", "Humidity", **h),
        EntitySpec("battery", "Battery", unit="%", device_class="battery", state_class="measurement", diagnostic=True),
        EntitySpec("feels_like", "Feels like", icon="mdi:thermometer-check", **t),
        EntitySpec("temperature_min_today", "Temperature min today", icon="mdi:thermometer-low", **t),
        EntitySpec("temperature_max_today", "Temperature max today", icon="mdi:thermometer-high", **t),
        EntitySpec("humidity_min_today", "Humidity min today", icon="mdi:water-minus", **h),
        EntitySpec("humidity_max_today", "Humidity max today", icon="mdi:water-plus", **h),
    ]


def _binary_event(prefix: str, noun: str, verb_on: str, device_class: str | None,
                  icon_on: str, with_left_open: bool) -> list[EntitySpec]:
    """Stats for a binary input. noun='Door', verb_on='open' -> 'Door open today'."""
    dur = dict(kind="duration", unit="min", device_class="duration", precision=1)
    cnt = dict(state_class="total_increasing", icon="mdi:counter")
    p = prefix
    specs = [
        EntitySpec(f"{p}active", noun, platform="binary_sensor", device_class=device_class),
        EntitySpec(f"{p}status", f"{noun} status", kind="text", icon=icon_on),
        EntitySpec(f"{p}current_s", f"{noun} {verb_on} duration", icon="mdi:timer-sand", **dur),
        EntitySpec(f"{p}since", f"{noun} {verb_on} since", kind="timestamp", device_class="timestamp", icon=icon_on),
        EntitySpec(f"{p}last_on_at", f"{noun} last {verb_on}", kind="timestamp", device_class="timestamp"),
        EntitySpec(f"{p}last_off_at", f"{noun} last cleared" if prefix == "leak_" else f"{noun} last closed",
                   kind="timestamp", device_class="timestamp"),
        EntitySpec(f"{p}last_duration_s", f"{noun} last {verb_on} duration", icon="mdi:history", **dur),
        EntitySpec(f"{p}today_s", f"{noun} {verb_on} today", icon="mdi:calendar-today", state_class="total_increasing", **dur),
        EntitySpec(f"{p}yesterday_s", f"{noun} {verb_on} yesterday", icon="mdi:calendar-arrow-left", **dur),
        EntitySpec(f"{p}week_s", f"{noun} {verb_on} this week", icon="mdi:calendar-week", state_class="total_increasing", **dur),
        EntitySpec(f"{p}last_week_s", f"{noun} {verb_on} last week", icon="mdi:calendar-week-begin", **dur),
        EntitySpec(f"{p}month_s", f"{noun} {verb_on} this month", icon="mdi:calendar-month", state_class="total_increasing", **dur),
        EntitySpec(f"{p}last_month_s", f"{noun} {verb_on} last month", icon="mdi:calendar-month-outline", **dur),
        EntitySpec(f"{p}count_today", f"{noun} events today", **cnt),
        EntitySpec(f"{p}count_yesterday", f"{noun} events yesterday", icon="mdi:counter"),
        EntitySpec(f"{p}count_week", f"{noun} events this week", **cnt),
        EntitySpec(f"{p}count_last_week", f"{noun} events last week", icon="mdi:counter"),
        EntitySpec(f"{p}count_month", f"{noun} events this month", **cnt),
        EntitySpec(f"{p}count_last_month", f"{noun} events last month", icon="mdi:counter"),
        EntitySpec(f"{p}longest_today_s", f"{noun} longest {verb_on} today", icon="mdi:timer-alert-outline", **dur),
        EntitySpec(f"{p}longest_week_s", f"{noun} longest {verb_on} this week", icon="mdi:timer-alert-outline", **dur),
        EntitySpec(f"{p}avg_today_s", f"{noun} average {verb_on} today", icon="mdi:timer-outline", **dur),
    ]
    if with_left_open:
        specs.insert(1, EntitySpec(f"{p}left_open", f"{noun} left {verb_on}", platform="binary_sensor",
                                   device_class="problem", icon=icon_on))
    return specs


def _occupancy() -> list[EntitySpec]:
    dur = dict(kind="duration", unit="min", device_class="duration", precision=1)
    return [
        EntitySpec("occ_occupied", "Occupied", platform="binary_sensor", device_class="occupancy"),
        EntitySpec("occ_status", "Occupancy status", kind="text", icon="mdi:account-group"),
        EntitySpec("people_count_all", "People count", state_class="measurement", icon="mdi:account-group"),
        EntitySpec("region_count", "Region count", icon="mdi:account-eye", enabled_default=False),
        EntitySpec("occ_occupied_since", "Occupied since", kind="timestamp", device_class="timestamp", icon="mdi:clock-start"),
        EntitySpec("occ_occupied_duration_s", "Occupied duration", icon="mdi:timer-sand", **dur),
        EntitySpec("occ_last_session_s", "Last session", icon="mdi:history", **dur),
        EntitySpec("occ_longest_session_today_s", "Longest session today", icon="mdi:timer-alert-outline", **dur),
        EntitySpec("occ_occupied_today_s", "Occupied today", icon="mdi:calendar-today", state_class="total_increasing", **dur),
        EntitySpec("occ_occupied_yesterday_s", "Occupied yesterday", icon="mdi:calendar-arrow-left", **dur),
        EntitySpec("occ_sessions_today", "Sessions today", state_class="total_increasing", icon="mdi:counter"),
        EntitySpec("occ_sessions_yesterday", "Sessions yesterday", icon="mdi:counter"),
        EntitySpec("occ_peak_today", "Peak people today", icon="mdi:account-multiple-plus"),
        EntitySpec("occ_peak_today_at", "Peak people time", kind="timestamp", device_class="timestamp",
                   icon="mdi:clock-star-four-points-outline"),
        EntitySpec("occ_peak_yesterday", "Peak people yesterday", icon="mdi:account-multiple"),
        EntitySpec("occ_person_minutes_today", "Person-minutes today", unit="person-min",
                   state_class="total_increasing", icon="mdi:account-clock"),
        EntitySpec("occ_person_minutes_yesterday", "Person-minutes yesterday", unit="person-min",
                   icon="mdi:account-clock-outline"),
        EntitySpec("occ_avg_people_today", "Average people when occupied", unit="people", icon="mdi:account-group-outline"),
        EntitySpec("occ_utilisation_today_pct", "Utilisation today", unit="%", state_class="measurement",
                   icon="mdi:chart-donut", precision=1),
        EntitySpec("occ_utilisation_yesterday_pct", "Utilisation yesterday", unit="%", icon="mdi:chart-donut-variant",
                   precision=1),
    ]


def entity_specs(model_key: str) -> list[EntitySpec]:
    model = MODELS[model_key]
    f = model.features
    specs: list[EntitySpec] = []
    if "occupancy" in f:
        specs += _occupancy()
    if "env" in f:
        specs += _env()
    if "door" in f:
        specs += _binary_event("door_", "Door", "open", "door", "mdi:door-open", with_left_open=True)
    if "leak" in f:
        specs += _binary_event("leak_", "Leak", "active", "moisture", "mdi:water-alert", with_left_open=False)
    if "input" in f:
        specs += _binary_event("input_", "Input", "high", None, "mdi:electric-switch", with_left_open=False)
    if "pulse" in f:
        specs.append(EntitySpec("pulse_count", "Pulse count", state_class="total_increasing", icon="mdi:counter"))
    return specs + _common()
