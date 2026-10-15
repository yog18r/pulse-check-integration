"""Maintenance mode: messages held back, a summary at the end, and nothing replayed."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.pulse_check.const import (
    CONF_MAINTENANCE_HOURS,
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    DEBOUNCE_SECONDS,
    DEFAULT_CONFIRM_MINUTES,
    DOMAIN,
    EVENT_TRANSITION,
)
from custom_components.pulse_check.websocket import snapshot_payload
from tests.test_notify import (
    BATTERY,
    OPTIONS,
    _digests,
    _local,
    _messages,
    _ready,
    _restart,
    _set_up,
    _tick,
)

SENSOR = "binary_sensor.pulse_check_maintenance_mode"
SUMMARY = "Maintenance mode is over. New since it began:"


async def _maintenance(hass: HomeAssistant, hours: float | None = None) -> None:
    data = {} if hours is None else {"hours": hours}
    await hass.services.async_call(DOMAIN, "maintenance_mode", data, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)


def _sensor(hass: HomeAssistant) -> tuple[str, dict[str, Any]]:
    state = hass.states.get(SENSOR)
    assert state is not None
    return state.state, dict(state.attributes)


async def _plug_offline(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    hass.states.async_set("switch.office_plug", "unavailable")
    hass.states.async_set("sensor.office_plug_power", "unavailable")
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))  # first seen
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))  # confirmed


async def _plug_back(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    hass.states.async_set("switch.office_plug", "on")
    hass.states.async_set("sensor.office_plug_power", "4.2")
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))


async def test_a_window_holds_messages_back_and_ends_with_one_summary(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    assert _sensor(hass)[0] == "off"
    events = async_capture_events(hass, EVENT_TRANSITION)

    await _maintenance(hass, 2)
    state, attributes = _sensor(hass)
    assert state == "on"
    assert attributes["until"] == "2026-10-15T12:05:01.000Z"

    # A battery drops and the plug goes offline: tracked, not sent.
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    await _plug_offline(hass, freezer)
    assert calls == []
    entered = [e.data for e in events if e.data["kind"] == "entered"]
    assert [(e["name"], e["issue"], e["maintenance"]) for e in entered] == [
        ("Kitchen H&T", "battery_critical", True),
        ("Office Plug", "offline", True),
    ]

    # The plug comes back before the end, so it is not news any more.
    await _plug_back(hass, freezer)

    await _tick(hass, freezer, timedelta(hours=2))
    assert _sensor(hass) == ("off", {"friendly_name": "Pulse Check Maintenance mode"})
    assert _messages(calls) == [f"{SUMMARY}\n- Kitchen H&T: battery critical (5 %)"]

    # Nothing is replayed, and the next problem is sent as usual.
    await _tick(hass, freezer, timedelta(minutes=10))
    assert len(calls) == 1
    await _plug_offline(hass, freezer)
    assert _messages(calls)[1:] == ["Office Plug: offline"]


async def test_problems_from_before_the_window_are_not_in_the_summary(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    """The baseline's critical batteries were known when the work began."""
    _, device_ids, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    await _maintenance(hass, 1)
    await _tick(hass, freezer, timedelta(seconds=5))  # the store's save delay
    window = hass_storage["pulse_check.data"]["data"]["maintenance"]
    assert window["started_at"] == "2026-10-15T10:05:01.000Z"
    assert window["known"][device_ids["dev_z2m_motion"]] == ["battery_critical"]

    await _tick(hass, freezer, timedelta(hours=1))
    assert calls == []  # nothing new, so nothing to say
    await _tick(hass, freezer, timedelta(seconds=5))
    assert hass_storage["pulse_check.data"]["data"]["maintenance"] == {}


