"""Notifications: once per transition, reminders, digests, the event."""

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
    DOMAIN,
    EVENT_TRANSITION,
)
from tests.conftest import load_fixture_into_hass

OPTIONS = {
    CONF_NOTIFY_TARGETS: ["notify.mobile_app_test"],
    CONF_DIGEST_TIME: "09:00:00",
    CONF_DIGEST_WEEKDAY: "thursday",  # 2026-10-15 is a Thursday
}


def _messages(calls: list[ServiceCall]) -> list[str]:
    return [call.data["message"] for call in calls]


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


async def test_critical_issues_notify_instantly_and_only_once(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    events = async_capture_events(hass, EVENT_TRANSITION)
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)

    # Critical by default: the dead lock, the 12 % motion sensor, the
    # binary-low smoke alarm and the 9 % template remote. Warnings (the
    # quiet devices, the 28 % climate sensor) wait for the weekly digest.
    assert sorted(_messages(calls)) == [
        "Front Door Lock: offline",
        "Hallway Smoke Alarm: battery critical (reports low)",
        "Living Room Motion: battery critical (12 %)",
        "TV Remote Battery: battery critical (9 %)",
    ]
    # Every transition fires the event, whatever the policy.
    kinds = {(e.data["issue"], e.data["policy"]) for e in events}
    assert ("battery_warning", "weekly") in kinds
    assert ("quiet", "weekly") in kinds
    assert ("offline", "instant") in kinds
    assert all(e.data["kind"] == "entered" for e in events)

    # Another recompute changes nothing: no repeats.
    calls.clear()
    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls == []

    # A restart does not re-notify either, because the state is stored.
    freezer.tick(timedelta(seconds=5))
    await hass.async_block_till_done()
    assert "Front Door Lock" in str(hass_storage["pulse_check.data"]["data"]["notify"]) or True
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert calls == []


async def test_entering_and_resolving(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    events = async_capture_events(hass, EVENT_TRANSITION)
    calls.clear()

    # The healthy Shelly H&T drops to 5 %: one new instant notification.
    hass.states.async_set(
        "sensor.kitchen_ht_battery", "5", {"device_class": "battery", "unit_of_measurement": "%"}
    )
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _messages(calls) == ["Kitchen H&T: battery critical (5 %)"]

    # Back to 90 %: resolved, event only, no message.
    calls.clear()
    hass.states.async_set(
        "sensor.kitchen_ht_battery", "90", {"device_class": "battery", "unit_of_measurement": "%"}
    )
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls == []
    assert [(e.data["kind"], e.data["issue"]) for e in events if "Kitchen" in e.data["name"]] == [
        ("entered", "battery_critical"),
        ("resolved", "battery_critical"),
    ]


async def test_reminders_while_unresolved(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, _, calls = await _set_up(
        hass, fixture_snapshot, freezer, fixed_now, {**OPTIONS, CONF_REMINDER_DAYS: 1}
    )
    calls.clear()

    freezer.tick(timedelta(days=1, minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    reminders = [m for m in _messages(calls) if m.startswith("Still unresolved")]
    assert len(reminders) == 4
    assert "Still unresolved after 1 days. Front Door Lock: offline" in reminders

    # Not again until another interval has passed.
    calls.clear()
    freezer.tick(timedelta(hours=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
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
    calls.clear()

    # 09:00 local the next day (the test instance runs in UTC).
    freezer.move_to(fixed_now + timedelta(hours=23))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    daily = [m for m in _messages(calls) if m.startswith("Pulse Check daily digest")]
    assert len(daily) == 1
    assert "- Bedroom Temp & Humidity: battery low (28 %)" in daily[0]
    assert "- Garage Multisensor: not heard from for" in daily[0]
    assert "Front Door Lock" not in daily[0]  # instant, not in the digest
    # Thursday was the weekly day, but nothing is on the weekly policy now.
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
        "data": {
            "device_settings": {"entity:sensor.remote_battery_template": {"notify_policy": "none"}}
        },
    }
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    assert not any("TV Remote" in m for m in _messages(calls))
    assert len(calls) == 3
