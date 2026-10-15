"""Battery history from the recorder, for drain estimates.

Home Assistant's *recorder* keeps every state change in a database and,
for sensors with `state_class: measurement`, long-term *statistics*: one
mean per hour and per day. Reading those is cheap and never touches a
device. This module asks for the last 14 days of daily means for every
battery sensor, falls back to raw state history for sensors without
statistics, and uses raw history with attributes for batteries that are
only reported as a `battery_level` attribute (vacuums, trackers).

The recorder runs its queries in its own worker thread via
`get_instance(hass).async_add_executor_job`, so the event loop is never
blocked by a slow database.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util

from .const import HISTORY_DAYS
from .core.battery import parse_numeric
from .core.drain import (
    DrainEstimate,
    DrainPoint,
    daily_means,
    estimate_drain,
    hourly_means,
    rows_to_points,
)

# Windows this short get hourly points, so a sparkline has some shape.
HOURLY_MAX_DAYS = 3

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from homeassistant.core import HomeAssistant, State

    from .core import DeviceHealth

_LOGGER = logging.getLogger(__name__)


def _history_points(
    hass: HomeAssistant,
    start: datetime,
    entity_ids: Iterable[str],
    attribute: str | None,
    hourly: bool = False,
) -> dict[str, list[DrainPoint]]:
    """Daily (or hourly) means from raw state history. Runs in the recorder's thread.

    With `attribute` set, the level is read from that attribute instead of
    the state; attributes are only stored when they change, so the last
    seen value carries forward.
    """
    points: dict[str, list[DrainPoint]] = {}
    collapse = hourly_means if hourly else daily_means
    for entity_id in entity_ids:
        rows = state_changes_during_period(
            hass, start, None, entity_id, no_attributes=attribute is None
        ).get(entity_id, [])
        points[entity_id] = collapse(_samples(rows, attribute))
    return points


def _samples(states: Iterable[State], attribute: str | None) -> list[tuple[datetime, float | None]]:
    samples: list[tuple[datetime, float | None]] = []
    last_seen: object = None
    for state in states:
        if attribute is None:
            value: object = state.state
        else:
            if attribute in state.attributes:
                last_seen = state.attributes[attribute]
            value = last_seen
        samples.append((state.last_updated, parse_numeric(value)))
    return samples


class HistoryTracker:
    """Keeps a drain estimate per battery entity, refreshed every few hours."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Start with no estimates; they arrive after the first refresh."""
        self.hass = hass
        self.estimates: dict[str, DrainEstimate] = {}

    @property
    def available(self) -> bool:
        """The recorder is optional; without it there is simply no history."""
        return "recorder" in self.hass.config.components

    async def async_refresh(self, devices: Iterable[DeviceHealth]) -> None:
        """Re-read history for every battery device with a numeric level."""
        if not self.available:
            return
        levels: dict[str, float] = {}
        sensor_ids: set[str] = set()
        attribute_ids: set[str] = set()
        for device in devices:
            battery = device.battery
            if battery is None or battery.level is None:
                continue
            levels[battery.entity_id] = battery.level
            (sensor_ids if battery.source == "sensor" else attribute_ids).add(battery.entity_id)
        if not levels:
            self.estimates = {}
            return

        now = dt_util.utcnow()
        start = now - timedelta(days=HISTORY_DAYS)
        recorder = get_instance(self.hass)

        points: dict[str, list[DrainPoint]] = {}
        if sensor_ids:
            stats = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass,
                start,
                None,
                sensor_ids,
                "day",
                None,
                {"mean"},
            )
            for entity_id, rows in stats.items():
                points[entity_id] = rows_to_points(rows)
        # Sensors the recorder has no statistics for: raw history instead.
        without_stats = sensor_ids - {k for k, v in points.items() if v}
        if without_stats:
            points.update(
                await recorder.async_add_executor_job(
                    _history_points, self.hass, start, without_stats, None
                )
            )
        if attribute_ids:
            points.update(
                await recorder.async_add_executor_job(
                    _history_points, self.hass, start, attribute_ids, "battery_level"
                )
            )

        self.estimates = self._fit(points, levels, now)
        _LOGGER.debug("Drain estimates for %d of %d batteries", len(self.estimates), len(levels))

    @staticmethod
    def _fit(
        points: dict[str, list[DrainPoint]], levels: dict[str, float], now: datetime
    ) -> dict[str, DrainEstimate]:
        estimates: dict[str, DrainEstimate] = {}
        for entity_id, level in levels.items():
            history = [*points.get(entity_id, []), DrainPoint(time=now, level=level)]
            estimate = estimate_drain(history, level)
            if estimate is not None:
                estimates[entity_id] = estimate
        return estimates

    async def async_points(
        self, entity_id: str, days: int, attribute: bool = False
    ) -> list[DrainPoint]:
        """History points for one battery over a window, for a sparkline.

        Statistics (hourly for short windows, daily otherwise) when the
        recorder has them, else raw state history collapsed the same way;
        attribute batteries always use raw history with attributes.
        """
        if not self.available:
            return []
        now = dt_util.utcnow()
        start = now - timedelta(days=days)
        hourly = days <= HOURLY_MAX_DAYS
        recorder = get_instance(self.hass)
        if attribute:
            found = await recorder.async_add_executor_job(
                _history_points, self.hass, start, {entity_id}, "battery_level", hourly
            )
            return found.get(entity_id, [])
        stats = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            None,
            {entity_id},
            "hour" if hourly else "day",
            None,
            {"mean"},
        )
        points = rows_to_points(stats.get(entity_id, []))
        if points:
            return points
        found = await recorder.async_add_executor_job(
            _history_points, self.hass, start, {entity_id}, None, hourly
        )
        return found.get(entity_id, [])
