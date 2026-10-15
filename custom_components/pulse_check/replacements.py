"""Replacement and charge history per device.

Every time a battery is replaced or charged (the user says so with a
service, or the level jumps up by itself) an event is recorded and the
*cycle* that just ended is summarised: how many days it lasted and how
fast it drained. Those summaries are what "unusual behaviour" is judged
against: a cycle draining far faster than the device's own past cycles
is worth a look.

All of it is kept in the store under `history[device_id]`:

    events:  [{at, kind, battery_type, level_before, level_after, auto}]
    cycles:  [{start, end, kind, days, rate_per_day}]
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from .core.models import as_utc, to_iso

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .core import DeviceHealth
    from .storage import PulseCheckStore

type EventKind = Literal["replaced", "charged"]

# A level that rises by at least this much in one step is a new battery or
# a charge, whatever the device says.
JUMP_POINTS = 20
# A level that falls by at least this much in one step is suspicious.
SUDDEN_DROP_POINTS = 20
# Cycles shorter than this are too noisy to learn a rate from.
MIN_CYCLE_DAYS = 1.0
# After a manual "replaced", wait this long for the sensor to show the new
# battery before accepting whatever level it reports as the cycle's start.
SETTLE_SECONDS = 6 * 3600


class ReplacementTracker:
    """Records events, closes cycles, and spots unusual drain."""

    def __init__(self, store: PulseCheckStore) -> None:
        """Work on the store's history section."""
        self.store = store

    def _entry(self, device_id: str) -> dict[str, Any]:
        return self.store.history.setdefault(device_id, {"events": [], "cycles": []})

    def record(
        self,
        device_id: str,
        kind: EventKind,
        at: datetime,
        battery_type: str | None,
        level_before: int | None = None,
        auto: bool = False,
    ) -> None:
        """Add an event and close the cycle that ended with it."""
        entry = self._entry(device_id)
        events: list[dict[str, Any]] = entry["events"]
        if level_before is None:
            level_before = self.store.levels.get(device_id, {}).get("level")
        if events:
            previous = events[-1]
            start = as_utc(datetime.fromisoformat(previous["at"]))
            days = (as_utc(at) - start).total_seconds() / 86400
            start_level = previous.get("level_after")
            rate = None
            if (
                days >= MIN_CYCLE_DAYS
                and isinstance(start_level, int | float)
                and isinstance(level_before, int | float)
                and start_level > level_before
            ):
                rate = (start_level - level_before) / days
            entry["cycles"].append(
                {
                    "start": previous["at"],
                    "end": to_iso(at),
                    "kind": kind,
                    "days": round(days, 1),
                    "rate_per_day": round(rate, 3) if rate is not None else None,
                }
            )
        events.append(
            {
                "at": to_iso(at),
                "kind": kind,
                "battery_type": battery_type,
                "level_before": level_before,
                "level_after": None,  # filled in by the next observation
                "auto": auto,
            }
        )
        self.store.async_save()

    def last_event(self, device_id: str) -> dict[str, Any] | None:
        """The most recent replacement or charge, if any."""
        events = self.store.history.get(device_id, {}).get("events") or []
        return events[-1] if events else None

    def average_rate(self, device_id: str) -> float | None:
        """Mean drain rate over the device's completed cycles that had one."""
        cycles = self.store.history.get(device_id, {}).get("cycles") or []
        rates = [c["rate_per_day"] for c in cycles if c.get("rate_per_day")]
        return sum(rates) / len(rates) if rates else None

    def cycle_stats(self, device_id: str) -> dict[str, Any]:
        """Count, average length and average rate of completed cycles."""
        cycles = self.store.history.get(device_id, {}).get("cycles") or []
        days = [c["days"] for c in cycles if c.get("days")]
        return {
            "cycles": len(cycles),
            "average_days": round(sum(days) / len(days), 1) if days else None,
            "average_rate_per_day": self.average_rate(device_id),
        }

    def observe(self, devices: Iterable[DeviceHealth], now: datetime) -> bool:
        """Look at the latest levels: detect jumps, finish events, flag unusual drain.

        Returns True when the store changed.
        """
        changed = False
        levels = self.store.levels
        for device in devices:
            battery = device.battery
            if battery is None or battery.level is None:
                continue
            level = battery.level
            previous = levels.get(device.device_id)
            previous_level = previous.get("level") if previous else None
            was_charging = bool(previous.get("charging")) if previous else False

            # A big rise means a new battery, or a charge for rechargeables.
            if isinstance(previous_level, int | float) and level - previous_level >= JUMP_POINTS:
                rechargeable = bool(
                    self.store.device_settings.get(device.device_id, {}).get("rechargeable")
                )
                kind: EventKind = "charged" if rechargeable or was_charging else "replaced"
                self.record(device.device_id, kind, now, None, int(previous_level), auto=True)
                changed = True

            last = self.last_event(device.device_id)
            if last is not None and last.get("level_after") is None:
                # The first reading that shows the new battery is the cycle's
                # start level. Sleepy sensors can keep reporting the old level
                # for hours, so wait for a rise, but not forever.
                before = last.get("level_before")
                settled = (as_utc(now) - as_utc(datetime.fromisoformat(last["at"]))).total_seconds()
                if (
                    not isinstance(before, int | float)
                    or level > before
                    or last.get("auto")
                    or settled >= SETTLE_SECONDS
                ):
                    last["level_after"] = level
                    changed = True

            sudden_drop = (
                isinstance(previous_level, int | float)
                and previous_level - level >= SUDDEN_DROP_POINTS
                and level > 0
            )
            if previous_level != level or (
                previous and previous.get("charging") != battery.is_charging
            ):
                charging_seen = (previous or {}).get("charging_seen_at")
                if battery.is_charging:
                    charging_seen = to_iso(now)
                levels[device.device_id] = {
                    "level": level,
                    "at": to_iso(now),
                    "charging": battery.is_charging,
                    "sudden_drop_at": to_iso(now)
                    if sudden_drop
                    else (previous or {}).get("sudden_drop_at"),
                    # The last time a charging signal was seen: it classifies
                    # the battery as one that gets charged (core/cycles.py).
                    "charging_seen_at": charging_seen,
                }
                changed = True

        for device_id in list(levels):
            if device_id not in {d.device_id for d in devices}:
                del levels[device_id]
                changed = True
        if changed:
            self.store.async_save()
        return changed

    def annotate(self, device: DeviceHealth, now: datetime) -> None:
        """Set `last_replaced` on a device from its recorded events.

        Unusual drain is judged from the battery's cycles (core/cycles.py) by
        the history tracker; this adds the user's own record and, when there
        is no history to judge from, a sudden drop seen live.
        """
        last = self.last_event(device.device_id)
        if last is not None:
            device.last_replaced = as_utc(datetime.fromisoformat(last["at"]))
        # Without recorder history there are no cycles; the live readings
        # still catch a sudden drop.
        if device.unusual is None:
            dropped = self.store.levels.get(device.device_id, {}).get("sudden_drop_at")
            if dropped and (as_utc(now) - as_utc(datetime.fromisoformat(dropped))).days < 7:
                device.unusual = "level dropped suddenly"
