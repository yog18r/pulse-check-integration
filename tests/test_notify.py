"""Notifications: startup baseline, confirmation window, transitions, reminders, digests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.pulse_check.const import (
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    CONF_WEEKLY_ALL_CLEAR,
    DEBOUNCE_SECONDS,
    DEFAULT_CONFIRM_MINUTES,
    DOMAIN,
    EVENT_TRANSITION,
)
from custom_components.pulse_check.notify import last_digest_slot
from tests.helpers import (
    BATTERY,
    NOTIFY_OPTIONS,
    TEMPERATURE,
    advance,
    digest_messages,
    local_time,
    open_general_options,
    past_grace,
    restart_ha,
    sent_messages,
    set_up_notify,
)


async def test_nothing_is_announced_at_startup(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    """The fixture has six problems; after a start they are a baseline, not news."""
    events = async_capture_events(hass, EVENT_TRANSITION)
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await advance(hass, freezer, timedelta(minutes=1))  # still inside the grace period
    assert calls == []
    assert events == []

    await past_grace(hass, freezer)
    assert calls == []
    assert events == []
    # ...but they are remembered, so they will not be announced later either.
    await advance(hass, freezer, timedelta(seconds=5))
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
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    healthy = {
        entity_id: state
        for entity_id, state in fixture_snapshot["states"].items()
        if state["state"] != "unavailable"
    }
    for entity_id, state in healthy.items():
        hass.states.async_set(entity_id, "unavailable", state["attributes"])
    await advance(
        hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1)
    )  # a recompute during startup
    assert calls == []

    # Devices come back one by one during and after the grace period.
    await advance(hass, freezer, timedelta(minutes=1))
    for entity_id, state in healthy.items():
        hass.states.async_set(entity_id, state["state"], state["attributes"])
    await past_grace(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
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
    _, _, calls = await set_up_notify(hass, fixture, freezer, fixed_now)
    await past_grace(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=10))
    assert calls == []
    assert [e for e in events if e.data["name"] == "Kitchen H&T"] == []

    # It comes up: nothing to announce either.
    hass.states.async_set("sensor.kitchen_ht_temperature", "21.7", TEMPERATURE)
    await advance(hass, freezer, timedelta(minutes=1))
    assert calls == []

    # Now a real outage: unavailable for the confirmation window.
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await advance(
        hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1)
    )  # the recompute that first sees it
    assert calls == []
    await advance(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert sent_messages(calls) == ["Kitchen H&T: offline"]


async def test_a_new_battery_problem_is_announced_at_once(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await past_grace(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)

    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert sent_messages(calls) == ["Kitchen H&T: battery critical (5 %)"]

    # Another recompute changes nothing: no repeats.
    await advance(hass, freezer, timedelta(minutes=6))
    assert len(calls) == 1

    # Back to 90 %: resolved. No message, only the phone's notification cleared.
    hass.states.async_set("sensor.kitchen_ht_battery", "90", BATTERY)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert sent_messages(calls) == ["Kitchen H&T: battery critical (5 %)", "clear_notification"]
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
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await past_grace(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)

    # The Shelly H&T's only primary entity drops out: offline, if it lasts.
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await advance(hass, freezer, timedelta(minutes=3))
    assert calls == []
    assert events == []

    await advance(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES))
    assert sent_messages(calls) == ["Kitchen H&T: offline"]
    assert events[0].data["issue"] == "offline"

    # The plug blips for two minutes and comes back: nothing, not even an event.
    calls.clear()
    events.clear()
    hass.states.async_set("switch.office_plug", "unavailable")
    hass.states.async_set("sensor.office_plug_power", "unavailable")
    await advance(hass, freezer, timedelta(minutes=2))
    hass.states.async_set("switch.office_plug", "on")
    hass.states.async_set("sensor.office_plug_power", "4.2")
    await advance(hass, freezer, timedelta(minutes=10))
    assert calls == []
    assert [e for e in events if e.data["name"] == "Office Plug"] == []


async def test_a_restart_never_resends(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await past_grace(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert len(calls) == 1
    await advance(hass, freezer, timedelta(seconds=5))  # the store's save delay

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await past_grace(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=10))
    assert len(calls) == 1


async def test_saving_options_does_not_announce_anything(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The reload after an options save records a fresh baseline, without a new grace period."""
    entry, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await past_grace(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)

    result = await open_general_options(hass, entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "thresholds": {"battery_warning": 60, "battery_critical": 50},
            "notifications": NOTIFY_OPTIONS,
        },
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    attention = hass.states.get("sensor.pulse_check_attention")
    assert attention is not None
    assert attention.state == "9"

    await past_grace(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=10))
    assert calls == []
    assert [e for e in events if e.data["kind"] == "entered"] == []


