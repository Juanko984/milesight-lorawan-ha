"""Register devices on the Milesight gateway's network server from Home Assistant (ns-api over MQTT)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from .ns_api import (
    CODE_EXISTS,
    CODE_NOT_FOUND,
    URL_APPS,
    URL_DEVICE_LIST,
    URL_DEVICES,
    URL_PROFILES,
    NsApiError,
    build_request,
    device_body,
    parse_applications,
    parse_devices,
    parse_profiles,
    parse_response,
)

_LOGGER = logging.getLogger(__name__)
TIMEOUT_S = 12


class NsApiClient:
    def __init__(self, hass: HomeAssistant, request_topic: str, response_topic: str, gateway_eui: str = "") -> None:
        self.hass = hass
        self.request_topic, self.response_topic = request_topic, response_topic
        self.gateway_eui = gateway_eui or ""
        self._waiting: dict[str, asyncio.Future] = {}
        self._unsub: Callable[[], None] | None = None
        self._lock = asyncio.Lock()

    async def _ensure_subscribed(self) -> None:
        async with self._lock:
            if self._unsub is None:
                self._unsub = await mqtt.async_subscribe(self.hass, self.response_topic, self._message, qos=0)
                # Home Assistant sends subscriptions to the broker in batches: give it a moment, so a fast
                # gateway's first answer is not missed
                await asyncio.sleep(1)

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        for fut in self._waiting.values():
            if not fut.done():
                fut.cancel()
        self._waiting.clear()

    @callback
    def _message(self, msg) -> None:
        parsed = parse_response(msg.payload)
        if parsed is None:
            return
        rid, code, error, body = parsed
        fut = self._waiting.pop(rid, None)
        if fut is not None and not fut.done():
            fut.set_result((code, error, body))

    async def async_request(self, method: str, url: str, body: dict | None = None,
                            timeout: float = TIMEOUT_S) -> dict[str, Any]:
        await self._ensure_subscribed()
        rid, text = build_request(method, url, body, self.gateway_eui)
        fut: asyncio.Future = self.hass.loop.create_future()
        self._waiting[rid] = fut
        _LOGGER.debug("ns-api %s %s (%s)", method, url, rid)
        await mqtt.async_publish(self.hass, self.request_topic, text, qos=1)
        try:
            code, error, rbody = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as err:
            raise NsApiError(None, f"no answer on {self.response_topic} within {timeout:.0f} s") from err
        finally:
            self._waiting.pop(rid, None)
        if code not in (200, None):
            raise NsApiError(code, error)
        return rbody

    # -------------------------------------------------------------- calls
    async def async_overview(self) -> dict[str, Any]:
        """Devices, applications and profiles on the gateway (one round trip, plus profiles / apps if missing)."""
        body = await self.async_request("GET", URL_DEVICE_LIST)
        apps, profiles = parse_applications(body), parse_profiles(body)
        if not profiles:
            try:
                profiles = parse_profiles(await self.async_request("GET", URL_PROFILES))
            except NsApiError:
                _LOGGER.debug("Could not list profiles", exc_info=True)
        if not apps:
            try:
                apps = parse_applications(await self.async_request("GET", URL_APPS))
            except NsApiError:
                _LOGGER.debug("Could not list applications", exc_info=True)
        return {"devices": parse_devices(body), "applications": apps, "profiles": profiles}

    async def async_add_device(self, deveui: str, name: str, application_id: str, profile_id: str,
                               app_key: str | None = None, fport: int = 85) -> str:
        """'added' or 'exists' (already registered – left as it is)."""
        try:
            await self.async_request("POST", URL_DEVICES, device_body(deveui, name, application_id, profile_id,
                                                                      app_key, fport))
        except NsApiError as err:
            if err.code == CODE_EXISTS:
                return "exists"
            raise
        return "added"

    async def async_remove_device(self, deveui: str) -> bool:
        try:
            await self.async_request("DELETE", f"{URL_DEVICES}/{deveui.lower()}")
        except NsApiError as err:
            if err.code == CODE_NOT_FOUND:
                return False
            raise
        return True
