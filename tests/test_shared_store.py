"""One store across reloads, so nothing the old setup saves late is lost or written back."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.pulse_check.coordinator import PulseCheckCoordinator
from custom_components.pulse_check.storage import DATA_STORE
from tests.helpers import start_integration


async def _flush(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Past the store's save delay."""
    freezer.tick(timedelta(seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_a_save_by_the_old_setup_after_a_reload_is_kept(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Saving the options reloads; work the old setup had under way can still save."""
    entry, device_ids = await start_integration(hass, fixture_snapshot, freezer, fixed_now)
    old: PulseCheckCoordinator = entry.runtime_data
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    new: PulseCheckCoordinator = entry.runtime_data
    assert new is not old
    assert new.store is old.store

    # The old setup finishing something now, such as a retried message.
    lock = device_ids["dev_zwave_lock"]
    old.store.snooze(lock, fixed_now + timedelta(days=2))
    await _flush(hass, freezer)
    assert lock in new.store.snoozes(fixed_now)
    assert lock in hass_storage["pulse_check.data"]["data"]["snoozes"]


async def test_removing_pulse_check_removes_through_the_store_holding_its_saves(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Home Assistant's store removal cancels that store's waiting save.

    Removal must therefore go through the store a late save is waiting on,
    or the file is written back two seconds after it was deleted. (The test
    harness replaces that removal, so the cancelling itself is Home
    Assistant's to test.)
    """
    entry, _ = await start_integration(hass, fixture_snapshot, freezer, fixed_now)
    store = entry.runtime_data.store
    removed: list[object] = []

    async def remove(self: object) -> None:
        removed.append(self)

    with patch.object(type(store), "async_remove", remove):
        assert await hass.config_entries.async_remove(entry.entry_id)
    assert removed == [store]
    assert DATA_STORE not in hass.data