async def test_reminders_while_unresolved(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Baseline problems are never announced, but reminders still reach the user."""
    _, _, calls = await set_up_notify(
        hass, fixture_snapshot, freezer, fixed_now, {**NOTIFY_OPTIONS, CONF_REMINDER_DAYS: 1}
    )
    await past_grace(hass, freezer)
    assert calls == []

    await advance(hass, freezer, timedelta(days=1, minutes=1))
    reminders = [m for m in sent_messages(calls) if m.startswith("Still unresolved")]
    # The motion sensor, the smoke alarm and the remote. Not the dead lock:
    # never seen online in this run, so never recorded as offline.
    assert len(reminders) == 3
    assert "Still unresolved after 1 day. Living Room Motion: battery critical (12 %)" in reminders

    # Not again until another interval has passed.
    calls.clear()
    await advance(hass, freezer, timedelta(hours=6))
    assert calls == []


async def test_digests_list_devices_on_that_policy(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await set_up_notify(
        hass, fixture_snapshot, freezer, fixed_now, {**NOTIFY_OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    )
    await past_grace(hass, freezer)

    # Past 09:00 local (16:00 UTC), the first digest time after the start.
    freezer.move_to(fixed_now + timedelta(hours=23))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    daily = [m for m in sent_messages(calls) if m.startswith("Pulse Check daily digest")]
    assert len(daily) == 1
    assert "- Bedroom Temp & Humidity: battery low (28 %)" in daily[0]
    assert "- Garage Multisensor: not heard from for" in daily[0]
    assert "Front Door Lock" not in daily[0]  # instant, not in the digest
    assert not any(m.startswith("Pulse Check weekly digest") for m in sent_messages(calls))


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
    _, device_ids, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await hass.services.async_call(
        DOMAIN,
        "set_device_settings",
        {"device_id": device_ids["dev_shelly_ht"], "notify_policy": "none"},
        blocking=True,
    )
    await past_grace(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)

    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert calls == []
    assert events[0].data["policy"] == "none"  # the event still fires for automations


# -- catching up missed digests -----------------------------------------------


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
    entry, _, calls = await set_up_notify(
        hass, fixture_snapshot, freezer, fixed_now, {**NOTIFY_OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    )
    await past_grace(hass, freezer)

    # Off from Thursday 03:00 to Saturday 10:00: three daily slots go by.
    await restart_ha(hass, entry, freezer, local_time(17, 10))
    await advance(hass, freezer, timedelta(minutes=1))
    assert calls == []  # nothing during the grace period
    await past_grace(hass, freezer)
    assert len(digest_messages(calls, "daily")) == 1
    assert "- Bedroom Temp & Humidity: battery low (28 %)" in digest_messages(calls, "daily")[0]
    # The weekly digest was missed too, but had nothing to say.
    assert digest_messages(calls, "weekly") == []

    # Then the normal schedule: Sunday 09:00.
    await advance(hass, freezer, local_time(18, 9) - dt_util.utcnow())
    assert len(digest_messages(calls, "daily")) == 2


async def test_a_digest_due_during_the_start_is_sent_when_the_grace_period_ends(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, _, calls = await set_up_notify(
        hass, fixture_snapshot, freezer, fixed_now, {**NOTIFY_OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    )
    await past_grace(hass, freezer)

    # A restart at 08:58: the 09:00 digest falls inside the grace period.
    await restart_ha(hass, entry, freezer, local_time(15, 8, 58))
    await advance(hass, freezer, timedelta(minutes=2))
    assert calls == []
    await past_grace(hass, freezer)
    assert len(digest_messages(calls, "daily")) == 1

    # Another restart the same morning does not send it again.
    await restart_ha(hass, entry, freezer, local_time(15, 11))
    await past_grace(hass, freezer)
    assert len(digest_messages(calls, "daily")) == 1


async def test_a_first_run_skips_slots_from_before_the_install(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The weekly all-clear would send on any catch-up; the first start sends nothing."""
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_WARNING: "daily", CONF_WEEKLY_ALL_CLEAR: True}
    entry, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=10))
    assert calls == []

    # Off for a week, back on Thursday afternoon: one of each, and the
    # weekly one keeps its all-clear line.
    await restart_ha(hass, entry, freezer, local_time(22, 12))
    await past_grace(hass, freezer)
    assert len(digest_messages(calls, "daily")) == 1
    assert digest_messages(calls, "weekly") == ["Pulse Check weekly digest\nAll devices OK."]


async def test_a_slot_with_nothing_to_say_still_counts_as_judged(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    """By default nothing is daily, so the daily digest has nothing to say."""
    entry, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await past_grace(hass, freezer)

    await advance(hass, freezer, local_time(15, 9) - dt_util.utcnow())
    assert digest_messages(calls, "daily") == []
    assert len(digest_messages(calls, "weekly")) == 1
    await advance(hass, freezer, timedelta(seconds=5))
    digests = hass_storage["pulse_check.data"]["data"]["digests"]
    assert digests["daily"].startswith("2026-10-15T16:00:00")  # 09:00 Pacific

    await restart_ha(hass, entry, freezer, local_time(15, 9, 30))
    await past_grace(hass, freezer)
    assert digest_messages(calls, "daily") == []
    assert len(digest_messages(calls, "weekly")) == 1
