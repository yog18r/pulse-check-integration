"""Notifications: startup baseline, confirmation window, transitions, reminders, digests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.pulse_check.const import (
    CONF_DIGEST_TIME,
    CONF_DIGEST_WEEKDAY,
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    CONF_WEEKLY_ALL_CLEAR,
    DEBOUNCE_SECONDS,
    DEFAULT_CONFIRM_MINUTES,
    DEFAULT_STARTUP_GRACE_MINUTES,
    DOMAIN,
    EVENT_TRANSITION,
)
from custom_components.pulse_check.notify import last_digest_slot
from tests.conftest import load_fixture_into_hass

OPTIONS = {
    CONF_NOTIFY_TARGETS: ["notify.mobile_app_test"],
    CONF_DIGEST_TIME: "09:00:00",
    CONF_DIGEST_WEEKDAY: "thursday",  # 2026-10-15 is a Thursday
}
# The test instance runs in US/Pacific: the fixture's 10:00 UTC is 03:00 local.
BATTERY = {"device_class": "battery", "unit_of_measurement": "%"}
TEMPERATURE = {"device_class": "temperature", "unit_of_measurement": "°C"}


def _messages(calls: list[ServiceCall]) -> list[str]:
    return [call.data["message"] for call in calls]


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    """Advance time and let timers, the debounced refresh and the notifier run.

    The notifier reacts to each refresh in a background task, which
    `async_block_till_done` skips unless asked. Without waiting for it, a
    slow machine (CI under load) checks for messages before they are sent.
    """
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _set_up(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    options: dict[str, Any] | None = None,
) -> tuple[MockConfigEntry, dict[str, str], list[ServiceCall]]:
    freezer.move_to(fixed_now)
    calls = async_mock_service(hass, "notify", "mobile_app_test")
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    entry = MockConfigEntry(
        domain=DOMAIN, title="Pulse Check", unique_id=DOMAIN, options=options or OPTIONS
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry, device_ids, calls


async def _ready(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the startup grace period pass; the baseline is recorded at its end."""
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_STARTUP_GRACE_MINUTES, seconds=1))


async def test_nothing_is_announced_at_startup(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    """The fixture has six problems; after a start they are a baseline, not news."""
    events = async_capture_events(hass, EVENT_TRANSITION)
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _tick(hass, freezer, timedelta(minutes=1))  # still inside the grace period
    assert calls == []
    assert events == []

    await _ready(hass, freezer)
    assert calls == []
    assert events == []
    # ...but they are remembered, so they will not be announced later either.
    await _tick(hass, freezer, timedelta(seconds=5))
    notify_state = hass_storage["pulse_check.data"]["data"]["notify"]
    # The dead lock is not among them: it has never been seen online in
    # this run, so it is "not loaded yet" rather than offline.
    assert {key for records in notify_state.values() for key in records} == {
        "quiet",
        "battery_critical",
        "battery_warning",
    }
    assert all(r["confirmed"] for records in notify_state.values() for r in records.values())


async def test_a_restart_storm_of_unavailable_devices_sends_nothing(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Every primary entity is unavailable while integrations load; then they return."""
    events = async_capture_events(hass, EVENT_TRANSITION)
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    healthy = {
        entity_id: state
        for entity_id, state in fixture_snapshot["states"].items()
        if state["state"] != "unavailable"
    }
    for entity_id, state in healthy.items():
        hass.states.async_set(entity_id, "unavailable", state["attributes"])
    await _tick(
        hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1)
    )  # a recompute during startup
    assert calls == []

    # Devices come back one by one during and after the grace period.
    await _tick(hass, freezer, timedelta(minutes=1))
    for entity_id, state in healthy.items():
        hass.states.async_set(entity_id, state["state"], state["attributes"])
    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert calls == []
    assert [e for e in events if e.data["kind"] == "entered"] == []


async def test_a_device_never_seen_online_is_not_offline(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """An integration that loads ten minutes after a restart is not an outage."""
    freezer.move_to(fixed_now)
    # The Shelly H&T is unavailable from the very start of this run.
    fixture = {**fixture_snapshot, "states": dict(fixture_snapshot["states"])}
    fixture["states"]["sensor.kitchen_ht_temperature"] = {
        **fixture_snapshot["states"]["sensor.kitchen_ht_temperature"],
        "state": "unavailable",
    }
    events = async_capture_events(hass, EVENT_TRANSITION)
    _, _, calls = await _set_up(hass, fixture, freezer, fixed_now)
    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(minutes=10))
    assert calls == []
    assert [e for e in events if e.data["name"] == "Kitchen H&T"] == []

    # It comes up: nothing to announce either.
    hass.states.async_set("sensor.kitchen_ht_temperature", "21.7", TEMPERATURE)
    await _tick(hass, freezer, timedelta(minutes=1))
    assert calls == []

    # Now a real outage: unavailable for the confirmation window.
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await _tick(
        hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1)
    )  # the recompute that first sees it
    assert calls == []
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert _messages(calls) == ["Kitchen H&T: offline"]


async def test_a_new_battery_problem_is_announced_at_once(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)

    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert _messages(calls) == ["Kitchen H&T: battery critical (5 %)"]

    # Another recompute changes nothing: no repeats.
    await _tick(hass, freezer, timedelta(minutes=6))
    assert len(calls) == 1

    # Back to 90 %: resolved, event only, no message.
    hass.states.async_set("sensor.kitchen_ht_battery", "90", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert len(calls) == 1
    assert [(e.data["kind"], e.data["issue"]) for e in events if "Kitchen" in e.data["name"]] == [
        ("entered", "battery_critical"),
        ("resolved", "battery_critical"),
    ]


async def test_offline_must_persist_for_the_confirmation_window(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)

    # The Shelly H&T's only primary entity drops out: offline, if it lasts.
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await _tick(hass, freezer, timedelta(minutes=3))
    assert calls == []
    assert events == []

    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES))
    assert _messages(calls) == ["Kitchen H&T: offline"]
    assert events[0].data["issue"] == "offline"

    # The plug blips for two minutes and comes back: nothing, not even an event.
    calls.clear()
    events.clear()
    hass.states.async_set("switch.office_plug", "unavailable")
    hass.states.async_set("sensor.office_plug_power", "unavailable")
    await _tick(hass, freezer, timedelta(minutes=2))
    hass.states.async_set("switch.office_plug", "on")
    hass.states.async_set("sensor.office_plug_power", "4.2")
    await _tick(hass, freezer, timedelta(minutes=10))
    assert calls == []
    assert [e for e in events if e.data["name"] == "Office Plug"] == []


async def test_a_restart_never_resends(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert len(calls) == 1
    await _tick(hass, freezer, timedelta(seconds=5))  # the store's save delay

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(minutes=10))
    assert len(calls) == 1


async def test_saving_options_does_not_announce_anything(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The reload after an options save starts from a fresh baseline."""
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"thresholds": {"battery_warning": 60, "battery_critical": 50}, "notifications": OPTIONS},
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    attention = hass.states.get("sensor.pulse_check_attention")
    assert attention is not None
    assert attention.state == "9"

    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(minutes=10))
    assert calls == []
    assert [e for e in events if e.data["kind"] == "entered"] == []


