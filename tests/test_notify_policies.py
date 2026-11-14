"""Who gets told what, and when: policies, snoozes, targets and the event.

Each test makes the Kitchen H&T's battery fail and checks one routing rule
the README promises. The rest of the fixture's problems are a baseline from
the start and stay quiet, apart from reminders, so assertions filter on the
kitchen sensor.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.pulse_check.const import (
    CONF_DIGEST_WEEKDAY,
    CONF_NOTIFY_CRITICAL,
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_MAX,
    DEBOUNCE_SECONDS,
    DOMAIN,
    EVENT_TRANSITION,
)
from custom_components.pulse_check.notify import SEND_ATTEMPTS, SEND_RETRY, TITLE
from tests.helpers import (
    BATTERY,
    NOTIFY_OPTIONS,
    advance,
    device_dict,
    past_grace,
    sent_messages,
    set_up_notify,
)

KITCHEN = "Kitchen H&T"
BLUEPRINT = (
    Path(__file__).parent.parent
    / "blueprints"
    / "automation"
    / "pulse_check"
    / "transition_notify.yaml"
)
# 09:00 local (US/Pacific) on the fixture's Thursday, 15 October 2026.
DIGEST_HOUR_UTC = 16


async def _battery(hass: HomeAssistant, freezer: FrozenDateTimeFactory, level: str) -> None:
    """Set the kitchen sensor's battery and let the debounced recompute run."""
    hass.states.async_set("sensor.kitchen_ht_battery", level, BATTERY)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))


async def _policy(hass: HomeAssistant, device_id: str, policy: str) -> None:
    await hass.services.async_call(
        DOMAIN,
        "set_device_settings",
        {"device_id": device_id, "notify_policy": policy},
        blocking=True,
    )


async def _at_digest(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, fixed_now: datetime, days: int = 0
) -> None:
    """Move to just after 09:00 local, `days` after the fixture's Thursday."""
    freezer.move_to(fixed_now.replace(hour=DIGEST_HOUR_UTC, minute=1) + timedelta(days=days))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def _digests(calls: list[Any], kind: str) -> list[str]:
    return [m for m in sent_messages(calls) if m.startswith(f"Pulse Check {kind} digest")]


def _kitchen(messages: list[str]) -> list[str]:
    return [m for m in messages if KITCHEN in m]


# -- snoozing ------------------------------------------------------------------


async def test_a_snoozed_device_stops_notifying(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Snooze resolves the issue: no reminders, and nothing in the digest."""
    options = {**NOTIFY_OPTIONS, CONF_REMINDER_DAYS: 1}
    _, device_ids, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)
    await _battery(hass, freezer, "5")
    assert _kitchen(sent_messages(calls)) == ["Kitchen H&T: battery critical (5 %)"]

    await hass.services.async_call(
        DOMAIN, "snooze", {"device_id": device_ids["dev_shelly_ht"], "days": 7}, blocking=True
    )
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    kitchen_events = [
        (e.data["kind"], e.data["issue"]) for e in events if e.data["name"] == KITCHEN
    ]
    assert kitchen_events == [("entered", "battery_critical"), ("resolved", "battery_critical")]

    calls.clear()
    for _ in range(3):
        await advance(hass, freezer, timedelta(days=1, minutes=1))
    assert _kitchen(sent_messages(calls)) == []


async def test_a_snoozed_device_is_left_out_of_the_digest(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    _, device_ids, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "25")
    await hass.services.async_call(
        DOMAIN, "snooze", {"device_id": device_ids["dev_shelly_ht"], "days": 7}, blocking=True
    )
    await _at_digest(hass, freezer, fixed_now)
    [daily] = _digests(calls, "daily")
    assert "- Bedroom Temp & Humidity: battery low (28 %)" in daily  # the digest itself works
    assert KITCHEN not in daily


# -- policies ------------------------------------------------------------------


async def test_critical_on_the_daily_digest_is_not_sent_at_once(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_CRITICAL: "daily"}
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    assert _kitchen(sent_messages(calls)) == []

    await _at_digest(hass, freezer, fixed_now)
    [daily] = _digests(calls, "daily")
    assert "- Kitchen H&T: battery critical (5 %)" in daily


async def test_a_device_policy_of_instant_beats_the_weekly_default(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A warning normally waits for the weekly digest; this device's goes out at once."""
    _, device_ids, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await _policy(hass, device_ids["dev_shelly_ht"], "instant")
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "25")
    assert _kitchen(sent_messages(calls)) == ["Kitchen H&T: battery low (25 %)"]


