"""Mark charged: the battery counts as charging until it has caught up."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.pulse_check.const import DEBOUNCE_SECONDS, DOMAIN
from custom_components.pulse_check.coordinator import PulseCheckCoordinator
from custom_components.pulse_check.replacements import JUMP_CONFIRM_SECONDS
from tests.helpers import BATTERY, device_dict as _device, start_integration

KITCHEN = "Kitchen H&T"
BATTERY_ENTITY = "sensor.kitchen_ht_battery"


async def _later(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _level(hass: HomeAssistant, freezer: FrozenDateTimeFactory, level: int) -> None:
    hass.states.async_set(BATTERY_ENTITY, str(level), BATTERY)
    await _later(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))


async def _low_kitchen(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> tuple[PulseCheckCoordinator, str]:
    """The Kitchen H&T at 10 %, below the 30 % warning level, marked as charging."""
    entry, device_ids = await start_integration(hass, fixture_snapshot, freezer, fixed_now)
    kitchen = device_ids["dev_shelly_ht"]
    # It gets charged, so it is on the Charge list, not the Replace list.
    await hass.services.async_call(
        DOMAIN, "set_device_settings", {"device_id": kitchen, "rechargeable": True}, blocking=True
    )
    await _level(hass, freezer, 10)
    coordinator: PulseCheckCoordinator = entry.runtime_data
    assert [i.device.device_id for i in coordinator.data.actions.charge] == [kitchen]

    await hass.services.async_call(DOMAIN, "mark_charged", {"device_id": kitchen}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    return coordinator, kitchen


def _low(coordinator: PulseCheckCoordinator, kitchen: str) -> bool:
    return coordinator.data.by_id[kitchen].severity != "ok"


async def test_a_marked_battery_counts_as_charging_until_out_of_the_warning_range(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    coordinator, kitchen = await _low_kitchen(hass, fixture_snapshot, freezer, fixed_now)
    assert not _low(coordinator, kitchen)
    assert coordinator.data.actions.charge == []
    assert _device(hass, KITCHEN)["battery"].get("isCharging") is True

    # Climbing slowly, as a home battery charging from the grid does.
    for level in (17, 24, 30):
        await _level(hass, freezer, level)
        assert kitchen in coordinator.store.charging
        assert not _low(coordinator, kitchen)
    # Out of the warning range: done, and not low on its own.
    await _level(hass, freezer, 31)
    assert kitchen not in coordinator.store.charging
    assert not _low(coordinator, kitchen)
    assert not _device(hass, KITCHEN)["battery"].get("isCharging")


async def test_a_mark_ends_when_the_level_falls_below_where_it_was(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    coordinator, kitchen = await _low_kitchen(hass, fixture_snapshot, freezer, fixed_now)
    await _level(hass, freezer, 9)
    assert kitchen not in coordinator.store.charging
    assert _low(coordinator, kitchen)
    assert [i.device.device_id for i in coordinator.data.actions.charge] == [kitchen]


async def test_a_mark_ends_when_the_level_does_not_rise(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    coordinator, kitchen = await _low_kitchen(hass, fixture_snapshot, freezer, fixed_now)
    await _later(hass, freezer, timedelta(hours=5))
    assert not _low(coordinator, kitchen)
    await _later(hass, freezer, timedelta(hours=1, minutes=5))
    assert kitchen not in coordinator.store.charging
    assert _low(coordinator, kitchen)


async def test_undo_takes_back_the_charge_and_the_mark(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    coordinator, kitchen = await _low_kitchen(hass, fixture_snapshot, freezer, fixed_now)
    await hass.services.async_call(DOMAIN, "undo_mark", {"device_id": kitchen}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert kitchen not in coordinator.store.charging
    assert _low(coordinator, kitchen)
    assert coordinator.replacements.last_event(kitchen) is None


async def test_a_fast_charge_after_marking_is_one_charge_not_two(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A rise of 20 points or more would otherwise be recorded as a charge of its own."""
    coordinator, kitchen = await _low_kitchen(hass, fixture_snapshot, freezer, fixed_now)
    await _level(hass, freezer, 28)
    await _later(hass, freezer, timedelta(seconds=JUMP_CONFIRM_SECONDS + 60))
    events = coordinator.store.history[kitchen]["events"]
    assert [e["kind"] for e in events] == ["charged"]
    assert events[0]["auto"] is False


async def test_the_mark_is_saved(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A restart in the middle of a charge keeps it."""
    _coordinator, kitchen = await _low_kitchen(hass, fixture_snapshot, freezer, fixed_now)
    await _later(hass, freezer, timedelta(seconds=5))
    saved = hass_storage["pulse_check.data"]["data"]["charging"][kitchen]
    assert saved["from"] == 10
