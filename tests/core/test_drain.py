"""Tests for drain estimation, ported from the card's drain.test.ts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.pulse_check.core.drain import (
    DrainPoint,
    daily_means,
    estimate_drain,
    format_days_left,
    has_charge_cycles,
    rows_to_points,
)

T0 = datetime(2026, 10, 1, tzinfo=UTC)
DAY = timedelta(days=1)


def series(days: int, start: float, per_day: float) -> list[DrainPoint]:
    """Daily samples from a starting level and a per-day change."""
    return [DrainPoint(time=T0 + i * DAY, level=start + i * per_day) for i in range(days)]


def test_fits_a_clean_linear_drain() -> None:
    # 90 % dropping 2 %/day for 10 days -> now at 72 %
    estimate = estimate_drain(series(10, 90, -2), 72)
    assert estimate is not None
    assert estimate.rate_per_day == pytest.approx(2)
    assert estimate.days_left == pytest.approx(36)
    assert estimate.samples == 10


def test_copes_with_noisy_samples() -> None:
    noisy = [
        DrainPoint(time=p.time, level=p.level + (0.6 if i % 2 else -0.6))
        for i, p in enumerate(series(14, 80, -1))
    ]
    estimate = estimate_drain(noisy, 67)
    assert estimate is not None
    assert 0.8 < estimate.rate_per_day < 1.2


def test_refuses_thin_or_short_data() -> None:
    assert estimate_drain(series(2, 90, -2), 86) is None  # too few samples
    one_day = [
        DrainPoint(time=T0, level=90),
        DrainPoint(time=T0 + DAY / 2, level=89),
        DrainPoint(time=T0 + DAY, level=88),
    ]
    assert estimate_drain(one_day, 88) is None  # spans only 1 day


def test_no_estimate_for_flat_rising_or_charging() -> None:
    assert estimate_drain(series(10, 50, 0), 50) is None
    assert estimate_drain(series(10, 50, 3), 80) is None
    assert estimate_drain(series(10, 50, -0.05), 49.5) is None  # below the noise floor


def test_ignores_garbage_points_and_unsorted_input() -> None:
    points = list(reversed(series(6, 60, -1)))
    points.append(DrainPoint(time=T0, level=float("nan")))
    estimate = estimate_drain(points, 55)
    assert estimate is not None
    assert estimate.samples == 6
    assert estimate.rate_per_day == pytest.approx(1)


def test_never_returns_negative_days_left() -> None:
    estimate = estimate_drain(series(5, 10, -2), 0)
    assert estimate is not None
    assert estimate.days_left == 0


def test_has_charge_cycles_spots_a_refill_between_samples() -> None:
    assert has_charge_cycles(series(10, 90, -2)) is False
    # A phone: 80, 60, 40, charged overnight back to 95, 75...
    phone = [
        DrainPoint(time=T0, level=80),
        DrainPoint(time=T0 + DAY, level=60),
        DrainPoint(time=T0 + 2 * DAY, level=40),
        DrainPoint(time=T0 + 3 * DAY, level=95),
        DrainPoint(time=T0 + 4 * DAY, level=75),
    ]
    assert has_charge_cycles(phone) is True
    # Order of the input does not matter.
    assert has_charge_cycles(list(reversed(phone))) is True
    # A small wobble is not a charge.
    assert has_charge_cycles([*series(5, 50, -1), DrainPoint(time=T0 + 5 * DAY, level=52)]) is False


def test_format_days_left_rounds_to_a_friendly_unit() -> None:
    assert format_days_left(0.4) == "under a day"
    assert format_days_left(3.6) == "~4d"
    assert format_days_left(20) == "~3w"
    assert format_days_left(100) == "~3mo"
    assert format_days_left(900) == "1y+"


def test_rows_to_points_reads_recorder_statistics() -> None:
    rows: list[dict[str, Any]] = [
        {"start": T0.timestamp(), "mean": 80.0},
        {"start": (T0 + DAY).timestamp(), "mean": None},  # a day without data
        {"start": (T0 + 2 * DAY).timestamp(), "mean": 78.5},
    ]
    assert rows_to_points(rows) == [
        DrainPoint(time=T0, level=80.0),
        DrainPoint(time=T0 + 2 * DAY, level=78.5),
    ]


def test_daily_means_collapses_raw_history_per_utc_day() -> None:
    samples = [
        (T0 + timedelta(hours=1), 90.0),
        (T0 + timedelta(hours=13), 88.0),
        (T0 + timedelta(hours=20), None),  # unavailable
        (T0 + DAY + timedelta(hours=3), 85.0),
        (T0 - DAY, 95.0),  # out of order: still lands on its own day
    ]
    assert daily_means(samples) == [
        DrainPoint(time=T0 - DAY, level=95.0),
        DrainPoint(time=T0, level=89.0),
        DrainPoint(time=T0 + DAY, level=85.0),
    ]
