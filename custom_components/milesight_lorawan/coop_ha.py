"""Chicken-coop controller — the Home Assistant glue for coop_calc.

One manager per gateway. Each tick it reads the configured light and temperature sensors, asks coop_calc for the
desired relay states and switches the lights / heater relays only when the decision changes. The configuration
(which relays, which sensors, the lux and temperature thresholds and the lighting window) is stored in the
gateway options and edited from the Coop controls card on the Chicken-coop page. A role sensor exposes the live
state (lights / heater on or off, the current readings and the reason) for that card.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send

from . import coop_calc as cc
from .const import DOMAIN, MANUFACTURER

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

CONF_COOP_CONTROL = "coop_control"
SIGNAL_COOP = f"{DOMAIN}_coop_{{}}"        # .format(hub entry_id)
STALE_S = 7200.0                            # a reading older than 2 h is treated as dropped out (heater → off)


class CoopManager:
    def __init__(self, hass: HomeAssistant, entry: "ConfigEntry", hub: Any) -> None:
        self.hass, self.entry, self.hub = hass, entry, hub
        self.data: dict[str, Any] = {}

    # ---- config --------------------------------------------------------
    @property
    def config(self) -> dict[str, Any]:
        return cc.normalise(self.entry.options.get(CONF_COOP_CONTROL))

    async def async_save(self, cfg: dict[str, Any]) -> dict[str, Any]:
        clean = cc.normalise(cfg)
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_COOP_CONTROL: clean})
        self.tick()
        return clean

    # ---- reading sensors ----------------------------------------------
    def _read(self, entity_id: str | None) -> tuple[float | None, bool]:
        """(value, fresh) for a sensor entity: None / not-fresh when it is missing, unavailable or stale."""
        if not entity_id:
            return None, False
        st = self.hass.states.get(entity_id)
        if st is None or st.state in (None, "", "unknown", "unavailable"):
            return None, False
        try:
            val = float(st.state)
        except (TypeError, ValueError):
            return None, False
        fresh = True
        try:
            last = st.last_updated.timestamp() if hasattr(st.last_updated, "timestamp") else None
            if last is not None and time.time() - last > STALE_S:
                fresh = False
        except Exception:  # noqa: BLE001
            pass
        return val, fresh

    def _relay_on(self, entity_id: str | None) -> bool:
        if not entity_id:
            return False
        st = self.hass.states.get(entity_id)
        return bool(st and st.state == "on")

    async def _set_relay(self, entity_id: str, on: bool) -> None:
        domain = entity_id.split(".", 1)[0] if "." in entity_id else "switch"
        try:
            await self.hass.services.async_call(
                domain, "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=False)
        except Exception:  # noqa: BLE001 - surfaced on the card via the relay state
            pass

    # ---- the control loop ---------------------------------------------
    @callback
    def tick(self, _now: Any = None) -> None:
        self.hass.async_create_task(self._async_tick())

    async def _async_tick(self) -> None:
        cfg = self.config
        from homeassistant.util import dt as dt_util
        now = dt_util.now()
        hour = now.hour + now.minute / 60.0
        lux, lux_ok = self._read(cfg["lights"]["lux_entity"])
        temp, probe_ok = self._read(cfg["heater"]["temp_entity"])
        lights_on = self._relay_on(cfg["lights"]["relay"])
        heater_on = self._relay_on(cfg["heater"]["relay"])
        decision = cc.evaluate(cfg, hour=hour, lux=lux, temp=temp, lights_on=lights_on, heater_on=heater_on,
                               lux_ok=lux_ok, probe_ok=probe_ok)

        for side in ("lights", "heater"):
            want = decision[side]["want"]
            relay = cfg[side]["relay"]
            cur = lights_on if side == "lights" else heater_on
            if want is not None and relay and want != cur:
                await self._set_relay(relay, want)

        self.data = {
            "milesight_role": "coop_controller", "site": self.entry.title,
            "lights": {**cfg["lights"], "on": decision["lights"]["want"] if decision["lights"]["want"] is not None else lights_on,
                       "lux": None if lux is None else round(lux), "lux_fresh": lux_ok,
                       "reason": decision["lights"]["reason"], "within_window": decision["lights"].get("within_window")},
            "heater": {**cfg["heater"], "on": decision["heater"]["want"] if decision["heater"]["want"] is not None else heater_on,
                       "temp": None if temp is None else round(temp, 1), "probe_fresh": probe_ok,
                       "reason": decision["heater"]["reason"]},
            "updated": now.isoformat(),
        }
        async_dispatcher_send(self.hass, SIGNAL_COOP.format(self.entry.entry_id))


class CoopSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_translation_key = "coop_controller"

    def __init__(self, hass: HomeAssistant, entry: "ConfigEntry", manager: CoopManager) -> None:
        self.hass, self.entry, self.manager = hass, entry, manager
        self._attr_name = "Coop controller"
        self._attr_unique_id = f"{entry.entry_id}_coop_controller"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"hub_{entry.entry_id}")}, name=entry.title,
                                            manufacturer=MANUFACTURER, model="LoRaWAN gateway")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_COOP.format(self.entry.entry_id), self._refresh))
        self.manager.tick()

    @callback
    def _refresh(self) -> None:
        if self.entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        d = self.manager.data
        on = sum(1 for s in ("lights", "heater") if (d.get(s) or {}).get("enabled") and (d.get(s) or {}).get("on"))
        en = sum(1 for s in ("lights", "heater") if (d.get(s) or {}).get("enabled"))
        if not en:
            return "Not set up"
        return f"{on} of {en} on" if on else "All off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.manager.data


async def async_setup_coop(hass: HomeAssistant, entry: "ConfigEntry") -> tuple[CoopManager, list]:
    mgr = CoopManager(hass, entry, entry.runtime_data)
    return mgr, [CoopSensor(hass, entry, mgr)]


# -------------------------------------------------------------- websocket
def _hub_entry(hass: HomeAssistant, hub_id: str | None):
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_HUB
    entries = [e for e in hass.config_entries.async_entries(DOMAIN)
               if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB]
    if hub_id:
        return next((e for e in entries if e.entry_id == hub_id), None)
    return entries[0] if entries else None


def register(hass: HomeAssistant) -> None:
    import voluptuous as vol
    from homeassistant.components import websocket_api

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/coop/set",
                                      vol.Required("config"): dict, vol.Optional("hub"): str})
    @websocket_api.require_admin
    @websocket_api.async_response
    async def ws_set_coop(hass: HomeAssistant, connection, msg: dict) -> None:
        entry = _hub_entry(hass, msg.get("hub"))
        mgr = getattr(getattr(entry, "runtime_data", None), "coop", None) if entry else None
        if mgr is None:
            connection.send_error(msg["id"], "not_found", "No gateway with a coop controller")
            return
        clean = await mgr.async_save(msg["config"])
        connection.send_result(msg["id"], {"ok": True, "config": clean})

    websocket_api.async_register_command(hass, ws_set_coop)
