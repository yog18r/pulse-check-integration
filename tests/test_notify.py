"""Notifications: startup baseline, confirmation window, transitions, reminders, digests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
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
    DEFAULT_CONFIRM_MINUTES,
    DEFAULT_STARTUP_GRACE_MINUTES,
    DOMAIN,
    EVENT_TRANSITION,
)
from tests.conftest import load_fixture_into_hass

OPTIONS = {
    CONF_NOTIFY_TARGETS: ["notify.mobile_app_test"],
    CONF_DIGEST_TIME: "09:00:00",
    CONF_DIGEST_WEEKDAY: "thursday",  # 2026-10-15 is a Thursday
}
BATTERY = {"device_class": "battery", "unit_of_measurement": "%"}
TEMPERATURE = {"device_class": "temperature", "unit_of_measurement": "°C"}


def _messages(calls: list[ServiceCall]) -> list[str]:
    return [call.data["message"] for call in calls]


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    """Advance time and let timers and the debounced refresh run."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


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
    await hass.async_block_till_done()
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
    await _tick(hass, freezer, timedelta(seconds=3))  # a recompute during startup
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
    await _tick(hass, freezer, timedelta(seconds=3))  # the recompute that first sees it
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
    await _tick(hass, freezer, timedelta(seconds=3))
    assert _messages(calls) == ["Kitchen H&T: battery critical (5 %)"]

    # Another recompute changes nothing: no repeats.
    await _tick(hass, freezer, timedelta(minutes=6))
    assert len(calls) == 1

    # Back to 90 %: resolved, event only, no message.
    hass.states.async_set("sensor.kitchen_ht_battery", "90", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=3))
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
    await _tick(hass, freezer, timedelta(seconds=3))
    assert len(calls) == 1
    await _tick(hass, freezer, timedelta(seconds=5))  # the store's save delay

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
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
    await hass.async_block_till_done()
    attention = hass.states.get("sensor.pulse_check_attention")
    assert attention is not None
    assert attention.state == "8"

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
    assert "Still unresolved after 1 days. Living Room Motion: battery critical (12 %)" in reminders

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

    # 09:00 local the next day (the test instance runs in UTC).
    freezer.move_to(fixed_now + timedelta(hours=23))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
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
    await _tick(hass, freezer, timedelta(seconds=3))
    assert calls == []
    assert events[0].data["policy"] == "none"  # the event still fires for automations
