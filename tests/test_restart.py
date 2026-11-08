"""Restarts: what was known is kept, and a device that never came back is reported."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.pulse_check.const import (
    CONF_REMINDER_DAYS,
    CONF_RESTART_TIMEOUT_MINUTES,
    DEBOUNCE_SECONDS,
    DEFAULT_CONFIRM_MINUTES,
    DEFAULT_RESTART_TIMEOUT_MINUTES,
    EVENT_TRANSITION,
)
from tests.test_notify import (
    OPTIONS,
    TEMPERATURE,
    _messages,
    _ready,
    _restart,
    _set_up,
    _tick,
)

# The timeout as shipped, instead of the shared test options' 0.
TIMEOUT = {**OPTIONS, CONF_RESTART_TIMEOUT_MINUTES: DEFAULT_RESTART_TIMEOUT_MINUTES}


async def test_a_device_that_never_came_back_is_offline_after_the_timeout(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The fixture's front door lock is dead from the very start of this run."""
    events = async_capture_events(hass, EVENT_TRANSITION)
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now, TIMEOUT)
    await _ready(hass, freezer)
    # Not loaded yet, for all Pulse Check can tell.
    await _tick(hass, freezer, timedelta(minutes=20))
    assert calls == []

    # The timeout passes, then the usual confirmation window.
    await _tick(hass, freezer, timedelta(minutes=5))
    assert calls == []
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert _messages(calls) == ["Front Door Lock: offline since the restart"]
    [entered] = [e for e in events if e.data["kind"] == "entered"]
    assert entered.data["issue"] == "offline"


async def test_zero_waits_for_ever(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now, OPTIONS)
    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(hours=2))
    assert calls == []


async def test_a_restart_keeps_an_offline_device_offline(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Offline before the restart and still down after it: no "resolved", reminders go on."""
    events = async_capture_events(hass, EVENT_TRANSITION)
    entry, _, calls = await _set_up(
        hass, fixture_snapshot, freezer, fixed_now, {**TIMEOUT, CONF_REMINDER_DAYS: 1}
    )
    await _ready(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert _messages(calls) == ["Kitchen H&T: offline"]
    await _tick(hass, freezer, timedelta(seconds=5))  # the store's save delay

    # Restart while it is still down; well past the timeout.
    await _restart(hass, entry, freezer, dt_util.utcnow())
    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_RESTART_TIMEOUT_MINUTES + 10))
    kitchen = [e for e in events if e.data["name"] == "Kitchen H&T"]
    assert [e.data["kind"] for e in kitchen] == ["entered"]
    # Not announced again, in either wording: it was already known.
    assert [m for m in _messages(calls) if m.startswith("Kitchen")] == ["Kitchen H&T: offline"]

    # The reminder it was due still comes.
    await _tick(hass, freezer, timedelta(days=1))
    assert any(
        m.startswith("Still unresolved") and "Kitchen H&T: offline" in m for m in _messages(calls)
    )

    # And when it comes back, it resolves as usual.
    hass.states.async_set("sensor.kitchen_ht_temperature", "21.7", TEMPERATURE)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    kitchen = [e for e in events if e.data["name"] == "Kitchen H&T"]
    assert [e.data["kind"] for e in kitchen] == ["entered", "resolved"]


async def test_a_problem_still_waiting_for_confirmation_is_dropped(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Seen offline only moments before the restart: not carried over as news."""
    events = async_capture_events(hass, EVENT_TRANSITION)
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now, OPTIONS)
    await _ready(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    await _tick(hass, freezer, timedelta(seconds=5))

    await _restart(hass, entry, freezer, dt_util.utcnow())
    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert calls == []
    assert [e for e in events if e.data["name"] == "Kitchen H&T"] == []
