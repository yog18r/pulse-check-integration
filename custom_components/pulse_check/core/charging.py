"""A battery the user has said they are charging.

"Mark charged" on the card or a phone notification means "I am charging
it now". A home battery charging from the grid, a phone on its charger or
an EV can take hours to climb back out of the warning range, and many of
them never say they are charging. Until it has, the mark stands in for
that signal: the battery counts as charging, so it is not low, not on the
Charge list, and its low-battery notification is cleared.

A mark ends at the first of:

- the level is above the warning level: it is not low any more. Not
  "full": many batteries stop short of it on purpose (an EV set to 80 %,
  a home battery kept in reserve);
- the level is below where it was when marked: it is being used, not
  charged (unplugged, a mistaken tap);
- the level has not risen for `NO_RISE`: charging never started or has
  stopped short (a loose plug, a charger off);
- for a battery with only a low / not low sensor: it reads not low, or
  `NO_RISE` has passed since it was marked;
- the device no longer reports a battery at all.

A mark that ends for any reason but the first leaves the battery low
again, and it comes back like any new problem.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .models import as_utc, to_iso

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .models import BatteryReading

# How long a marked battery may go without rising before the mark ends.
NO_RISE = timedelta(hours=6)


def new_mark(level: float | None, now: datetime) -> dict[str, Any]:
    """The mark for a battery marked as charging at `level`, now."""
    return {"at": to_iso(now), "from": level, "peak": level, "peak_at": to_iso(now)}


def _time(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            return as_utc(datetime.fromisoformat(value))
        except ValueError:
            pass
    return fallback


def follow_mark(
    mark: Mapping[str, Any],
    battery: BatteryReading | None,
    warning: float,
    now: datetime,
) -> dict[str, Any] | None:
    """The mark to keep after this reading, or None when it has ended.

    `battery` is the reading as the device reports it, before the mark is
    applied; `warning` is the device's warning level.
    """
    now = as_utc(now)
    marked_at = _time(mark.get("at"), now)
    if battery is None:
        return None
    level = battery.level
    if level is None:
        if not battery.is_low or now - marked_at >= NO_RISE:
            return None
        return dict(mark)
    if level > warning:
        return None
    start = mark.get("from")
    if isinstance(start, int | float) and level < start:
        return None
    peak = mark.get("peak")
    if not isinstance(peak, int | float) or level > peak:
        return {**mark, "peak": level, "peak_at": to_iso(now)}
    if now - _time(mark.get("peak_at"), marked_at) >= NO_RISE:
        return None
    return dict(mark)
