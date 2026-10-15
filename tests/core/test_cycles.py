"""Cycles, battery kinds and estimates, over synthetic histories.

Each scenario is one of the specification cases: a lock with a single
dip-and-recover, a lock with two completed replacement cycles, a phone
charged nightly, a blind charged every two months, and a sensor that has
sat flat for four months.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pulse_check.core.cycles import (
    assess,
    classify_battery,
    estimate_replaceable,
    remove_glitches,
    segment_cycles,
)
from custom_components.pulse_check.core.drain import DrainPoint

NOW = datetime(2026, 10, 15, 10, tzinfo=UTC)
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


def daily(days: int, start: float, per_day: float, end: datetime = NOW) -> list[DrainPoint]:
    """One sample per day ending yesterday, draining `per_day` points a day."""
    return [DrainPoint(time=end - (days - i) * DAY, level=start - i * per_day) for i in range(days)]


def hourly(hours: int, start: float, per_hour: float, end: datetime = NOW) -> list[DrainPoint]:
    return [
        DrainPoint(time=end - (hours - i) * HOUR, level=start - i * per_hour) for i in range(hours)
    ]


# --- a lock: one dip-and-recover glitch, still estimated -------------------


def test_a_single_dip_and_recover_is_a_glitch_not_a_cycle() -> None:
    history = daily(30, 70, 0.3)  # 70 % down to 61 % over a month
    history[20] = DrainPoint(time=history[20].time, level=42)  # one bad reading
    assert len(remove_glitches(history)) == 29
    cycles = segment_cycles([*history, DrainPoint(time=NOW, level=61)])
    assert len(cycles) == 1

    insight = assess(history, [], 61, NOW, warning=30)
    assert insight.kind == "replaceable"
    assert insight.estimate is not None
    assert insight.estimate.basis == "trend over current cycle"
    assert insight.estimate.confidence == "high"
    assert insight.estimate.days_left == pytest.approx(61 / 0.3, rel=0.1)
    assert insight.unusual is None


# --- a lock with two completed replacement cycles ---------------------------


def test_two_replacement_cycles_predict_the_next_one() -> None:
    first_end = NOW - 243 * DAY
    second_end = NOW - 3 * DAY
    first = daily(200, 100, 0.4, end=first_end)  # 100 -> 20 over 200 days
    second = daily(240, 100, 0.35, end=second_end)  # 100 -> 16 over 240 days
    fresh = daily(3, 100, 1, end=NOW)  # a new cell, three days in: too short to fit
    history = [*first, *second, *fresh]

    cycles = segment_cycles([*history, DrainPoint(time=NOW, level=97)])
    assert [round(c.start_level) for c in cycles] == [100, 100, 100]
    assert [round(c.days) for c in cycles][:2] == [199, 239]
    assert classify_battery(cycles) == "replaceable"

    insight = assess(history, [], 97, NOW, warning=30)
    assert insight.completed_cycles == 2
    assert insight.median_cycle_days == pytest.approx(219, abs=2)
    assert insight.estimate is not None
    assert insight.estimate.kind == "replace"
    assert insight.estimate.basis == "from 2 previous cycles of ~219 days"
    assert insight.estimate.confidence == "medium"
    # ~250 and ~286 days per 100 points: median ~268, at 97 % about 260 days.
    assert insight.estimate.days_left == pytest.approx(260, abs=10)


def test_the_current_cycle_wins_once_it_has_a_week_of_decline() -> None:
    previous = daily(200, 100, 0.4, end=NOW - 20 * DAY)
    current = daily(20, 100, 2, end=NOW)  # draining five times faster than before
    insight = assess([*previous, *current], [], 60, NOW, warning=30)
    assert insight.estimate is not None
    assert insight.estimate.basis == "trend over current cycle"
    assert insight.estimate.days_left == pytest.approx(30, rel=0.1)
    assert insight.unusual == "draining 5× faster than usual"


# --- a phone charged nightly: no estimate -----------------------------------


def test_a_phone_charged_every_night_gets_nothing() -> None:
    history: list[DrainPoint] = []
    for day in range(14, 0, -1):
        for hour in range(24):
            # 100 % at 7 am, 2 points an hour, charged overnight.
            level = max(100 - 2 * ((hour - 7) % 24), 40)
            history.append(DrainPoint(time=NOW - day * DAY + hour * HOUR, level=level))
    means = [DrainPoint(time=NOW - d * DAY, level=70) for d in range(14, 0, -1)]
    insight = assess(means, history, 70, NOW, warning=30, mobile_app=True)
    assert insight.kind == "charged"
    assert insight.estimate is None

    # Even without the mobile_app hint, the short cycles give it away.
    cycles = segment_cycles(history)
    assert len(cycles) >= 10
    assert classify_battery(cycles) == "charged"


# --- a blind charged every 60 days: "charge in ~N days" ----------------------


def test_a_blind_charged_every_two_months_gets_a_charge_estimate() -> None:
    history: list[DrainPoint] = []
    for cycle_end in (NOW - 120 * DAY, NOW - 60 * DAY):
        history += daily(60, 100, 1.1, end=cycle_end)  # 100 % down to ~35 %
    history += daily(60, 100, 1.1, end=NOW)  # the current cycle, 60 days in: ~35 %
    fine = hourly(14 * 24, 49, 1.1 / 24, end=NOW)  # hourly means over the last fortnight

    cycles = segment_cycles([*history, DrainPoint(time=NOW, level=34)])
    assert len(cycles) == 3
    # Rechargeable is the user's call (or a charging signal); the cycles
    # alone look like replacements.
    assert classify_battery(cycles) == "replaceable"
    insight = assess(history, fine, 34, NOW, warning=30, rechargeable=True)
    assert insight.kind == "charged"
    assert insight.estimate is not None
    assert insight.estimate.kind == "charge"
    assert insight.estimate.basis == "until charge needed"
    assert insight.estimate.days_left == pytest.approx((34 - 30) / 1.1, rel=0.1)


# --- a sensor flat for four months: "more than a year", low confidence -------


def test_a_flat_sensor_is_more_than_a_year_with_low_confidence() -> None:
    history = daily(120, 100, 0.05)  # 100 % down to 94 % in four months
    insight = assess(history, [], 94, NOW, warning=30)
    assert insight.kind == "replaceable"
    assert insight.estimate is not None
    assert insight.estimate.open_ended is True
    assert insight.estimate.confidence == "low"
    assert insight.estimate.days_left == 365
    assert insight.estimate.basis == "flat for 120 days"


# --- edge cases -------------------------------------------------------------


def test_marks_start_a_cycle_without_a_visible_rise() -> None:
    history = daily(30, 60, 1)  # 60 % down to 31 %; the sensor still reads the old level
    mark = NOW - 2 * DAY  # mark_replaced two days ago
    cycles = segment_cycles([*history, DrainPoint(time=NOW, level=29)], [mark])
    assert len(cycles) == 2
    assert cycles[1].days == pytest.approx(2, abs=0.1)


def test_a_rise_that_does_not_land_near_full_is_unknown() -> None:
    history = [
        *daily(20, 60, 1, end=NOW - 10 * DAY),
        *daily(10, 65, 1),
    ]  # 41 % -> 65 %: partial top-up
    assert assess(history, [], 56, NOW, warning=30).kind == "unknown"
    assert estimate_replaceable([], 50) is None


def test_no_history_means_no_estimate() -> None:
    insight = assess([], [], 50, NOW, warning=30)
    assert insight.kind == "replaceable"  # one point, no rises: nothing contradicts it
    assert insight.estimate is None
    assert insight.unusual is None
