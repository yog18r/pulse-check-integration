"""A problem's phone notification is cleared once the problem is gone.

Each message about one issue carries a tag; a reminder reuses it, so it
replaces the earlier notification. When the issue resolves, companion-app
targets get `clear_notification` with that tag, unless the option is off.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.pulse_check.const import (
    CONF_CLEAR_RESOLVED,
    CONF_CONFIRM_MINUTES,
    CONF_NOTIFY_CRITICAL,
    CONF_NOTIFY_TARGETS,
    CONF_REMINDER_DAYS,
    DEBOUNCE_SECONDS,
    DOMAIN,
)
from tests.helpers import (
    BATTERY,
    NOTIFY_OPTIONS,
    TEMPERATURE,
    advance,
    past_grace,
    set_up_notify,
)

CLEAR = "clear_notification"


async def _battery(hass: HomeAssistant, freezer: FrozenDateTimeFactory, level: str) -> None:
    hass.states.async_set("sensor.kitchen_ht_battery", level, BATTERY)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))


def _tag(device_id: str, issue: str) -> str:
    return f"pulse_check:{device_id}:{issue}"


def _clears(calls: list[ServiceCall]) -> list[dict[str, Any]]:
    return [call.data for call in calls if call.data["message"] == CLEAR]


async def test_a_resolved_problem_clears_its_phone_notification(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, device_ids, phone = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    tag = _tag(device_ids["dev_shelly_ht"], "battery_critical")
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    assert [call.data["data"]["tag"] for call in phone] == [tag]
    assert _clears(phone) == []

    await _battery(hass, freezer, "90")
    assert _clears(phone) == [{"message": CLEAR, "data": {"tag": tag}}]


async def test_a_reminder_replaces_the_notification_and_is_cleared_too(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**NOTIFY_OPTIONS, CONF_REMINDER_DAYS: 1}
    _, device_ids, phone = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    tag = _tag(device_ids["dev_shelly_ht"], "battery_critical")
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    await advance(hass, freezer, timedelta(days=1, minutes=1))
    kitchen = [call.data for call in phone if "Kitchen H&T" in call.data["message"]]
    assert [data["message"].startswith("Still unresolved") for data in kitchen] == [False, True]
    assert {data["data"]["tag"] for data in kitchen} == {tag}

    await _battery(hass, freezer, "90")
    assert _clears(phone) == [{"message": CLEAR, "data": {"tag": tag}}]


async def test_snoozing_a_device_clears_its_notification(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The phone's "Snooze 1 day" button leaves nothing behind on the phone."""
    _, device_ids, phone = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    kitchen = device_ids["dev_shelly_ht"]
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    await hass.services.async_call(
        DOMAIN, "snooze", {"device_id": kitchen, "days": 1}, blocking=True
    )
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert _clears(phone) == [
        {"message": CLEAR, "data": {"tag": _tag(kitchen, "battery_critical")}}
    ]


async def test_with_the_option_off_nothing_is_cleared(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**NOTIFY_OPTIONS, CONF_CLEAR_RESOLVED: False}
    _, _, phone = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    await _battery(hass, freezer, "90")
    assert len(phone) == 1
    assert _clears(phone) == []


async def test_other_targets_get_no_tag_and_nothing_to_clear(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """An email can't be taken back, so it gets exactly what it always did."""
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_TARGETS: ["notify.email_test"]}
    await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    email = async_mock_service(hass, "notify", "email_test")
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    await _battery(hass, freezer, "90")
    assert [call.data for call in email] == [
        {"title": "Pulse Check", "message": "Kitchen H&T: battery critical (5 %)"}
    ]


async def test_a_problem_only_in_a_digest_is_not_cleared(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """No notification of its own was sent, so there is nothing to clear."""
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_CRITICAL: "daily"}
    _, _, phone = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    await _battery(hass, freezer, "90")
    assert phone == []


async def test_an_outage_that_heals_within_the_window_sends_and_clears_nothing(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**NOTIFY_OPTIONS, CONF_CONFIRM_MINUTES: 10}
    _, _, phone = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await advance(hass, freezer, timedelta(minutes=2))
    hass.states.async_set("sensor.kitchen_ht_temperature", "21.5", TEMPERATURE)
    await advance(hass, freezer, timedelta(minutes=15))
    assert phone == []
