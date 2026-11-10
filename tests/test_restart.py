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
from tests.helpers import (
    NOTIFY_OPTIONS,
    TEMPERATURE,
    advance,
    past_grace,
    restart_ha,
    sent_messages,
    set_up_notify,
)

# The timeout as shipped, instead of the shared test options' 0.
TIMEOUT = {**NOTIFY_OPTIONS, CONF_RESTART_TIMEOUT_MINUTES: DEFAULT_RESTART_TIMEOUT_MINUTES}


async def test_a_device_that_never_came_back_is_offline_after_the_timeout(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The fixture's front door lock is dead from the very start of this run."""
    events = async_capture_events(hass, EVENT_TRANSITION)
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, TIMEOUT)
    await past_grace(hass, freezer)
    # Not loaded yet, for all Pulse Check can tell.
    await advance(hass, freezer, timedelta(minutes=20))
    assert calls == []

    # The timeout passes, then the usual confirmation window.
    await advance(hass, freezer, timedelta(minutes=5))
    assert calls == []
    await advance(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert sent_messages(calls) == ["Front Door Lock: offline since the restart"]
    [entered] = [e for e in events if e.data["kind"] == "entered"]
    assert entered.data["issue"] == "offline"


async def test_zero_waits_for_ever(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, NOTIFY_OPTIONS)
    await past_grace(hass, freezer)
    await advance(hass, freezer, timedelta(hours=2))
    assert calls == []


async def test_a_restart_keeps_an_offline_device_offline(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Offline before the restart and still down after it: no "resolved", reminders go on."""
    events = async_capture_events(hass, EVENT_TRANSITION)
    entry, _, calls = await set_up_notify(
        hass, fixture_snapshot, freezer, fixed_now, {**TIMEOUT, CONF_REMINDER_DAYS: 1}
    )
    await past_grace(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    await advance(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert sent_messages(calls) == ["Kitchen H&T: offline"]
    await advance(hass, freezer, timedelta(seconds=5))  # the store's save delay

    # Restart while it is still down; well past the timeout.
    await restart_ha(hass, entry, freezer, dt_util.utcnow())
    await past_grace(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=DEFAULT_RESTART_TIMEOUT_MINUTES + 10))
    kitchen = [e for e in events if e.data["name"] == "Kitchen H&T"]
    assert [e.data["kind"] for e in kitchen] == ["entered"]
    # Not announced again, in either wording: it was already known.
    assert [m for m in sent_messages(calls) if m.startswith("Kitchen")] == ["Kitchen H&T: offline"]

    # The reminder it was due still comes.
    await advance(hass, freezer, timedelta(days=1))
    assert any(
        m.startswith("Still unresolved") and "Kitchen H&T: offline" in m
        for m in sent_messages(calls)
    )

    # And when it comes back, it resolves as usual.
    hass.states.async_set("sensor.kitchen_ht_temperature", "21.7", TEMPERATURE)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
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
    entry, _, calls = await set_up_notify(
        hass, fixture_snapshot, freezer, fixed_now, NOTIFY_OPTIONS
    )
    await past_grace(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    await advance(hass, freezer, timedelta(seconds=5))

    await restart_ha(hass, entry, freezer, dt_util.utcnow())
    await past_grace(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert calls == []
    assert [e for e in events if e.data["name"] == "Kitchen H&T"] == []
