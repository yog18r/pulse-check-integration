"""When a "charging now" mark ends (core/charging.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pulse_check.core.charging import NO_RISE, follow_mark, new_mark
from custom_components.pulse_check.core.models import BatteryReading

MARKED = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)
WARNING = 30


def _reading(level: int | None, is_low: bool = False) -> BatteryReading:
    return BatteryReading(is_low=is_low, source="sensor", entity_id="sensor.b", level=level)


def _follow(level: int | None, after: timedelta, mark: dict | None = None, **kw: bool):  # type: ignore[no-untyped-def, type-arg]
    return follow_mark(mark or new_mark(10, MARKED), _reading(level, **kw), WARNING, MARKED + after)


def test_a_rising_battery_stays_marked_and_its_peak_moves() -> None:
    kept = _follow(17, timedelta(hours=1))
    assert kept is not None
    assert kept["peak"] == 17
    assert kept["from"] == 10


def test_out_of_the_warning_range_ends_it() -> None:
    """Not full: an EV set to stop at 80 % never gets there."""
    assert _follow(WARNING, timedelta(hours=2)) is not None
    assert _follow(WARNING + 1, timedelta(hours=2)) is None


def test_falling_below_where_it_was_marked_ends_it() -> None:
    assert _follow(9, timedelta(minutes=10)) is None


@pytest.mark.parametrize(("hours", "kept"), [(5.9, True), (6, False)])
def test_no_rise_for_six_hours_ends_it(hours: float, kept: bool) -> None:
    assert (_follow(10, timedelta(hours=hours)) is not None) is kept


def test_the_six_hours_run_from_the_last_rise() -> None:
    risen = _follow(15, timedelta(hours=5))
    assert risen is not None
    # Five hours after that rise it is still charging, at a standstill.
    assert follow_mark(risen, _reading(15), WARNING, MARKED + timedelta(hours=10)) is not None
    assert follow_mark(risen, _reading(15), WARNING, MARKED + timedelta(hours=11)) is None


def test_a_battery_with_only_a_low_sensor_ends_when_not_low_or_after_six_hours() -> None:
    mark = new_mark(None, MARKED)
    assert _follow(None, timedelta(hours=1), mark, is_low=True) is not None
    assert _follow(None, timedelta(hours=1), mark, is_low=False) is None
    assert _follow(None, NO_RISE, mark, is_low=True) is None


def test_no_battery_ends_it() -> None:
    assert follow_mark(new_mark(10, MARKED), None, WARNING, MARKED) is None


def test_a_mark_made_without_a_level_starts_from_the_first_one() -> None:
    kept = _follow(12, timedelta(minutes=5), new_mark(None, MARKED))
    assert kept is not None
    assert kept["peak"] == 12
