"""Batteries charged every day, and estimates that say "more than a year".

The shapes come from a real home: a phone drained from 100 % each day and
charged at night, a home battery charged by solar at about 10 points an
hour and drained overnight, and door locks whose level wobbles a few
points with use and temperature.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pulse_check.core.cycles import (
    OPEN_ENDED_DAYS,
    Charge,
    assess,
    find_charges,
    since_last_charge,
)
from custom_components.pulse_check.core.drain import DrainPoint

NOW = datetime(2026, 11, 8, 12, 30, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def home_battery(days: int = 7, low: float = 45) -> list[DrainPoint]:
    """Hourly means: charged 10 points an hour to 100 %, then drained to `low` overnight."""
    points: list[DrainPoint] = []
    start = NOW - days * DAY
    level = low
    for hour in range(days * 24):
        at = start + hour * HOUR
        local = hour % 24
        if local < 6:  # charging from solar, 10 points an hour
            level = min(100.0, level + 10)
        elif local < 9:  # full while the sun is up
            level = 100.0
        else:  # the evening and the night
            level = max(low, level - (100 - low) / 15)
        points.append(DrainPoint(time=at, level=level))
    return points


def test_a_slow_charge_is_one_charge() -> None:
    """Ten points an hour never rises 15 between two samples, but is still a charge."""
    charges = find_charges(home_battery(days=7))
    assert len(charges) == 7
    assert all(c.peak.level == 100 for c in charges)


def test_a_home_battery_is_charged_whatever_the_hour() -> None:
    """Daily means are flat for a battery charged every day; the hourly history is not."""
    hourly = home_battery(days=14)
    flat_means = [DrainPoint(time=NOW - d * DAY, level=70) for d in range(14, 0, -1)]
    for hours_back in range(0, 24, 3):
        now = NOW - hours_back * HOUR
        seen = [p for p in hourly if p.time <= now]
        insight = assess(flat_means, seen, seen[-1].level, now, warning=30)
        assert insight.kind == "charged", f"{hours_back} h back"


def test_a_home_battery_that_never_runs_low_reports_its_usual_low_only() -> None:
    """Topped up by solar from about 47 % every day: never near the 30 % warning."""
    hourly = home_battery(days=14, low=47)
    flat_means = [DrainPoint(time=NOW - d * DAY, level=70) for d in range(14, 0, -1)]
    insight = assess(flat_means, hourly, hourly[-1].level, NOW, warning=30)
    assert insight.kind == "charged"
    assert insight.usual_low == pytest.approx(47)
    # "Charge in ~6h" would forecast a fall to 30 % that never happens.
    assert insight.estimate is None


def test_a_home_battery_that_reaches_the_warning_level_gets_hours() -> None:
    # Mid-evening: 65 %, draining 5 points an hour to a low of 25 %.
    hourly = home_battery(days=14, low=25)[:-8]
    now, level = hourly[-1].time, hourly[-1].level
    flat_means = [DrainPoint(time=now - d * DAY, level=60) for d in range(14, 0, -1)]
    insight = assess(flat_means, hourly, level, now, warning=30)
    assert insight.estimate is not None
    assert insight.estimate.kind == "charge"
    # 65 % down to 30 % at 5 points an hour: about 7 hours.
    assert 5 < insight.estimate.days_left * 24 < 9


def flat(level: float, hours: int = 336) -> list[DrainPoint]:
    return [DrainPoint(time=NOW - (hours - h) * HOUR, level=level) for h in range(hours)]


def test_a_dip_lasting_hours_that_comes_back_is_not_a_charge() -> None:
    """A lock reading 42 % for three hourly means, then 61 % again, twice."""
    hourly = flat(61)
    for start in (100, 250):
        for h in range(start, start + 3):
            hourly[h] = DrainPoint(time=hourly[h].time, level=42)
    assert find_charges(hourly) == []
    means = [DrainPoint(time=NOW - d * DAY, level=61) for d in range(30, 0, -1)]
    assert assess(means, hourly, 61, NOW, warning=30).kind != "charged"


def test_a_spike_lasting_hours_that_drops_back_is_not_a_charge() -> None:
    """A rejoining device reporting 100 % until its next report three hours later, twice."""
    hourly = flat(60)
    for start in (100, 250):
        for h in range(start, start + 3):
            hourly[h] = DrainPoint(time=hourly[h].time, level=100)
    assert find_charges(hourly) == []


def test_no_estimate_while_charging_again() -> None:
    """Rising from its low: the old discharge says nothing about now."""
    hourly = home_battery(days=7, low=20)
    # The last few hours: a new charge under way, not yet complete.
    rising = [DrainPoint(time=NOW + h * HOUR, level=20 + 8 * (h + 1)) for h in range(2)]
    now = rising[-1].time
    flat_means = [DrainPoint(time=now - d * DAY, level=60) for d in range(7, 0, -1)]
    insight = assess(flat_means, [*hourly, *rising], rising[-1].level, now, warning=30)
    assert insight.kind == "charged"
    assert insight.estimate is None


def test_the_discharge_is_measured_after_the_full_plateau() -> None:
    """Held at 100 % for hours after charging: the fit starts when it begins to fall."""
    points = [DrainPoint(time=NOW - (10 - h) * HOUR, level=100) for h in range(4)]
    points += [DrainPoint(time=NOW - (6 - h) * HOUR, level=96 - 4 * h) for h in range(7)]
    charge = Charge(low=DrainPoint(time=NOW - 14 * HOUR, level=30), peak=points[0])
    segment = since_last_charge(points, [charge])
    assert segment[0].level == 100
    assert segment[1].level == 96  # the plateau's other samples are skipped


def test_a_mark_after_a_small_top_up_starts_the_discharge_again() -> None:
    points = [DrainPoint(time=NOW - (12 - h) * HOUR, level=90 - h) for h in range(13)]
    charge = Charge(low=DrainPoint(time=NOW - 30 * HOUR, level=30), peak=points[0])
    mark = NOW - 4 * HOUR
    segment = since_last_charge(points, [charge], [mark])
    assert segment[0].time >= mark


def test_lone_high_readings_do_not_make_a_lock_charged() -> None:
    """A Zigbee lock saying 100 % once as it rejoins, twice in a fortnight."""
    hourly = [DrainPoint(time=NOW - (336 - h) * HOUR, level=60) for h in range(336)]
    for spike in (100, 250):
        hourly[spike] = DrainPoint(time=hourly[spike].time, level=100)
    assert find_charges(hourly) == []
    means = [DrainPoint(time=NOW - d * DAY, level=60) for d in range(30, 0, -1)]
    assert assess(means, hourly, 60, NOW, warning=30).kind != "charged"


def test_a_trend_beyond_a_year_reads_as_more_than_a_year() -> None:
    """A lock losing 0.15 points a day from 93 %: the fit says ~600 days."""
    means = [DrainPoint(time=NOW - d * DAY, level=93 - 0.15 * (30 - d)) for d in range(30, 0, -1)]
    insight = assess(means, [], 88.5, NOW, warning=30)
    assert insight.kind == "replaceable"
    estimate = insight.estimate
    assert estimate is not None
    assert estimate.open_ended
    assert estimate.days_left == OPEN_ENDED_DAYS
