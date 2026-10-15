"""Battery drain estimation: "about 12 days left".

Given a handful of (time, level) samples from the recorder, fit a straight
line through them and read the slope in % per day. Divide the current
level by that rate and you have a rough time to empty.

Deliberately conservative:

- needs at least 3 samples spanning at least 2 days
- a flat or rising line (phones on charge, noisy sensors) gives no estimate
- the result is a rough order of magnitude, never "11.7 days"
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from .models import as_utc

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class DrainPoint:
    """One sample of a battery level."""

    time: datetime
    # Battery level in percent.
    level: float


@dataclass(frozen=True, slots=True)
class DrainEstimate:
    """A fitted drain rate and the days it implies."""

    # Percentage points lost per day. Always positive.
    rate_per_day: float
    # Days until the battery reaches 0% at the current rate.
    days_left: float
    # How many samples the fit used, so callers can hedge on thin data.
    samples: int


SECONDS_PER_DAY = 24 * 60 * 60
MIN_SAMPLES = 3
MIN_SPAN = timedelta(days=2)
# Slopes shallower than this are indistinguishable from noise.
MIN_RATE_PER_DAY = 0.1
# A rise of at least this many points between consecutive samples is a
# new battery or a charge: the fit starts again from there.
CYCLE_START_RISE_POINTS = 20
# Smaller rises still count as charges when they keep happening: a phone
# charged nightly shows one every day. Two or more in the window and no
# line through it means anything.
REPEATED_RISE_POINTS = 15
MAX_RISES = 1


def _ordered(points: Iterable[DrainPoint]) -> list[DrainPoint]:
    return sorted((p for p in points if math.isfinite(p.level)), key=lambda p: as_utc(p.time))


def has_charge_cycles(points: Iterable[DrainPoint]) -> bool:
    """True when the window shows repeated charging: two or more rises of 15+ points.

    One rise is a replacement, a charge, or a sensor glitch that healed
    (a lock reading 42 % then 61 % again); the fit simply starts after it.
    Several rises are a device that gets charged, and no estimate is made.
    """
    ordered = _ordered(points)
    rises = sum(
        1
        for earlier, later in pairwise(ordered)
        if later.level - earlier.level >= REPEATED_RISE_POINTS
    )
    return rises > MAX_RISES


def since_last_rise(points: Iterable[DrainPoint]) -> list[DrainPoint]:
    """The samples from the last big rise onward: the current cycle.

    A rise of 20+ points is a new battery or a full charge, so samples
    before it describe a different battery's life and would only flatten
    the fit. Smaller wobbles are kept.
    """
    ordered = _ordered(points)
    cut = 0
    for index, (earlier, later) in enumerate(pairwise(ordered), start=1):
        if later.level - earlier.level >= CYCLE_START_RISE_POINTS:
            cut = index
    return ordered[cut:]


def _slope_per_day(points: list[DrainPoint]) -> float:
    """Least-squares slope of level against time, in % per day."""
    times = [as_utc(p.time).timestamp() for p in points]
    levels = [p.level for p in points]
    mean_t = sum(times) / len(times)
    mean_l = sum(levels) / len(levels)
    numerator = 0.0
    denominator = 0.0
    for t, level in zip(times, levels, strict=True):
        dt = t - mean_t
        numerator += dt * (level - mean_l)
        denominator += dt * dt
    if denominator == 0:
        return 0.0
    return numerator / denominator * SECONDS_PER_DAY


def estimate_drain(raw_points: Iterable[DrainPoint], current_level: float) -> DrainEstimate | None:
    """Fit the samples and estimate days left, or None when the data is too thin."""
    points = sorted((p for p in raw_points if math.isfinite(p.level)), key=lambda p: as_utc(p.time))
    if len(points) < MIN_SAMPLES:
        return None
    if as_utc(points[-1].time) - as_utc(points[0].time) < MIN_SPAN:
        return None

    rate_per_day = -_slope_per_day(points)
    if rate_per_day < MIN_RATE_PER_DAY:
        return None  # flat, rising or noise

    return DrainEstimate(
        rate_per_day=rate_per_day,
        days_left=max(0.0, current_level / rate_per_day),
        samples=len(points),
    )


def format_days_left(days: float) -> str:
    """Round to a friendly unit: "~12d", "~3w", "~4mo"."""
    if days < 1:
        return "under a day"
    if days < 14:
        return f"~{math.floor(days + 0.5)}d"
    if days < 60:
        return f"~{math.floor(days / 7 + 0.5)}w"
    if days < 365:
        return f"~{math.floor(days / 30 + 0.5)}mo"
    return "1y+"


def rows_to_points(rows: Iterable[Mapping[str, Any]]) -> list[DrainPoint]:
    """Recorder statistics rows (`start` as epoch seconds, `mean`) -> points.

    Rows without a mean (a day with no data) are skipped.
    """
    points: list[DrainPoint] = []
    for row in rows:
        mean = row.get("mean")
        start = row.get("start")
        if mean is None or not isinstance(start, int | float):
            continue
        points.append(DrainPoint(time=datetime.fromtimestamp(start, tz=UTC), level=float(mean)))
    return points


def _means_per(samples: Iterable[tuple[datetime, float | None]], hourly: bool) -> list[DrainPoint]:
    totals: dict[datetime, list[float]] = {}
    for moment, level in samples:
        if level is None or not math.isfinite(level):
            continue
        utc = as_utc(moment)
        bucket = utc.replace(minute=0, second=0, microsecond=0)
        if not hourly:
            bucket = bucket.replace(hour=0)
        totals.setdefault(bucket, []).append(level)
    return [
        DrainPoint(time=bucket, level=sum(levels) / len(levels))
        for bucket, levels in sorted(totals.items())
    ]


def daily_means(samples: Iterable[tuple[datetime, float | None]]) -> list[DrainPoint]:
    """Collapse raw samples into one point per UTC day: the mean of that day.

    This is the shape the statistics API gives us, so sensors without
    statistics can take the same path. Samples without a value
    (unavailable, unknown) are skipped.
    """
    return _means_per(samples, hourly=False)


def hourly_means(samples: Iterable[tuple[datetime, float | None]]) -> list[DrainPoint]:
    """The same per UTC hour, for short sparkline windows."""
    return _means_per(samples, hourly=True)
