"""Gateway hub: subscribes to the uplink topic and routes / discovers devices."""
from __future__ import annotations

import logging
from typing import Callable

from homeassistant.components import mqtt
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_DEVEUI,
    CONF_PAYLOAD_ENCODING,
    CONF_TOPIC,
    DOMAIN,
    ENCODING_BASE64,
    SIGNAL_UPLINK,
)
from .decoders import Uplink, parse_envelope
from .models import guess_model

_LOGGER = logging.getLogger(__name__)


class Hub:
    """One gateway / MQTT uplink topic."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        cfg = {**entry.data, **entry.options}
        self.topic: str = cfg[CONF_TOPIC]
        self.encoding: str = cfg.get(CONF_PAYLOAD_ENCODING, ENCODING_BASE64)
        self.last_uplink: dict[str, Uplink] = {}
        self._announced: set[str] = set()
        self._unsub: Callable[[], None] | None = None

    async def async_start(self) -> None:
        self._unsub = await mqtt.async_subscribe(self.hass, self.topic, self._message_received, qos=0)
        _LOGGER.debug("Subscribed to %s", self.topic)

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def forget(self, deveui: str) -> None:
        """Allow a removed device to be discovered again."""
        self._announced.discard(deveui)

    @callback
    def _message_received(self, msg: mqtt.ReceiveMessage) -> None:
        up = parse_envelope(msg.payload, self.encoding)
        if up is None:
            return
        self.last_uplink[up.deveui] = up

        if self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, up.deveui):
            async_dispatcher_send(self.hass, SIGNAL_UPLINK.format(up.deveui), up)
            return

        if up.deveui in self._announced:
            return
        self._announced.add(up.deveui)
        best, candidates = guess_model(up.raw)
        _LOGGER.info("Discovered new LoRaWAN device %s (guess: %s)", up.deveui, best)
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={
                    CONF_DEVEUI: up.deveui,
                    "guess": best,
                    "candidates": candidates,
                    "device_name": up.device_name,
                },
            )
        )
