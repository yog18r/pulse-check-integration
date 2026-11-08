"""Battery history from the recorder, for cycles and days-left estimates.

Home Assistant's *recorder* keeps every state change in a database and,
for sensors with `state_class: measurement`, long-term *statistics*: one
mean per hour and per day. Reading those is cheap and never touches a
device. For every battery this module fetches:

- up to a year of daily means, to see whole cycles (a coin cell lasting
  eight months, a blind charged every two), and
- hourly means for the last fortnight, to measure the current cycle of a
  device that gets charged (days until a charge is needed).

Sensors without statistics fall back to raw state history, collapsed to
the same daily and hourly means; batteries that only exist as a
`battery_level` attribute (vacuums, trackers) use raw history with
attributes. The pure analysis lives in `core/cycles.py`.

The recorder runs its queries in its own worker thread via
`get_instance(hass).async_add_executor_job`, so the event loop is never
blocked by a slow database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .core.battery import parse_numeric
from .core.cycles import BatteryInsight, assess
from .core.drain import DrainPoint, daily_means, hourly_means, rows_to_points
from .core.models import as_utc

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant, State

    from .core import CoreConfig, DeviceHealth
    from .storage import PulseCheckStore

_LOGGER = logging.getLogger(__name__)

# Daily means over up to a year: enough to see several replacement cycles.
HISTORY_LONG_DAYS = 365
# Hourly means over the last fortnight: enough to measure a charge cycle.
HISTORY_FINE_DAYS = 14
# Raw state history is heavier than statistics, so the fallback looks back less.
RAW_FALLBACK_DAYS = 90
# Windows this short get hourly points, so a sparkline has some shape.
HOURLY_MAX_DAYS = 3
# A charging signal seen within this long still classifies the battery as charged.
CHARGING_SIGNAL_MEMORY = timedelta(days=HISTORY_LONG_DAYS)
# Insights live here so a reloaded entry (saved options) starts with the
# previous ones instead of nothing until its own first history read.
DATA_INSIGHTS = f"{DOMAIN}_insights"


type Samples = list[tuple[datetime, float | None]]


def _history_samples(
    hass: HomeAssistant, start: datetime, entity_ids: Iterable[str], attribute: str | None
) -> dict[str, Samples]:
    """Levels from raw state history, one sample per row. Runs in the recorder's thread.

    With `attribute` set, the level is read from that attribute instead of
    the state; attributes are only stored when they change, so the last
    seen value carries forward. Reading attributes is the expensive part
    (a tracker stores a row per location update), so callers read each
    entity once and derive every window from the samples.
    """
    samples: dict[str, Samples] = {}
    for entity_id in entity_ids:
        rows = state_changes_during_period(
            hass, start, None, entity_id, no_attributes=attribute is None
        ).get(entity_id, [])
        samples[entity_id] = _samples(rows, attribute)
    return samples


def _samples(states: Iterable[State], attribute: str | None) -> Samples:
    samples: Samples = []
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
    """Keeps a battery insight per battery entity, refreshed every few hours."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Start from the previous tracker's insights, if any, until the first refresh."""
        self.hass = hass
        self.insights: dict[str, BatteryInsight] = hass.data.get(DATA_INSIGHTS, {})

    @property
    def available(self) -> bool:
        """The recorder is optional; without it there is simply no history."""
        return "recorder" in self.hass.config.components

    async def _statistics(
        self, sensor_ids: set[str], days: int, period: str
    ) -> dict[str, list[DrainPoint]]:
        """Recorder statistics (means) per sensor over the last `days`; empty when none."""
        if not sensor_ids:
            return {}
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            dt_util.utcnow() - timedelta(days=days),
            None,
            sensor_ids,
            period,
            None,
            {"mean"},
        )
        points = {entity_id: rows_to_points(rows) for entity_id, rows in stats.items()}
        return {entity_id: found for entity_id, found in points.items() if found}

    async def _raw(
        self, sensor_ids: set[str], attribute_ids: set[str], days: int
    ) -> dict[str, Samples]:
        """Raw samples over the last `days` (at most the raw fallback window), read once."""
        start = dt_util.utcnow() - timedelta(days=min(days, RAW_FALLBACK_DAYS))
        recorder = get_instance(self.hass)
        samples: dict[str, Samples] = {}
        if sensor_ids:
            samples.update(
                await recorder.async_add_executor_job(
                    _history_samples, self.hass, start, sensor_ids, None
                )
            )
        if attribute_ids:
            samples.update(
                await recorder.async_add_executor_job(
                    _history_samples, self.hass, start, attribute_ids, "battery_level"
                )
            )
        return samples

    async def _means(
        self,
        sensor_ids: set[str],
        attribute_ids: set[str],
        days: int,
        period: str,
        hourly: bool,
    ) -> dict[str, list[DrainPoint]]:
        """Means per entity over the last `days`: statistics first, raw history as fallback."""
        points = await self._statistics(sensor_ids, days, period)
        raw = await self._raw(sensor_ids - points.keys(), attribute_ids, days)
        collapse = hourly_means if hourly else daily_means
        for entity_id, samples in raw.items():
            points[entity_id] = collapse(samples)
        return points

    async def async_refresh(
        self, devices: Iterable[DeviceHealth], store: PulseCheckStore, config: CoreConfig
    ) -> None:
        """Re-read history for every battery device with a numeric level.

        The store supplies what the history alone cannot: the user's
        rechargeable setting, recorded replacements and charges (cycle
        boundaries), and whether a charging signal has been seen.
        """
        if not self.available:
            return
        batteries: dict[str, DeviceHealth] = {}
        sensor_ids: set[str] = set()
        attribute_ids: set[str] = set()
        for device in devices:
            battery = device.battery
            if battery is None or battery.level is None:
                continue
            batteries[battery.entity_id] = device
            (sensor_ids if battery.source == "sensor" else attribute_ids).add(battery.entity_id)
        if not batteries:
            self.insights = {}
            self.hass.data[DATA_INSIGHTS] = {}
            return

        # Statistics for both windows; raw history only for what they lack,
        # read once and collapsed into both (it is the expensive query).
        daily = await self._statistics(sensor_ids, HISTORY_LONG_DAYS, "day")
        hourly = await self._statistics(sensor_ids, HISTORY_FINE_DAYS, "hour")
        lacking = (sensor_ids - daily.keys()) | (sensor_ids - hourly.keys())
        raw = await self._raw(lacking, attribute_ids, HISTORY_LONG_DAYS)
        now = dt_util.utcnow()
        fine_start = now - timedelta(days=HISTORY_FINE_DAYS)
        for entity_id, samples in raw.items():
            if entity_id not in daily:
                daily[entity_id] = daily_means(samples)
            if entity_id not in hourly:
                hourly[entity_id] = hourly_means([s for s in samples if s[0] >= fine_start])

        insights: dict[str, BatteryInsight] = {}
        for entity_id, device in batteries.items():
            battery = device.battery
            assert battery is not None and battery.level is not None
            settings: dict[str, Any] = store.device_settings.get(device.device_id, {})
            observed: dict[str, Any] = store.levels.get(device.device_id, {})
            charging_seen = observed.get("charging_seen_at")
            charging_signal = battery.is_charging or (
                charging_seen is not None
                and now - as_utc(datetime.fromisoformat(charging_seen)) <= CHARGING_SIGNAL_MEMORY
            )
            events = store.history.get(device.device_id, {}).get("events") or []
            marks = [as_utc(datetime.fromisoformat(event["at"])) for event in events]
            insights[entity_id] = assess(
                daily.get(entity_id, []),
                hourly.get(entity_id, []),
                battery.level,
                now,
                warning=config.battery_warning,
                mobile_app=device.integration == "mobile_app",
                rechargeable=bool(settings.get("rechargeable")),
                charging_signal=charging_signal,
                marks=marks,
            )
        self.insights = insights
        self.hass.data[DATA_INSIGHTS] = insights
        estimated = sum(1 for i in insights.values() if i.estimate is not None)
        kinds = sorted(i.kind for i in insights.values())
        counts = {kind: kinds.count(kind) for kind in dict.fromkeys(kinds)}
        # Nothing estimated is worth a line in the normal log, since the
        # usual reason (under a fortnight of recorded history) is invisible
        # otherwise. The `pulse_check.refresh` service produces it on demand.
        _LOGGER.log(
            logging.INFO if estimated == 0 else logging.DEBUG,
            "Battery insights for %d batteries, %d with an estimate (kinds: %s)%s",
            len(insights),
            estimated,
            counts,
            "; estimates need a fortnight of recorded history or a completed cycle"
            if estimated == 0
            else "",
        )

    async def async_points(
        self, entity_id: str, days: int, attribute: bool = False
    ) -> list[DrainPoint]:
        """History points for one battery over a window, for a sparkline.

        Statistics (hourly for short windows, daily otherwise) when the
        recorder has them, else raw state history collapsed the same way;
        attribute batteries always use raw history with attributes.
        """
        found = await self.async_points_many([(entity_id, days, attribute)])
        return found.get((entity_id, days), [])

    async def async_points_many(
        self, wanted: Iterable[tuple[str, int, bool]]
    ) -> dict[tuple[str, int], list[DrainPoint]]:
        """History points for many batteries at once, keyed by (entity id, days).

        `wanted` holds (entity id, days, is an attribute battery). The
        recorder is asked once per window length, for every battery that
        shares it, instead of once per battery: a dashboard opening with
        forty sparklines costs one query, not forty.
        """
        if not self.available:
            return {}
        windows: dict[int, tuple[set[str], set[str]]] = {}
        for entity_id, days, attribute in wanted:
            sensors, attributes = windows.setdefault(days, (set(), set()))
            (attributes if attribute else sensors).add(entity_id)
        found: dict[tuple[str, int], list[DrainPoint]] = {}
        for days, (sensors, attributes) in windows.items():
            hourly = days <= HOURLY_MAX_DAYS
            points = await self._means(
                sensors, attributes, days, "hour" if hourly else "day", hourly
            )
            for entity_id in sensors | attributes:
                found[(entity_id, days)] = points.get(entity_id, [])
        return found
