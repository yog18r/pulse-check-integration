"""Battery cycles: what a battery's history says about its future.

A battery's history is a saw-tooth: it drains, then it is replaced or
charged and jumps back up. Each tooth is a *cycle*. Cutting the history
into cycles tells us three things a plain straight-line fit cannot:

- what kind of battery it is: one that gets *charged* (a phone, a blind)
  or one that gets *replaced* (a sensor's coin cell);
- how long this device's batteries actually last, from its own past;
- whether a replaceable battery's current cycle is draining unusually fast.

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

from .drain import MIN_SPAN, DrainPoint, estimate_drain
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
# When the fit has nothing to say (too slow, too few samples), a cycle at
# least this long that lost at least this many points still gives a rough,
# low-confidence number from the drop over the span.
SLOW_DRAIN_DAYS = 14
SLOW_DRAIN_POINTS = 1
# Estimates beyond this are reported as "more than a year", open-ended.
OPEN_ENDED_DAYS = 365
# A current cycle at least this long that lost less than FLAT_CYCLE_DROP
# points is "more than a year", with low confidence.
FLAT_CYCLE_DAYS = 90
FLAT_CYCLE_DROP = 10
# A fall of this many points within RISE_WINDOW in the last week is sudden.
SUDDEN_DROP_POINTS = 20
RECENT = timedelta(days=7)
# Draining more than this many times faster than the device's own past is unusual.
UNUSUAL_FACTOR = 2.0
# Cycles compared for unusual drain must span at least this long: a few
# hours of use say nothing about how fast a battery drains.
MIN_COMPARE_DAYS = 2.0
# A charge is a rise of RISE_POINTS from a low within RISE_WINDOW, found
# in the hourly history: a home battery charging 10 points an hour never
# rises 15 between two samples, but does from where it started. After a
# charge, the level must fall this far below its peak before the next
# rise counts, so one long charge is one charge.
REARM_POINTS = 5
# A charge stays up: at least this many samples at or above the rise.
MIN_CHARGE_SAMPLES = 2
# This many charges in the hourly history (a fortnight) make a battery one
# that gets charged, whatever its daily means say.
FREQUENT_CHARGES = 2
# The usual low: the median level before the most recent charges.
USUAL_LOW_CHARGES = 7
# A battery charged that often drains in hours, so its discharge since the
# last charge is worth a fit once it covers this long.
MIN_DISCHARGE_SPAN = timedelta(hours=3)

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
class Charge:
    """One charge: the low it started from and the peak it reached."""

    low: DrainPoint
    peak: DrainPoint


@dataclass(frozen=True, slots=True)
class BatteryInsight:
    """Everything the cycles say about one battery."""

    kind: BatteryKind
    estimate: Estimate | None
    completed_cycles: int
    median_cycle_days: float | None
    unusual: str | None
    # For a battery charged often: the level it usually falls to before a
    # charge (the median of the last few lows, from hourly means, so a few
    # points above the very lowest reading).
    usual_low: float | None = None


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


def find_charges(points: Iterable[DrainPoint]) -> list[Charge]:
    """Every charge in the samples: a rise of RISE_POINTS from a low within RISE_WINDOW.

    Unlike a cycle boundary, the rise may be spread over many samples, as
    a home battery's is. One charge ends once the level has fallen
    REARM_POINTS below its peak; a charge still at its peak counts too.
    A real charge stays up for more than one sample: a lone high reading
    (a Zigbee device saying 100 % once as it rejoins) is not one.

    Nor is a reading glitch that lasts a few hours, as one does in hourly
    means until the device next reports: a sudden fall that comes back to
    where it was (a lock reading 42 % for three hours, then 61 % again),
    or a sudden rise that drops straight back (100 % for three hours,
    then 60 % again). A real charge climbs well above where the battery
    was before it ran down, and drains away gradually.
    """
    charges: list[Charge] = []
    low: DrainPoint | None = None
    # The level before a sudden fall to the current low, if it fell suddenly.
    fell_from: float | None = None
    start: DrainPoint | None = None  # the low of the charge under way
    start_fell_from: float | None = None
    peak: DrainPoint | None = None
    high = 0  # samples of the charge under way that stayed risen
    previous: DrainPoint | None = None

    def keep(dropped_back_to: DrainPoint | None) -> bool:
        """Whether the charge under way was real, not a glitch."""
        assert start is not None and peak is not None
        if high < MIN_CHARGE_SAMPLES:
            return False
        if start_fell_from is not None and peak.level - start_fell_from <= REARM_POINTS:
            return False  # a dip that came back to where it was
        return not (
            dropped_back_to is not None and dropped_back_to.level - start.level <= REARM_POINTS
        )  # a spike that dropped straight back

    for point in remove_glitches(points):
        sudden_fall = previous is not None and previous.level - point.level >= GLITCH_POINTS
        if start is not None and peak is not None:
            if point.level - start.level >= RISE_POINTS:
                high += 1
            if point.level >= peak.level:
                peak = point
            elif peak.level - point.level >= REARM_POINTS:
                if keep(point if sudden_fall else None):
                    charges.append(Charge(low=start, peak=peak))
                start = peak = None
                # The new low may itself be the bottom of a sudden dip.
                low = point
                fell_from = previous.level if sudden_fall and previous is not None else None
        else:
            stale = low is not None and as_utc(point.time) - as_utc(low.time) > RISE_WINDOW
            if low is None or point.level <= low.level or stale:
                if sudden_fall and previous is not None:
                    fell_from = previous.level
                elif low is None or stale or abs(point.level - low.level) > 1:
                    fell_from = None  # a gradual decline, not a dip
                low = point
            elif point.level - low.level >= RISE_POINTS:
                start, start_fell_from, peak, high = low, fell_from, point, 1
        previous = point
    if start is not None and peak is not None and keep(None):
        charges.append(Charge(low=start, peak=peak))
    return charges


def classify_battery(
    cycles: Sequence[Cycle],
    *,
    mobile_app: bool = False,
    rechargeable: bool = False,
    charging_signal: bool = False,
    frequent_charges: bool = False,
) -> BatteryKind:
    """Charged, replaceable, or unknown.

    Charged: the user said so, it is a phone or a robot vacuum, it has shown a charging
    signal, its hourly history shows it charged at least twice, or its
    completed cycles are short (median under 30 days). Daily means alone
    cannot see a daily charge: every day averages out the same.
    Replaceable: every cycle so far began near full, which is what a fresh
    cell looks like. Anything else is unknown, and gets no estimate.
    """
    if mobile_app or rechargeable or charging_signal or frequent_charges:
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
    2. Else the drop over the current cycle, once it spans a fortnight and
       has lost a point: low confidence, "more than a year" when it says
       so. A long cycle that lost under ten points is reported as flat.
    3. Else the device's completed cycles: how many days they lasted per
       100 points, scaled to the current level.
    4. Else nothing.
    """
    if not cycles:
        return None
    current = cycles[-1]
    if current.days >= MIN_TREND_DAYS:
        fit = estimate_drain(current.points, level)
        if fit is not None:
            # Beyond a year a fit is as uncertain as any other way of
            # saying so, and reads the same: "more than a year".
            return Estimate(
                days_left=min(fit.days_left, OPEN_ENDED_DAYS),
                open_ended=fit.days_left > OPEN_ENDED_DAYS,
                basis="trend over current cycle",
                confidence="high" if fit.samples >= 14 else "medium",
                kind="replace",
                rate_per_day=fit.rate_per_day,
            )
    if current.days >= FLAT_CYCLE_DAYS and current.drop < FLAT_CYCLE_DROP:
        return Estimate(
            days_left=OPEN_ENDED_DAYS,
            basis=f"flat for {current.days:.0f} days",
            confidence="low",
            kind="replace",
            open_ended=True,
        )
    if current.days >= SLOW_DRAIN_DAYS and current.drop >= SLOW_DRAIN_POINTS:
        rate = current.drop / current.days
        days_left = level / rate
        return Estimate(
            days_left=min(days_left, OPEN_ENDED_DAYS),
            basis=f"slow drain over {current.days:.0f} days",
            confidence="low",
            kind="replace",
            open_ended=days_left > OPEN_ENDED_DAYS,
            rate_per_day=rate,
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
    return None


def estimate_charged(
    current_points: Sequence[DrainPoint],
    level: float,
    warning: float,
    *,
    min_span: timedelta | None = None,
) -> Estimate | None:
    """Days (often a fraction of one) until a charged battery reaches the warning level.

    Fitted over the samples since the last charge. For a battery charged
    every day, `min_span` is a few hours and the answer is in hours; the
    card shows it, and nothing is ever notified from it.
    """
    if level <= warning:
        return None
    fit = estimate_drain(current_points, level, min_span or MIN_SPAN)
    if fit is None:
        return None
    return Estimate(
        days_left=(level - warning) / fit.rate_per_day,
        basis="until charge needed",
        confidence="medium" if fit.samples >= 24 else "low",
        kind="charge",
        rate_per_day=fit.rate_per_day,
    )


def since_last_charge(
    points: Sequence[DrainPoint], charges: Sequence[Charge], marks: Sequence[datetime] = ()
) -> list[DrainPoint]:
    """The discharge since the latest charge; empty while it is charging again.

    It starts at the later of the latest charge's peak and the latest
    mark (a mark_charged after a small top-up), then skips the flat top a
    battery sits at while it is still being topped up or held full. If
    the level has since risen again, a new charge is under way and there
    is no discharge to measure.
    """
    begin = as_utc(charges[-1].peak.time) if charges else None
    for mark in marks:
        if begin is None or as_utc(mark) > begin:
            begin = as_utc(mark)
    segment = [p for p in points if begin is None or as_utc(p.time) >= begin]
    if not segment:
        return []
    top = segment[0].level
    while len(segment) > 1 and segment[1].level >= top - 1:
        segment = segment[1:]
    lowest = min(p.level for p in segment)
    if segment[-1].level - lowest >= REARM_POINTS:
        return []  # charging again
    return segment


def _span_rate(points: Sequence[DrainPoint]) -> float | None:
    """Points lost per day from first sample to last, over at least MIN_COMPARE_DAYS."""
    if len(points) < 2:
        return None
    first, last = points[0], points[-1]
    days = (as_utc(last.time) - as_utc(first.time)).total_seconds() / 86400
    drop = first.level - last.level
    if days < MIN_COMPARE_DAYS or drop <= 0:
        return None
    return drop / days


def unusual_behaviour(
    cycles: Sequence[Cycle], now: datetime, kind: BatteryKind = "replaceable"
) -> str | None:
    """A note when a replaceable battery drains far faster than before, or dropped suddenly.

    Only replaceable batteries are judged. A charged battery's cycles last
    a day or so, and daily means smooth its charge and discharge away, so
    a comparison says nothing ("draining 40× faster" for a phone that has
    been in use since breakfast).

    The rates compared are like for like: start to end of the daily
    series, for the current cycle and each past one, each spanning at
    least `MIN_COMPARE_DAYS`. The live reading is left out of the current
    rate: it is one instant, where the rest are daily means.
    """
    if kind != "replaceable" or not cycles:
        return None
    current = cycles[-1]
    past = [rate for c in cycles[:-1] if (rate := _span_rate(c.points)) is not None]
    rate = _span_rate([p for p in current.points if as_utc(p.time) < as_utc(now)])
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
    fine_points = remove_glitches([*hourly, live])
    charges = find_charges(fine_points)
    frequent = len(charges) >= FREQUENT_CHARGES
    lows = [c.low.level for c in charges[-USUAL_LOW_CHARGES:]]
    usual_low = median(lows) if frequent else None
    cycles = segment_cycles([*daily, live], marks)
    kind = classify_battery(
        cycles,
        mobile_app=mobile_app,
        rechargeable=rechargeable,
        charging_signal=charging_signal,
        frequent_charges=frequent,
    )
    estimate: Estimate | None = None
    if kind == "replaceable":
        estimate = estimate_replaceable(cycles, level)
    elif kind == "charged" and frequent and min(lows) > warning:
        # Charged often and not once run down to the warning level lately (a
        # home battery topped up by solar every day): a time to the warning
        # level would forecast something that does not happen. The usual low
        # says what does.
        estimate = None
    elif kind == "charged" and (charges or marks):
        estimate = estimate_charged(
            since_last_charge(fine_points, charges, marks),
            level,
            warning,
            min_span=MIN_DISCHARGE_SPAN if frequent else None,
        )
    elif kind == "charged":
        fine = segment_cycles(fine_points, marks)
        if fine:
            estimate = estimate_charged(fine[-1].points, level, warning)
    completed = cycles[:-1]
    return BatteryInsight(
        kind=kind,
        estimate=estimate,
        completed_cycles=len(completed),
        median_cycle_days=median(c.days for c in completed) if completed else None,
        unusual=unusual_behaviour(cycles, now, kind),
        usual_low=usual_low,
    )