async def test_calling_it_again_moves_the_end_and_keeps_the_start(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    await _maintenance(hass, 1)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(minutes=30))

    await _maintenance(hass, 2)  # from now: ends 2.5 h after the first call
    await _tick(hass, freezer, timedelta(hours=1))
    assert _sensor(hass)[0] == "on"
    assert calls == []
    await _tick(hass, freezer, timedelta(hours=1))
    assert _messages(calls) == [f"{SUMMARY}\n- Kitchen H&T: battery critical (5 %)"]


async def test_hours_zero_ends_it_now(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    await _maintenance(hass, 0)  # nothing to end: nothing happens
    assert _sensor(hass)[0] == "off"

    await _maintenance(hass, 8)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert calls == []

    await _maintenance(hass, 0)
    assert _sensor(hass)[0] == "off"
    assert _messages(calls) == [f"{SUMMARY}\n- Kitchen H&T: battery critical (5 %)"]
    # The cancelled end-of-window timer sends no second summary.
    await _tick(hass, freezer, timedelta(hours=9))
    assert [m for m in _messages(calls) if m.startswith(SUMMARY)] == _messages(calls)[:1]


async def test_the_default_length_comes_from_the_options(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up(
        hass, fixture_snapshot, freezer, fixed_now, {**OPTIONS, CONF_MAINTENANCE_HOURS: 0.5}
    )
    await _maintenance(hass)
    assert _sensor(hass)[1]["until"] == "2026-10-15T10:30:00.000Z"
    entry = hass.config_entries.async_loaded_entries(DOMAIN)[0]
    assert snapshot_payload(entry.runtime_data)["maintenance_until"] == "2026-10-15T10:30:00.000Z"

    await _tick(hass, freezer, timedelta(minutes=31))
    assert _sensor(hass)[0] == "off"
    assert snapshot_payload(entry.runtime_data)["maintenance_until"] is None


async def test_a_restart_during_the_window_keeps_it(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The work itself may restart Home Assistant; the window survives it."""
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    await _maintenance(hass, 3)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))

    await _restart(hass, entry, freezer, fixed_now + timedelta(hours=1))
    assert _sensor(hass)[0] == "on"
    await _ready(hass, freezer)
    await _plug_offline(hass, freezer)
    assert calls == []

    await _tick(hass, freezer, timedelta(hours=2))
    assert _sensor(hass)[0] == "off"
    assert _messages(calls) == [
        f"{SUMMARY}\n- Kitchen H&T: battery critical (5 %)\n- Office Plug: offline"
    ]


async def test_a_window_that_ends_while_stopped_is_summarised_after_the_start(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    await _maintenance(hass, 1)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))

    await _restart(hass, entry, freezer, fixed_now + timedelta(hours=2))
    assert _sensor(hass)[0] == "off"
    assert calls == []  # not during the grace period
    await _ready(hass, freezer)
    assert _messages(calls) == [f"{SUMMARY}\n- Kitchen H&T: battery critical (5 %)"]


async def test_digests_and_reminders_wait(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A digest slot inside the window is skipped for good; reminders resume after it."""
    options = {**OPTIONS, CONF_NOTIFY_WARNING: "daily", CONF_REMINDER_DAYS: 0.5}
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    await _maintenance(hass, 14)  # over the 09:00 local digest (16:00 UTC)

    await _tick(hass, freezer, _local(15, 9, 1) - fixed_now)
    assert calls == []
    # A restart does not catch the skipped digest up either.
    await _restart(hass, entry, freezer, _local(15, 10))
    await _ready(hass, freezer)
    assert _digests(calls, "daily") == []
    assert calls == []

    # The window ends: no summary (nothing new), then the overdue reminders.
    await _tick(hass, freezer, _local(15, 17, 30) - _local(15, 10))
    assert _digests(calls, "daily") == []
    reminders = [m for m in _messages(calls) if m.startswith("Still unresolved")]
    assert len(reminders) == 3
    assert not any(m.startswith(SUMMARY) for m in _messages(calls))

    # The next day's digest goes out as usual.
    await _tick(hass, freezer, _local(16, 9) - _local(15, 17, 30))
    assert len(_digests(calls, "daily")) == 1