async def test_a_device_policy_of_daily_holds_a_critical_for_the_daily_digest(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, device_ids, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await _policy(hass, device_ids["dev_shelly_ht"], "daily")
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    assert _kitchen(sent_messages(calls)) == []

    await _at_digest(hass, freezer, fixed_now)
    [daily] = _digests(calls, "daily")
    assert "- Kitchen H&T: battery critical (5 %)" in daily


async def test_a_device_policy_of_weekly_puts_it_in_the_weekly_digest_only(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_WARNING: "daily"}
    _, device_ids, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await _policy(hass, device_ids["dev_shelly_ht"], "weekly")
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    assert _kitchen(sent_messages(calls)) == []

    await _at_digest(hass, freezer, fixed_now)  # Thursday: both digests are due
    [daily] = _digests(calls, "daily")
    [weekly] = _digests(calls, "weekly")
    assert KITCHEN not in daily
    assert "- Kitchen H&T: battery critical (5 %)" in weekly


async def test_reminders_stop_at_the_maximum(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**NOTIFY_OPTIONS, CONF_REMINDER_DAYS: 1, CONF_REMINDER_MAX: 2}
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    for _ in range(5):
        await advance(hass, freezer, timedelta(days=1, minutes=1))
    reminders = [m for m in _kitchen(sent_messages(calls)) if m.startswith("Still unresolved")]
    assert len(reminders) == 2


async def test_the_weekly_digest_waits_for_its_weekday(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Weekly on Monday: nothing from Thursday to Sunday, one on Monday."""
    options = {**NOTIFY_OPTIONS, CONF_DIGEST_WEEKDAY: "monday"}
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    for day in range(4):  # Thursday 15th to Sunday 18th
        await _at_digest(hass, freezer, fixed_now, days=day)
    assert _digests(calls, "weekly") == []

    await _at_digest(hass, freezer, fixed_now, days=4)  # Monday 19th
    [weekly] = _digests(calls, "weekly")
    assert "- Bedroom Temp & Humidity: battery low (28 %)" in weekly


# -- targets -------------------------------------------------------------------


async def test_a_notify_entity_target_gets_send_message(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A notify entity (not a legacy notify service) is sent to through notify.send_message."""
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_TARGETS: ["notify.family_email"]}
    _, _, legacy = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    hass.states.async_set("notify.family_email", "unknown")
    send = async_mock_service(hass, "notify", "send_message")
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    assert legacy == []
    assert [call.data for call in send] == [
        {
            "entity_id": "notify.family_email",
            "title": TITLE,
            "message": "Kitchen H&T: battery critical (5 %)",
        }
    ]


async def test_a_message_no_target_accepts_is_given_up_after_its_attempts(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Tried `SEND_ATTEMPTS` times, then counted as sent: a target added later gets no backlog."""
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_TARGETS: ["notify.late_phone"]}
    await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")  # attempt 1
    for _ in range(SEND_ATTEMPTS - 1):  # the rest, one retry interval apart
        await advance(hass, freezer, SEND_RETRY + timedelta(seconds=1))

    late = async_mock_service(hass, "notify", "late_phone")
    await advance(hass, freezer, SEND_RETRY + timedelta(seconds=1))
    await advance(hass, freezer, SEND_RETRY + timedelta(seconds=1))
    assert _kitchen(sent_messages(late)) == []


# -- the event -----------------------------------------------------------------


async def test_each_transition_writes_a_logbook_line(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Whatever the policy, so a device left to a digest has its history too."""
    options = {**NOTIFY_OPTIONS, CONF_NOTIFY_CRITICAL: "none"}
    _, device_ids, _ = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    lines = async_capture_events(hass, EVENT_LOGBOOK_ENTRY)
    await _battery(hass, freezer, "5")
    await _battery(hass, freezer, "90")
    assert [line.data for line in lines] == [
        {
            "name": KITCHEN,
            "message": message,
            "domain": DOMAIN,
            "device_id": device_ids["dev_shelly_ht"],
        }
        for message in ("battery critical (5 %)", "battery critical resolved")
    ]


async def test_the_transition_event_carries_every_documented_field(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Automations and the shipped blueprint read these; a rename would silence them."""
    _, device_ids, _ = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now)
    await past_grace(hass, freezer)
    events = async_capture_events(hass, EVENT_TRANSITION)
    await _battery(hass, freezer, "5")
    [event] = [e.data for e in events if e.data["name"] == KITCHEN]
    kitchen = device_dict(hass, KITCHEN)
    assert event == {
        "device_id": device_ids["dev_shelly_ht"],
        "name": KITCHEN,
        "area": kitchen.get("area"),
        "integration": "shelly",
        "issue": "battery_critical",
        "kind": "entered",
        "severity": "critical",
        "message": "Kitchen H&T: battery critical (5 %)",
        "policy": "instant",
        "level": 5,
        "maintenance": False,
    }
    assert event["area"] is not None  # the fixture's kitchen has an area

    # The blueprint reads only fields the event carries.
    text = BLUEPRINT.read_text(encoding="utf-8")
    used = {
        word.split(".", 1)[0].split()[0].split("|")[0]
        for word in text.split("trigger.event.data.")[1:]
    }
    assert used <= set(event)


def test_the_blueprint_still_parses() -> None:
    """A YAML error in the shipped blueprint fails here, not in a user's import."""
    blueprint = load_yaml_dict(str(BLUEPRINT))
    assert blueprint["blueprint"]["domain"] == "automation"


async def test_a_digest_no_target_accepts_is_tried_again(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A phone offline at 09:00 still gets the day's digest when it is back."""
    options = {
        **NOTIFY_OPTIONS,
        CONF_NOTIFY_CRITICAL: "daily",
        CONF_NOTIFY_TARGETS: ["notify.late_phone"],
    }
    await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    await _battery(hass, freezer, "5")
    await _at_digest(hass, freezer, fixed_now)  # no such service yet: it fails

    late = async_mock_service(hass, "notify", "late_phone")
    await advance(hass, freezer, SEND_RETRY + timedelta(seconds=1))
    [daily] = _digests(late, "daily")
    assert "- Kitchen H&T: battery critical (5 %)" in daily
    # Sent once: no further retries.
    await advance(hass, freezer, SEND_RETRY + timedelta(seconds=1))
    assert len(_digests(late, "daily")) == 1
