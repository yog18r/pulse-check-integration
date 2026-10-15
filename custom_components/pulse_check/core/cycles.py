"""Battery cycles: what a battery's history says about its future.

A battery's history is a saw-tooth: it drains, then it is replaced or
charged and jumps back up. Each tooth is a *cycle*. Cutting the history
into cycles tells us three things a plain straight-line fit cannot:

- what kind of battery it is: one that gets *charged* (a phone, a blind)
  or one that gets *replaced* (a sensor's coin cell);
- how long this device's batteries actually last, from its own past;
- whether the current cycle is draining unusually fast.

Everything here is pure: samples in, facts out. The Home Assistant layer
(history.py) fetches the samples and passes in what it knows from the
registry and the user's settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import median
from typing import TYPE_CHECKING, Literal

from .drain import DrainPoint, estimate_drain
from .models import as_utc

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# A rise of at least this many points within RISE_WINDOW is a charge or a
# new battery: a cycle boundary.
RISE_POINTS = 15
RISE_WINDOW = timedelta(hours=48)
# A single sample at least this far below both of its neighbours is a
# reading glitch (a lock that said 42 % for a day and then 61 % again),
# not a charge. It is dropped before cycles are cut.
GLITCH_POINTS = 15
# A cycle starting at or above this level began with a full battery.
NEAR_FULL = 85
# Batteries whose completed cycles are shorter than this get charged, not replaced.
SHORT_CYCLE_DAYS = 30
# The current cycle must show at least this much decline for a trend fit.
MIN_TREND_DAYS = 7
# A current cycle at least this long that lost less than FLAT_CYCLE_DROP
# points is "more than a year", with low confidence.
FLAT_CYCLE_DAYS = 90
FLAT_CYCLE_DROP = 10
# A fall of this many points within RISE_WINDOW in the last week is sudden.
SUDDEN_DROP_POINTS = 20
RECENT = timedelta(days=7)
# Draining more than this many times faster than the device's own past is unusual.
UNUSUAL_FACTOR = 2.0
# Charge estimates shorter than this are daily chargers: nothing to say.
MIN_CHARGE_DAYS = 1.0

type BatteryKind = Literal["charged", "replaceable", "unknown"]
type Confidence = Literal["high", "medium", "low"]
type EstimateKind = Literal["replace", "charge"]


@dataclass(frozen=True, slots=True)
class Cycle:
    """One tooth of the saw: from a charge or replacement to the next."""

    start: datetime
    end: datetime
    start_level: float
    end_level: float
    points: tuple[DrainPoint, ...]

    @property
    def days(self) -> float:
        """Length in days."""
        return (as_utc(self.end) - as_utc(self.start)).total_seconds() / 86400

    @property
    def drop(self) -> float:
        """Points lost from start to end (negative if it rose)."""
        return self.start_level - self.end_level

    @property
    def rate_per_day(self) -> float | None:
        """Average discharge rate, or None when the cycle did not drain."""
        if self.days <= 0 or self.drop <= 0:
            return None
        return self.drop / self.days


@dataclass(frozen=True, slots=True)
class Estimate:
    """Days left, with where the number came from and how much to trust it."""

    days_left: float
    # Plain words, shown as a tooltip: "trend over current cycle",
    # "from 2 previous cycles of ~220 days", "until charge needed".
    basis: str
    confidence: Confidence
    kind: EstimateKind
    # True for "more than a year": days_left is then a floor, not a prediction.
    open_ended: bool = False
    rate_per_day: float | None = None


@dataclass(frozen=True, slots=True)
class BatteryInsight:
    """Everything the cycles say about one battery."""

    kind: BatteryKind
    estimate: Estimate | None
    completed_cycles: int
    median_cycle_days: float | None
    unusual: str | None


def _ordered(points: Iterable[DrainPoint]) -> list[DrainPoint]:
    return sorted(points, key=lambda p: as_utc(p.time))


def remove_glitches(points: Iterable[DrainPoint]) -> list[DrainPoint]:
    """Drop lone samples far below both neighbours: a bad reading, not a cycle."""
    ordered = _ordered(points)
    if len(ordered) < 3:
        return ordered
    kept: list[DrainPoint] = [ordered[0]]
    for earlier, point, later in zip(ordered, ordered[1:], ordered[2:], strict=False):
        glitch = (
            earlier.level - point.level >= GLITCH_POINTS
            and later.level - point.level >= GLITCH_POINTS
        )
        if not glitch:
            kept.append(point)
    kept.append(ordered[-1])
    return kept


def segment_cycles(
    points: Iterable[DrainPoint], boundaries: Iterable[datetime] = ()
) -> list[Cycle]:
    """Cut the samples into cycles.

    A new cycle starts at a rise of `RISE_POINTS` or more within
    `RISE_WINDOW`, and at every explicit boundary (a mark_replaced or
    mark_charged call, a charging signal turning on). The last cycle is
    the current, open one.
    """
    ordered = remove_glitches(points)
    if not ordered:
        return []
    marks = sorted(as_utc(b) for b in boundaries)
    segments: list[list[DrainPoint]] = [[ordered[0]]]
    for earlier, later in pairwise(ordered):
        t0, t1 = as_utc(earlier.time), as_utc(later.time)
        rose = later.level - earlier.level >= RISE_POINTS and t1 - t0 <= RISE_WINDOW
        marked = any(t0 < mark <= t1 for mark in marks)
        if rose or marked:
            segments.append([later])
        else:
            segments[-1].append(later)
    return [
        Cycle(
            start=seg[0].time,
            end=seg[-1].time,
            start_level=seg[0].level,
            end_level=seg[-1].level,
            points=tuple(seg),
        )
        for seg in segments
    ]


def classify_battery(
    cycles: Sequence[Cycle],
    *,
    mobile_app: bool = False,
    rechargeable: bool = False,
    charging_signal: bool = False,
) -> BatteryKind:
    """Charged, replaceable, or unknown.

    Charged: the user said so, it is a phone, it has shown a charging
    signal, or its completed cycles are short (median under 30 days).
    Replaceable: every cycle so far began near full, which is what a fresh
    cell looks like. Anything else is unknown, and gets no estimate.
    """
    if mobile_app or rechargeable or charging_signal:
        return "charged"
    completed = cycles[:-1]
    if len(completed) >= 2 and median(c.days for c in completed) < SHORT_CYCLE_DAYS:
        return "charged"
    if all(c.start_level >= NEAR_FULL for c in cycles[1:]):
        return "replaceable"
    return "unknown"


def estimate_replaceable(cycles: Sequence[Cycle], level: float) -> Estimate | None:
    """Days until a replaceable battery is empty.

    1. The current cycle's own trend, once it spans a week of decline.
    2. Else the device's completed cycles: how many days they lasted per
       100 points, scaled to the current level.
    3. Else a long flat cycle is "more than a year", low confidence.
    4. Else nothing.
    """
    if not cycles:
        return None
    current = cycles[-1]
    if current.days >= MIN_TREND_DAYS:
        fit = estimate_drain(current.points, level)
        if fit is not None:
            return Estimate(
                days_left=fit.days_left,
                basis="trend over current cycle",
                confidence="high" if fit.samples >= 14 else "medium",
                kind="replace",
                rate_per_day=fit.rate_per_day,
            )
    completed = [c for c in cycles[:-1] if c.drop > 0 and c.days >= 1]
    if completed:
        days_per_100 = median(c.days * 100 / c.drop for c in completed)
        typical = median(c.days for c in completed)
        plural = "cycle" if len(completed) == 1 else "cycles"
        return Estimate(
            days_left=days_per_100 * level / 100,
            basis=f"from {len(completed)} previous {plural} of ~{typical:.0f} days",
            confidence="medium" if len(completed) >= 2 else "low",
            kind="replace",
            rate_per_day=100 / days_per_100,
        )
    if current.days >= FLAT_CYCLE_DAYS and current.drop < FLAT_CYCLE_DROP:
        return Estimate(
            days_left=365,
            basis=f"flat for {current.days:.0f} days",
            confidence="low",
            kind="replace",
            open_ended=True,
        )
    return None


def estimate_charged(
    current_points: Sequence[DrainPoint], level: float, warning: float
) -> Estimate | None:
    """Days until a charged battery reaches the warning level.

    Fitted over the samples since the last charge. A device charged every
    day never spans enough to fit, and anything under a day is suppressed:
    nobody needs to be told their phone wants charging tonight.
    """
    if level <= warning:
        return None
    fit = estimate_drain(current_points, level)
    if fit is None:
        return None
    days = (level - warning) / fit.rate_per_day
    if days < MIN_CHARGE_DAYS:
        return None
    return Estimate(
        days_left=days,
        basis="until charge needed",
        confidence="medium" if fit.samples >= 24 else "low",
        kind="charge",
        rate_per_day=fit.rate_per_day,
    )


def unusual_behaviour(cycles: Sequence[Cycle], now: datetime) -> str | None:
    """A note when the current cycle drains far faster than before, or dropped suddenly."""
    if not cycles:
        return None
    current = cycles[-1]
    past = [c.rate_per_day for c in cycles[:-1] if c.rate_per_day is not None]
    rate = current.rate_per_day
    if rate is not None and past:
        typical = median(past)
        if typical > 0 and rate > UNUSUAL_FACTOR * typical:
            return f"draining {rate / typical:.0f}× faster than usual"
    recent = as_utc(now) - RECENT
    for earlier, later in pairwise(current.points):
        t0, t1 = as_utc(earlier.time), as_utc(later.time)
        if (
            t1 >= recent
            and t1 - t0 <= RISE_WINDOW
            and earlier.level - later.level >= SUDDEN_DROP_POINTS
            and later.level > 0
        ):
            return "level dropped suddenly"
    return None


def assess(
    daily: Iterable[DrainPoint],
    hourly: Iterable[DrainPoint],
    level: float,
    now: datetime,
    *,
    warning: float,
    mobile_app: bool = False,
    rechargeable: bool = False,
    charging_signal: bool = False,
    marks: Iterable[datetime] = (),
) -> BatteryInsight:
    """The whole picture for one battery, from its history and what we know about it."""
    live = DrainPoint(time=now, level=level)
    marks = tuple(marks)
    cycles = segment_cycles([*daily, live], marks)
    kind = classify_battery(
        cycles, mobile_app=mobile_app, rechargeable=rechargeable, charging_signal=charging_signal
    )
    estimate: Estimate | None = None
    if kind == "replaceable":
        estimate = estimate_replaceable(cycles, level)
    elif kind == "charged":
        fine = segment_cycles([*hourly, live], marks)
        if fine:
            estimate = estimate_charged(fine[-1].points, level, warning)
    completed = cycles[:-1]
    return BatteryInsight(
        kind=kind,
        estimate=estimate,
        completed_cycles=len(completed),
        median_cycle_days=median(c.days for c in completed) if completed else None,
        unusual=unusual_behaviour(cycles, now),
    )
