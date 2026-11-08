"""Fixes from the 0.2.9 code review: overlapping runs, failed sends, reloads, snapshots."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.pulse_check.const import (
    CONF_INTEGRATION_LIMIT,
    CONF_NOTIFY_TARGETS,
    CONF_RESTART_TIMEOUT_MINUTES,
    CONF_STARTUP_GRACE_MINUTES,
    DEBOUNCE_SECONDS,
    DEFAULT_CONFIRM_MINUTES,
    DOMAIN,
)
from custom_components.pulse_check.coordinator import build_snapshot
from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices
from custom_components.pulse_check.notify import DATA_RUNTIME, SEND_RETRY
from tests.test_integration_limit import _ht_offline, _plug_offline
from tests.test_notify import (
    BATTERY,
    OPTIONS,
    TEMPERATURE,
    _messages,
    _ready,
    _set_up,
    _tick,
)

TARGET = "notify.mobile_app_test"


async def _debounce(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the debounced recompute run, without waiting for the notifier's task."""
    freezer.tick(timedelta(seconds=DEBOUNCE_SECONDS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


# -- overlapping evaluations ---------------------------------------------------


async def test_a_slow_send_does_not_announce_twice(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A second recompute while the first is still sending waits for it."""
    entry, _, _ = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    gate = asyncio.Event()
    sent: list[str] = []

    async def slow(call: ServiceCall) -> None:
        await gate.wait()
        sent.append(call.data["message"])

    hass.services.async_register("notify", "mobile_app_test", slow)

    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _debounce(hass, freezer)  # the first run is now stuck sending
    # A second recompute meanwhile (a service call, the five-minute timer).
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    gate.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert sent == ["Kitchen H&T: battery critical (5 %)"]


# -- failed sends --------------------------------------------------------------


async def test_a_failed_send_is_retried_and_raises_a_repair_issue(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    working = False
    sent: list[str] = []

    async def flaky(call: ServiceCall) -> None:
        if not working:
            raise HomeAssistantError("phone unreachable")
        sent.append(call.data["message"])

    hass.services.async_register("notify", "mobile_app_test", flaky)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    issues = ir.async_get(hass)
    issue = issues.async_get_issue(DOMAIN, f"notify_failed_{TARGET}")
    assert issue is not None
    assert issue.translation_placeholders == {"target": TARGET, "error": "phone unreachable"}

    # The target works again; the message goes out at the next retry.
    working = True
    await _tick(hass, freezer, SEND_RETRY + timedelta(minutes=5))
    assert sent == ["Kitchen H&T: battery critical (5 %)"]
    assert issues.async_get_issue(DOMAIN, f"notify_failed_{TARGET}") is None


async def test_a_missing_target_raises_a_repair_issue(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {**OPTIONS, CONF_NOTIFY_TARGETS: ["notify.old_phone"]}
    await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "notify_target_missing_notify.old_phone")
    assert issue is not None
    assert issue.translation_key == "notify_target_missing"


async def test_no_targets_is_not_a_failure(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    options = {k: v for k, v in OPTIONS.items() if k != CONF_NOTIFY_TARGETS}
    await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert ir.async_get(hass).issues == {}


# -- reloads and the restart timeout -------------------------------------------


async def test_saving_options_keeps_watching(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A device that fails just after an options save is still announced."""
    entry, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "thresholds": {"battery_warning": 30, "battery_critical": 15},
            # A longer quiet period after start does not start another one.
            "notifications": {**OPTIONS, CONF_STARTUP_GRACE_MINUTES: 30},
        },
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    await _tick(hass, freezer, timedelta(minutes=1))

    hass.states.async_set("sensor.kitchen_ht_temperature", "unavailable", TEMPERATURE)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert _messages(calls) == ["Kitchen H&T: offline"]


async def test_a_timeout_inside_the_grace_period_still_announces(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A one-minute timeout must not let the baseline swallow the dead lock."""
    options = {**OPTIONS, CONF_RESTART_TIMEOUT_MINUTES: 1}
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    assert calls == []
    await _tick(hass, freezer, timedelta(minutes=2))
    await _tick(hass, freezer, timedelta(minutes=DEFAULT_CONFIRM_MINUTES + 1))
    assert _messages(calls) == ["Front Door Lock: offline since the restart"]


# -- the snapshot -----------------------------------------------------------------


async def test_a_child_device_is_a_device_of_its_own(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    entry = MockConfigEntry(domain="hub", state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    parent = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("hub", "parent")},
        name="Hub",
        manufacturer="Acme",
    )
    devices.async_update_device(parent.id, area_id="garage")
    child = devices.async_get_or_create_child(
        config_entry_id=entry.entry_id,
        identifiers={("hub", "child")},
        name="Hub sensor port",
        parent_device_id=parent.id,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "hub", "port-1", config_entry=entry, device_id=child.id
    )
    hass.states.async_set(entity.entity_id, "unavailable")

    snapshot = build_snapshot(hass)
    assert snapshot["devices"][child.id]["name"] == "Hub sensor port"
    assert snapshot["devices"][child.id]["manufacturer"] == "Acme"
    assert snapshot["devices"][child.id]["area_id"] == "garage"
    [health] = [
        d
        for d in analyse_devices(snapshot, CoreConfig(), datetime.now(UTC))
        if d.device_id == child.id
    ]
    assert health.source == "device"
    assert health.is_offline
    # Nothing a child does not have is asked for (that logs a deprecation).
    assert "ChildDeviceEntry" not in caplog.text


async def test_a_yaml_leftover_is_not_provided_once_its_platform_runs(
    hass: HomeAssistant,
) -> None:
    """A template sensor removed from YAML keeps a registry entry and a placeholder."""
    registry = er.async_get(hass)
    entity = registry.async_get_or_create("sensor", "template", "old-sensor")
    hass.states.async_set(entity.entity_id, "unavailable", {"restored": True})
    assert "not_provided" not in build_snapshot(hass)["entities"][entity.entity_id]

    hass.config.components.add("template.sensor")  # the platform set up fine
    assert build_snapshot(hass)["entities"][entity.entity_id]["not_provided"] is True


# -- own entities never decide ----------------------------------------------------


def test_pulse_check_entities_on_a_device_are_ignored() -> None:
    """The per-device sensors update every run; they must not make a device look alive."""
    long_ago = "2026-09-01T00:00:00.000Z"
    just_now = "2026-11-08T11:59:00.000Z"

    def state(entity_id: str, value: str, at: str, **attributes: Any) -> dict[str, Any]:
        return {
            "entity_id": entity_id,
            "state": value,
            "attributes": attributes,
            "last_changed": at,
            "last_updated": at,
            "last_reported": at,
        }

    snapshot: Snapshot = {
        "states": {  # type: ignore[typeddict-item]
            "sensor.door_battery": state(
                "sensor.door_battery", "60", long_ago, device_class="battery"
            ),
            "sensor.door_battery_days_left": state("sensor.door_battery_days_left", "40", just_now),
            "sensor.door_battery_last_replaced": state(
                "sensor.door_battery_last_replaced", "x", just_now
            ),
        },
        "entities": {
            "sensor.door_battery": {
                "entity_id": "sensor.door_battery",
                "device_id": "dev",
                "platform": "zha",
            },
            "sensor.door_battery_days_left": {
                "entity_id": "sensor.door_battery_days_left",
                "device_id": "dev",
                "platform": "pulse_check",
                "entity_category": "diagnostic",
            },
            "sensor.door_battery_last_replaced": {
                "entity_id": "sensor.door_battery_last_replaced",
                "device_id": "dev",
                "platform": "pulse_check",
                "entity_category": "diagnostic",
            },
        },
        "devices": {
            "dev": {  # type: ignore[typeddict-item]
                "id": "dev",
                "name": "Door",
                "name_by_user": None,
                "manufacturer": None,
                "model": None,
                "area_id": None,
                "entry_type": None,
                "disabled_by": None,
            }
        },
        "areas": {},
    }
    [door] = analyse_devices(snapshot, CoreConfig(), datetime(2026, 11, 8, 12, 0, tzinfo=UTC))
    assert door.integration == "zha"  # not "pulse_check", which would drop it
    assert door.is_quiet
    assert door.entity_ids == ["sensor.door_battery"]


# -- second review -------------------------------------------------------------


async def test_held_messages_wait_between_failed_attempts(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A failing target is tried every 15 minutes, not on every evaluation."""
    options = {**OPTIONS, CONF_INTEGRATION_LIMIT: 1}
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now, options)
    await _ready(hass, freezer)
    await _plug_offline(hass, freezer)
    await _ht_offline(hass, freezer)  # held: the allowance is used up
    assert _messages(calls) == ["Office Plug: offline"]

    attempts = 0
    working = False
    sent: list[str] = []

    async def flaky(call: ServiceCall) -> None:
        nonlocal attempts
        attempts += 1
        if not working:
            raise HomeAssistantError("phone unreachable")
        sent.append(call.data["message"])

    hass.services.async_register("notify", "mobile_app_test", flaky)
    await _tick(hass, freezer, timedelta(minutes=65))  # the hour is up: first try
    assert attempts == 1
    for _ in range(2):  # evaluations in between do not try again
        await _tick(hass, freezer, timedelta(minutes=5))
    assert attempts == 1

    working = True
    await _tick(hass, freezer, SEND_RETRY)
    assert attempts == 2
    assert sent == ["shelly: 1 more device offline or not heard from:\n- Kitchen H&T: offline"]


async def test_a_timeout_names_itself_in_the_repair(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)

    async def hangs(call: ServiceCall) -> None:
        raise TimeoutError

    hass.services.async_register("notify", "mobile_app_test", hangs)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"notify_failed_{TARGET}")
    assert issue is not None
    assert issue.translation_placeholders == {"target": TARGET, "error": "TimeoutError"}


async def test_removing_a_broken_target_clears_its_repair(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        "notify_failed_notify.old_phone",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="notify_failed",
        translation_placeholders={"target": "notify.old_phone", "error": "gone"},
    )
    await _set_up(hass, fixture_snapshot, freezer, fixed_now)  # targets: mobile_app_test only
    assert ir.async_get(hass).async_get_issue(DOMAIN, "notify_failed_notify.old_phone") is None


async def test_a_snooze_just_before_a_reload_is_kept(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The old store's delayed save must not be overwritten by the new one."""
    entry, device_ids, _ = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    kitchen = device_ids["dev_shelly_ht"]
    await hass.services.async_call(
        DOMAIN, "snooze", {"device_id": kitchen, "days": 1}, blocking=True
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert kitchen in entry.runtime_data.store.data["snoozes"]


async def test_a_mark_during_a_pending_rise_starts_from_before_it(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, device_ids, _ = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    kitchen = device_ids["dev_shelly_ht"]
    for level in ("40", "100"):  # a new cell fitted; the rise is not confirmed yet
        hass.states.async_set("sensor.kitchen_ht_battery", level, BATTERY)
        await _tick(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    await hass.services.async_call(DOMAIN, "mark_replaced", {"device_id": kitchen}, blocking=True)
    event = entry.runtime_data.replacements.last_event(kitchen)
    assert event is not None
    assert event["level_before"] == 40
    assert "jump" not in entry.runtime_data.store.levels[kitchen]


async def test_a_deleted_yaml_automation_is_not_provided(hass: HomeAssistant) -> None:
    """Integrations that are their own domain are listed under their name alone."""
    registry = er.async_get(hass)
    entity = registry.async_get_or_create("automation", "automation", "old-automation")
    hass.states.async_set(entity.entity_id, "unavailable", {"restored": True})
    hass.config.components.add("automation")
    assert build_snapshot(hass)["entities"][entity.entity_id]["not_provided"] is True


async def test_removing_the_integration_cleans_up(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    entry, device_ids, _ = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await hass.services.async_call(
        DOMAIN, "snooze", {"device_id": device_ids["dev_shelly_ht"], "days": 1}, blocking=True
    )
    await _tick(hass, freezer, timedelta(seconds=5))
    assert "pulse_check.data" in hass_storage
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"notify_failed_{TARGET}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="notify_failed",
        translation_placeholders={"target": TARGET, "error": "x"},
    )
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert "pulse_check.data" not in hass_storage
    assert DATA_RUNTIME not in hass.data
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"notify_failed_{TARGET}") is None
