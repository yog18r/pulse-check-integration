"""Which state changes cause a recompute, and which are ignored.

A house with power sensors reporting every second must not keep the
coordinator busy: only changes the analysis can see get through, and
those are debounced to one run per cooldown.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from tests.conftest import load_fixture_into_hass


async def _settle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the debounce cooldown pass and every scheduled task finish."""
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _attributes(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    state = hass.states.get(entity_id)
    assert state is not None
    return dict(state.attributes)


async def test_only_relevant_state_changes_cause_a_recompute(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    runs: list[int] = []
    config_entry.async_on_unload(coordinator.async_add_listener(lambda: runs.append(1)))

    # A plug's power sensor reporting a new reading every second for a
    # minute: the analysis never reads watts, so no recompute at all.
    power = _attributes(hass, "sensor.office_plug_power")
    for tenths in range(40, 100):
        freezer.tick(timedelta(seconds=1))
        hass.states.async_set("sensor.office_plug_power", str(tenths / 10), power)
    await _settle(hass, freezer)
    assert runs == []

    # Attribute-only updates on an unrelated attribute: ignored too.
    hass.states.async_set("sensor.office_plug_power", "9.9", {**power, "last_reset": "today"})
    await _settle(hass, freezer)
    assert runs == []

    # The same sensor going unavailable can make its device offline: one run.
    hass.states.async_set("sensor.office_plug_power", "unavailable", power)
    await _settle(hass, freezer)
    assert len(runs) == 1

    # A battery level changing: one run, however many changes land in the cooldown.
    battery = _attributes(hass, "sensor.kitchen_ht_battery")
    for level in ("44", "43", "42"):
        hass.states.async_set("sensor.kitchen_ht_battery", level, battery)
    await _settle(hass, freezer)
    assert len(runs) == 2

    # An entity that belongs to no analysed device: ignored.
    hass.states.async_set("sensor.random_template", "43", {})
    await _settle(hass, freezer)
    assert len(runs) == 2


async def test_a_recompute_that_changes_nothing_writes_no_new_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """No time-stamped attributes, so identical results leave the recorder alone."""
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    before = hass.states.get("sensor.pulse_check_attention")
    assert before is not None
    assert "computed_at" not in before.attributes

    freezer.tick(timedelta(seconds=30))
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    after = hass.states.get("sensor.pulse_check_attention")
    assert after is not None
    assert after.last_updated == before.last_updated
    assert after.last_changed == before.last_changed


async def test_a_new_battery_without_a_registry_entry_is_picked_up(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A YAML template sensor brings no registry event: its first state is the signal."""
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    runs: list[int] = []
    config_entry.async_on_unload(coordinator.async_add_listener(lambda: runs.append(1)))

    # A new entity that is not a battery: ignored.
    hass.states.async_set("sensor.shed_temperature", "14", {"device_class": "temperature"})
    await _settle(hass, freezer)
    assert runs == []

    # A new battery: one run, and it is a device from then on.
    battery = {"device_class": "battery", "unit_of_measurement": "%"}
    hass.states.async_set("sensor.shed_battery", "60", battery)
    await _settle(hass, freezer)
    assert len(runs) == 1
    shed = {d.device_id: d for d in coordinator.data.devices}["entity:sensor.shed_battery"]
    assert shed.battery is not None
    assert shed.battery.level == 60

    # Its level changing is a change like any other battery's.
    hass.states.async_set("sensor.shed_battery", "59", battery)
    await _settle(hass, freezer)
    assert len(runs) == 2


async def test_a_disabled_entity_is_not_read_as_an_unregistered_one(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """A disabled entity's state lingers until its integration reloads; skip it."""
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    registry = er.async_get(hass)
    registry.async_update_entity(
        "sensor.remote_battery_template", disabled_by=er.RegistryEntryDisabler.USER
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.remote_battery_template") is not None
    ids = {device.device_id for device in config_entry.runtime_data.data.devices}
    assert "entity:sensor.remote_battery_template" not in ids
    assert "entity:sensor.garden_soil_moisture" in ids  # the one truly unregistered
