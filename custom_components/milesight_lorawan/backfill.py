"""Fill gaps in Home Assistant's long-term statistics from records the device stored while offline."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def hourly(records: list[tuple[int, dict]], keys: set[str]) -> dict[str, dict[datetime, list[float]]]:
    """key -> hour start (UTC) -> values (numbers only)."""
    out: dict[str, dict[datetime, list[float]]] = defaultdict(lambda: defaultdict(list))
    for ts, vals in records:
        hour = datetime.fromtimestamp(ts - ts % 3600, timezone.utc)
        for k, v in vals.items():
            if k in keys and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k][hour].append(float(v))
    return out


async def async_import(hass: HomeAssistant, deveui: str, records: list[tuple[int, dict]],
                       measure_keys: dict[str, str | None]) -> int:
    """Import hourly mean / min / max for hours that have no statistics yet. Returns hours added."""
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import (
            async_import_statistics,
            statistics_during_period,
        )
    except ImportError:          # recorder not available
        return 0
    try:
        from homeassistant.components.recorder.models import StatisticMeanType
    except ImportError:
        StatisticMeanType = None  # noqa: N806 - Home Assistant before 2025.x

    reg = er.async_get(hass)
    now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    per_key = hourly(records, set(measure_keys))
    added = 0
    for key, hours in per_key.items():
        entity_id = reg.async_get_entity_id("sensor", DOMAIN, f"{deveui}_{key}")
        if entity_id is None:
            continue
        candidates = sorted(h for h in hours if h < now_hour)
        if not candidates:
            continue
        existing = await get_instance(hass).async_add_executor_job(
            statistics_during_period, hass, candidates[0], candidates[-1] + timedelta(hours=1), {entity_id},
            "hour", None, {"mean"})
        have = {row["start"] if isinstance(row["start"], datetime) else datetime.fromtimestamp(row["start"], timezone.utc)
                for row in existing.get(entity_id, [])}
        missing = [h for h in candidates if h not in have]
        if not missing:
            continue
        state = hass.states.get(entity_id)
        unit = state.attributes.get("unit_of_measurement") if state else measure_keys.get(key)
        meta: dict[str, Any] = {"has_sum": False, "name": None, "source": "recorder", "statistic_id": entity_id,
                                "unit_of_measurement": unit}
        if StatisticMeanType is not None:
            meta["mean_type"] = StatisticMeanType.ARITHMETIC
            meta["unit_class"] = _unit_class(state)
        else:
            meta["has_mean"] = True
        stats = [{"start": h, "mean": sum(hours[h]) / len(hours[h]), "min": min(hours[h]), "max": max(hours[h])}
                 for h in missing]
        async_import_statistics(hass, meta, stats)
        added += len(stats)
    if added:
        _LOGGER.info("Filled %s hour(s) of statistics for %s from stored device data", added, deveui)
    return added


def _unit_class(state) -> str | None:
    if state is None:
        return None
    try:
        from homeassistant.components.sensor import UNIT_CONVERTERS
        conv = UNIT_CONVERTERS.get(state.attributes.get("device_class"))
        return conv.UNIT_CLASS if conv else None
    except Exception:  # noqa: BLE001
        return None
