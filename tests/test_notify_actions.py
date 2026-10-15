"""Buttons on companion-app notifications: the payload, and what each button does."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.pulse_check.const import (
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_MAX,
    DEBOUNCE_SECONDS,
    DOMAIN,
)
from custom_components.pulse_check.notify_actions import (
    EVENT_NOTIFICATION_ACTION,
    is_mobile_app_target,
    notification_actions,
    parse_action_id,
)
from tests.conftest import device_dict
from tests.test_notify import BATTERY, OPTIONS, TEMPERATURE, _local, _ready, _set_up, _tick

TITLES = {
    "MARK_REPLACED": "Mark replaced",
    "MARK_CHARGED": "Mark charged",
    "REMIND_LATER": "Remind me later",
    "SNOOZE_DAY": "Snooze 1 day",
}
BOTH_TARGETS = {**OPTIONS, CONF_NOTIFY_TARGETS: ["notify.mobile_app_test", "notify.email_test"]}


def _actions(call: ServiceCall) -> list[str]:
    return [action["action"] for action in call.data.get("data", {}).get("actions", [])]


async def _press(hass: HomeAssistant, action: str) -> None:
    """What the companion app does when a button is pressed."""
    hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": action})
    await hass.async_block_till_done(wait_background_tasks=True)


async def _kitchen_battery_critical(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))


# -- the identifiers and buttons, without Home Assistant ----------------------


def test_identifiers_carry_the_device_and_survive_colons() -> None:
    assert parse_action_id("PULSE_CHECK_SNOOZE_DAY:entity:sensor.remote") == (
        "SNOOZE_DAY",
        "entity:sensor.remote",
    )
    assert parse_action_id("PULSE_CHECK_MARK_REPLACED:3f2a") == ("MARK_REPLACED", "3f2a")
    assert parse_action_id("PULSE_CHECK_EXPLODE:3f2a") is None
    assert parse_action_id("PULSE_CHECK_SNOOZE_DAY:") is None
    assert parse_action_id("ALARM") is None


def test_only_companion_app_services_get_buttons() -> None:
    assert is_mobile_app_target("notify.mobile_app_pixel_9")
    assert not is_mobile_app_target("notify.email")
    assert not is_mobile_app_target("notify.family_phones")  # a group: plain messages
    assert not is_mobile_app_target("light.mobile_app_lamp")


@pytest.mark.parametrize(
    ("issue", "rechargeable", "another", "verbs"),
    [
        ("battery_critical", False, True, ["MARK_REPLACED", "REMIND_LATER"]),
        ("battery_warning", True, True, ["MARK_CHARGED", "REMIND_LATER"]),
        ("battery_critical", False, False, ["MARK_REPLACED"]),
        ("offline", False, True, ["SNOOZE_DAY"]),
        ("quiet", True, False, ["SNOOZE_DAY"]),
    ],
)
def test_buttons_per_issue(issue: str, rechargeable: bool, another: bool, verbs: list[str]) -> None:
    actions = notification_actions(
        issue, "dev1", rechargeable=rechargeable, another_reminder=another, titles=TITLES
    )
    assert actions == [{"action": f"PULSE_CHECK_{v}:dev1", "title": TITLES[v]} for v in verbs]


# -- what is sent -------------------------------------------------------------


async def test_an_instant_message_has_buttons_on_the_phone_only(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, device_ids, phone = await _set_up(hass, fixture_snapshot, freezer, fixed_now, BOTH_TARGETS)
    email = async_mock_service(hass, "notify", "email_test")
    await _ready(hass, freezer)
    kitchen = device_ids["dev_shelly_ht"]

    await _kitchen_battery_critical(hass, freezer)
    assert len(phone) == 1
    assert phone[0].data == {
        "title": "Pulse Check",
        "message": "Kitchen H&T: battery critical (5 %)",
        "data": {
            "actions": [
                {"action": f"PULSE_CHECK_MARK_REPLACED:{kitchen}", "title": "Mark replaced"},
                {"action": f"PULSE_CHECK_REMIND_LATER:{kitchen}", "title": "Remind me later"},
            ]
        },
    }
    # Any other target gets exactly what it got before buttons existed.
    assert [call.data for call in email] == [
        {"title": "Pulse Check", "message": "Kitchen H&T: battery critical (5 %)"}
    ]

    # Offline: a snooze button.
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    await _tick(hass, freezer, timedelta(minutes=6))
    assert phone[-1].data["message"] == "Kitchen H&T: offline"
    assert _actions(phone[-1]) == [f"PULSE_CHECK_SNOOZE_DAY:{kitchen}"]


async def test_a_rechargeable_device_offers_mark_charged(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, device_ids, phone = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    kitchen = device_ids["dev_shelly_ht"]
    await hass.services.async_call(
        DOMAIN, "set_device_settings", {"device_id": kitchen, "rechargeable": True}, blocking=True
    )
    await _ready(hass, freezer)
    await _kitchen_battery_critical(hass, freezer)
    assert _actions(phone[0]) == [
        f"PULSE_CHECK_MARK_CHARGED:{kitchen}",
        f"PULSE_CHECK_REMIND_LATER:{kitchen}",
    ]


async def test_the_last_reminder_does_not_promise_another(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**OPTIONS, CONF_REMINDER_DAYS: 1, CONF_REMINDER_MAX: 1}
    _, device_ids, phone = await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    await _tick(hass, freezer, timedelta(days=1, minutes=1))
    motion = device_ids["dev_z2m_motion"]
    reminder = next(c for c in phone if "Living Room Motion" in c.data["message"])
    assert reminder.data["message"].startswith("Still unresolved")
    assert _actions(reminder) == [f"PULSE_CHECK_MARK_REPLACED:{motion}"]


async def test_digests_have_no_buttons(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    _, _, phone = await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    await _tick(hass, freezer, _local(15, 9, 1) - fixed_now)
    digests = [c for c in phone if c.data["message"].startswith("Pulse Check daily digest")]
    assert len(digests) == 1
    assert "data" not in digests[0].data


# -- what the buttons do ------------------------------------------------------


async def test_snooze_1_day(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, device_ids, _ = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _press(hass, f"PULSE_CHECK_SNOOZE_DAY:{device_ids['dev_zwave_lock']}")
    lock = device_dict(hass, "Front Door Lock")
    assert lock["severity"] == "ok"
    assert lock["snoozedUntil"] == "2026-10-16T10:00:00.000Z"


async def test_mark_replaced_and_mark_charged(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, device_ids, _ = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    history = entry.runtime_data.store.history
    motion, phone = device_ids["dev_z2m_motion"], device_ids["dev_phone"]

    await _press(hass, f"PULSE_CHECK_MARK_REPLACED:{motion}")
    assert [e["kind"] for e in history[motion]["events"]] == ["replaced"]
    await _press(hass, f"PULSE_CHECK_MARK_CHARGED:{phone}")
    assert [e["kind"] for e in history[phone]["events"]] == ["charged"]


async def test_remind_me_later_keeps_the_reminder_schedule(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**OPTIONS, CONF_REMINDER_DAYS: 1}
    entry, device_ids, phone = await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    kitchen = device_ids["dev_shelly_ht"]
    await _kitchen_battery_critical(hass, freezer)
    record = dict(entry.runtime_data.store.notify[kitchen]["battery_critical"])

    await _press(hass, f"PULSE_CHECK_REMIND_LATER:{kitchen}")
    assert entry.runtime_data.store.notify[kitchen]["battery_critical"] == record
    assert len(phone) == 1

    # The reminder comes when it would have anyway: a day after the message.
    await _tick(hass, freezer, timedelta(hours=23))
    assert len(phone) == 1
    await _tick(hass, freezer, timedelta(hours=1, minutes=1))
    kitchen_messages = [c.data["message"] for c in phone if "Kitchen" in c.data["message"]]
    assert kitchen_messages == [
        "Kitchen H&T: battery critical (5 %)",
        "Still unresolved after 1 days. Kitchen H&T: battery critical (5 %)",
    ]


async def test_stale_and_foreign_buttons_are_harmless(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry, _, _ = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    snoozes = dict(entry.runtime_data.store.data["snoozes"])
    await _press(hass, "PULSE_CHECK_SNOOZE_DAY:a-device-that-was-removed")
    assert "Notification button PULSE_CHECK_SNOOZE_DAY:a-device-that-was-removed failed" in (
        caplog.text
    )
    await _press(hass, "ALARM")  # another automation's button
    assert entry.runtime_data.store.data["snoozes"] == snoozes
