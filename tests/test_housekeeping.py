"""The store does not grow without end: migrations, capped history, pruning the departed."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.pulse_check.const import UPDATE_INTERVAL
from custom_components.pulse_check.coordinator import PulseCheckCoordinator
from custom_components.pulse_check.core.models import to_iso
from custom_components.pulse_check.storage import (
    HEARD_SAVE_EVERY,
    MAX_HISTORY_RECORDS,
    PRUNE_AFTER,
    STORAGE_KEY,
    PulseCheckStore,
    trim_history,
)
from tests.conftest import load_fixture_into_hass


def _event(at: datetime) -> dict[str, Any]:
    return {"at": to_iso(at), "kind": "charged", "auto": True}


def test_trim_history_keeps_the_newest() -> None:
    entry = {"events": list(range(MAX_HISTORY_RECORDS + 5)), "cycles": [1, 2]}
    assert trim_history(entry) is True
    assert entry["events"][0] == 5
    assert len(entry["events"]) == MAX_HISTORY_RECORDS
    assert entry["cycles"] == [1, 2]
    assert trim_history(entry) is False


async def test_an_unticked_rechargeable_from_before_means_detect_not_replaceable(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Older versions could save `rechargeable: false` for "not set"."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "device_settings": {
                "a": {"rechargeable": False, "battery_type": "AA"},
                "b": {"rechargeable": True},
            }
        },
    }
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    settings = config_entry.runtime_data.store.device_settings
    assert settings["a"] == {"battery_type": "AA"}
    assert settings["b"] == {"rechargeable": True}


async def test_what_is_kept_for_a_removed_device_goes_after_a_week(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    freezer.move_to(fixed_now)
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    store = coordinator.store
    kitchen = device_ids["dev_shelly_ht"]
    lock = device_ids["dev_zwave_lock"]
    # Over-long history for a device that stays, and some for one that goes.
    store.history[kitchen] = {
        "events": [_event(fixed_now - timedelta(days=i)) for i in range(MAX_HISTORY_RECORDS + 10)],
        "cycles": [],
    }
    store.history[lock] = {"events": [_event(fixed_now)], "cycles": []}
    store.snooze(lock, fixed_now + timedelta(days=365))
    store.history["entity:sensor.never_existed"] = {"events": [], "cycles": []}

    dr.async_get(hass).async_remove_device(lock)
    await coordinator.async_refresh()
    assert len(store.history[kitchen]["events"]) == MAX_HISTORY_RECORDS
    assert lock in store.history  # gone, but not for long enough yet
    assert lock in store.data["gone"]

    freezer.tick(PRUNE_AFTER - timedelta(hours=1))
    async_fire_time_changed(hass)
    await coordinator.async_refresh()
    assert lock in store.history

    freezer.tick(timedelta(hours=1) + UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await coordinator.async_refresh()
    assert lock not in store.history
    assert lock not in store.data["snoozes"]
    assert "entity:sensor.never_existed" not in store.history
    assert store.data["gone"] == {}
    assert kitchen in store.history


async def test_a_device_that_comes_back_keeps_its_history(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A YAML entity missing for a while (its integration failed to start) is not gone."""
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    hass.states.async_remove("sensor.garden_soil_moisture")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    store = coordinator.store
    orphan = "entity:sensor.garden_soil_moisture"
    store.history[orphan] = {"events": [_event(fixed_now)], "cycles": []}
    await coordinator.async_refresh()
    assert orphan in store.data["gone"]

    freezer.tick(timedelta(days=2))
    hass.states.async_set(
        "sensor.garden_soil_moisture", "40", {"device_class": "battery", "unit_of_measurement": "%"}
    )
    await coordinator.async_refresh()
    assert orphan not in store.data["gone"]
    freezer.tick(PRUNE_AFTER)
    await coordinator.async_refresh()
    assert orphan in store.history


async def test_a_disabled_entity_with_no_device_keeps_its_history(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Disabled entities are left out of the analysis, but they have not left."""
    freezer.move_to(fixed_now)
    entry = er.async_get(hass).async_get_or_create(
        "sensor", "test", "spare", disabled_by=er.RegistryEntryDisabler.USER
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    orphan = f"entity:{entry.entity_id}"
    coordinator.store.history[orphan] = {"events": [_event(fixed_now)], "cycles": []}
    await coordinator.async_refresh()
    freezer.tick(PRUNE_AFTER + UPDATE_INTERVAL)
    await coordinator.async_refresh()
    assert orphan in coordinator.store.history
    assert orphan not in coordinator.store.data["gone"]


def _last_heard(coordinator: PulseCheckCoordinator, device_id: str) -> datetime | None:
    return next(d.last_heard for d in coordinator.data.devices if d.device_id == device_id)


async def test_last_heard_survives_going_offline_and_a_restart(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Home Assistant stamps every unavailable entity "now" when it starts."""
    freezer.move_to(fixed_now)
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    lock = device_ids["dev_zwave_lock"]
    heard = _last_heard(coordinator, lock)
    assert heard is not None
    entity_ids = next(d.entity_ids for d in coordinator.data.devices if d.device_id == lock)

    freezer.tick(timedelta(hours=11))
    for entity_id in entity_ids:
        hass.states.async_set(entity_id, "unavailable")
    await coordinator.async_refresh()
    assert _last_heard(coordinator, lock) == heard

    # A restart: the store is read back and every entity is stamped anew.
    freezer.tick(timedelta(minutes=5))
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    for entity_id in entity_ids:
        hass.states.async_set(entity_id, "unknown", force_update=True)
    coordinator = config_entry.runtime_data
    await coordinator.async_refresh()
    assert _last_heard(coordinator, lock) == heard


def test_last_heard_is_written_now_and_then_not_every_update(hass: HomeAssistant) -> None:
    store = PulseCheckStore(hass)
    saves: list[None] = []
    store.async_save = lambda: saves.append(None)  # type: ignore[method-assign]
    now = datetime(2026, 11, 9, tzinfo=dt_util.UTC)
    store.note_heard([("a", now)], now)
    store.note_heard([("a", now + timedelta(minutes=1))], now + timedelta(minutes=1))
    assert len(saves) == 1
    store.note_heard([("a", now + timedelta(minutes=2))], now + HEARD_SAVE_EVERY)
    assert len(saves) == 2
    assert store.last_heard() == {"a": now + timedelta(minutes=2)}