async def test_reminders_while_unresolved(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Baseline problems are never announced, but reminders still reach the user."""
    _, _, calls = await _set_up(
        hass, fixture_snapshot, freezer, fixed_now, {**OPTIONS, CONF_REMINDER_DAYS: 1}
    )
    await _ready(hass, freezer)
    assert calls == []

    await _tick(hass, freezer, timedelta(days=1, minutes=1))
    reminders = [m for m in _messages(calls) if m.startswith("Still unresolved")]
    # The motion sensor, the smoke alarm and the remote. Not the dead lock:
    # never seen online in this run, so never recorded as offline.
    assert len(reminders) == 3
    assert "Still unresolved after 1 day. Living Room Motion: battery critical (12 %)" in reminders

    # Not again until another interval has passed.
    calls.clear()
    await _tick(hass, freezer, timedelta(hours=6))
    assert calls == []


async def test_digests_list_devices_on_that_policy(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(
        hass, fixture_snapshot, freezer, fixed_now, {**OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    )
    await _ready(hass, freezer)

    # Past 09:00 local (16:00 UTC), the first digest time after the start.
    freezer.move_to(fixed_now + timedelta(hours=23))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    daily = [m for m in _messages(calls) if m.startswith("Pulse Check daily digest")]
    assert len(daily) == 1
    assert "- Bedroom Temp & Humidity: battery low (28 %)" in daily[0]
    assert "- Garage Multisensor: not heard from for" in daily[0]
    assert "Front Door Lock" not in daily[0]  # instant, not in the digest
    assert not any(m.startswith("Pulse Check weekly digest") for m in _messages(calls))


async def test_per_device_policy_none_silences_a_device(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    hass_storage["pulse_check.data"] = {
        "version": 1,
        "key": "pulse_check.data",
        "data": {"device_settings": {}},
    }
    _, device_ids, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await hass.services.async_call(
        DOMAIN,
        "set_device_settings",
        {"device_id": device_ids["dev_shelly_ht"], "notify_policy": "none"},
        blocking=True,
    )
    await _ready(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)

    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert calls == []
    assert events[0].data["policy"] == "none"  # the event still fires for automations


# -- catching up missed digests -----------------------------------------------


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in October 2026 on the test instance's local clock."""
    return datetime(2026, 10, day, hour, minute, tzinfo=dt_util.get_default_time_zone())


def _digests(calls: list[ServiceCall], kind: str) -> list[str]:
    return [m for m in _messages(calls) if m.startswith(f"Pulse Check {kind} digest")]


async def _restart(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory, at: datetime
) -> None:
    """Home Assistant stops, stays off until `at`, then starts the entry again."""
    await _tick(hass, freezer, timedelta(seconds=5))  # the store's save delay
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    freezer.move_to(at)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_the_last_digest_slot_follows_the_local_clock(hass: HomeAssistant) -> None:
    """Sydney's clocks went forward on Sunday 4 October 2026; the slot stays at 09:00."""
    await hass.config.async_set_time_zone("Australia/Sydney")
    monday_early = datetime(2026, 10, 5, 8, 0, tzinfo=dt_util.get_default_time_zone())

    daily = last_digest_slot(monday_early, 9, 0)
    assert (daily.day, daily.hour, daily.minute) == (4, 9, 0)
    assert last_digest_slot(monday_early.replace(hour=9), 9, 0) == monday_early.replace(hour=9)

    weekly = last_digest_slot(monday_early, 9, 0, weekday=5)  # Saturday
    assert (weekly.day, weekly.hour) == (3, 9)
    assert weekly.utcoffset() == timedelta(hours=10)  # before the change, still standard time
    assert daily.utcoffset() == timedelta(hours=11)


async def test_a_digest_missed_while_stopped_is_sent_once_after_the_start(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, _, calls = await _set_up(
        hass, fixture_snapshot, freezer, fixed_now, {**OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    )
    await _ready(hass, freezer)

    # Off from Thursday 03:00 to Saturday 10:00: three daily slots go by.
    await _restart(hass, entry, freezer, _local(17, 10))
    await _tick(hass, freezer, timedelta(minutes=1))
    assert calls == []  # nothing during the grace period
    await _ready(hass, freezer)
    assert len(_digests(calls, "daily")) == 1
    assert "- Bedroom Temp & Humidity: battery low (28 %)" in _digests(calls, "daily")[0]
    # The weekly digest was missed too, but had nothing to say.
    assert _digests(calls, "weekly") == []

    # Then the normal schedule: Sunday 09:00.
    await _tick(hass, freezer, _local(18, 9) - dt_util.utcnow())
    assert len(_digests(calls, "daily")) == 2


async def test_a_digest_due_during_the_start_is_sent_when_the_grace_period_ends(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, _, calls = await _set_up(
        hass, fixture_snapshot, freezer, fixed_now, {**OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    )
    await _ready(hass, freezer)

    # A restart at 08:58: the 09:00 digest falls inside the grace period.
    await _restart(hass, entry, freezer, _local(15, 8, 58))
    await _tick(hass, freezer, timedelta(minutes=2))
    assert calls == []
    await _ready(hass, freezer)
    assert len(_digests(calls, "daily")) == 1

    # Another restart the same morning does not send it again.
    await _restart(hass, entry, freezer, _local(15, 11))
    await _ready(hass, freezer)
    assert len(_digests(calls, "daily")) == 1


async def test_a_first_run_skips_slots_from_before_the_install(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The weekly all-clear would send on any catch-up; the first start sends nothing."""
    options = {**OPTIONS, CONF_NOTIFY_WARNING: "daily", CONF_WEEKLY_ALL_CLEAR: True}
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(minutes=10))
    assert calls == []

    # Off for a week, back on Thursday afternoon: one of each, and the
    # weekly one keeps its all-clear line.
    await _restart(hass, entry, freezer, _local(22, 12))
    await _ready(hass, freezer)
    assert len(_digests(calls, "daily")) == 1
    assert _digests(calls, "weekly") == ["Pulse Check weekly digest\nAll devices OK."]


async def test_a_slot_with_nothing_to_say_still_counts_as_judged(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    """By default nothing is daily, so the daily digest has nothing to say."""
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)

    await _tick(hass, freezer, _local(15, 9) - dt_util.utcnow())
    assert _digests(calls, "daily") == []
    assert len(_digests(calls, "weekly")) == 1
    await _tick(hass, freezer, timedelta(seconds=5))
    digests = hass_storage["pulse_check.data"]["data"]["digests"]
    assert digests["daily"].startswith("2026-10-15T16:00:00")  # 09:00 Pacific

    await _restart(hass, entry, freezer, _local(15, 9, 30))
    await _ready(hass, freezer)
    assert _digests(calls, "daily") == []
    assert len(_digests(calls, "weekly")) == 1
