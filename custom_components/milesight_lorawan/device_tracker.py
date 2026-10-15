"""Device tracker platform (GNSS trackers)."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE
from .entity import MilesightEntity, setup_platform_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        return
    setup_platform_entities(entry, async_add_entities, "device_tracker", MilesightTracker)


class MilesightTracker(MilesightEntity, TrackerEntity):
    """Last GNSS fix reported by the tracker (shown on the map)."""

    _attr_source_type = SourceType.GPS

    def _coord(self, key: str) -> float | None:
        lat, lon = self.runtime.values.get("latitude"), self.runtime.values.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or (lat == 0 and lon == 0):
            return None
        return lat if key == "latitude" else lon

    @property
    def latitude(self) -> float | None:
        return self._coord("latitude")

    @property
    def longitude(self) -> float | None:
        return self._coord("longitude")

    @property
    def extra_state_attributes(self) -> dict:
        v = self.runtime.values
        return {k: v[k] for k in ("motion_status", "geofence_status") if v.get(k) is not None}
