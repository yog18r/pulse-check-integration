"""Replacement tracking: services, auto-detection, cycles, unusual drain, per-device sensors."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.pulse_check.const import ATTR_DEVICES, CONF_PER_DEVICE_SENSORS, DOMAIN
from tests.conftest import load_fixture_into_hass

ATTENTION = "sensor.pulse_check_attention"
BATTERY = {"device_class": "battery", "unit_of_measurement": "%"}


def _device(hass: HomeAssistant, name: str) -> dict[str, Any]:
    state = hass.states.get(ATTENTION)
    assert state is not None
    for device in state.attributes[ATTR_DEVICES]:
        if device["name"] == name:
            return device  # type: ignore[no-any-return]
    raise AssertionError(name)


async def _set_level(hass: HomeAssistant, freezer: FrozenDateTimeFactory, level: int) -> None:
    hass.states.async_set("sensor.kitchen_ht_battery", str(level), BATTERY)
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _set_up(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    options: dict[str, Any] | None = None,
) -> tuple[MockConfigEntry, dict[str, str]]:
    freezer.move_to(fixed_now)
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    entry = MockConfigEntry(
        domain=DOMAIN, title="Pulse Check", unique_id=DOMAIN, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, device_ids


async def test_mark_replaced_records_an_event_and_closes_the_cycle(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, device_ids = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    kitchen = device_ids["dev_shelly_ht"]
    assert "lastReplaced" not in _device(hass, "Kitchen H&T")

    await hass.services.async_call(
        DOMAIN, "mark_replaced", {"device_id": kitchen, "battery_type": "CR123A"}, blocking=True
    )
    await hass.async_block_till_done()
    assert _device(hass, "Kitchen H&T")["lastReplaced"] == "2026-10-15T10:00:00.000Z"

    # The new battery reads 100 %, then 80 % ten days later, when it is
    # replaced again: one completed cycle at 2 %/day.
    await _set_level(hass, freezer, 100)
    freezer.tick(timedelta(days=10))
    await _set_level(hass, freezer, 80)
    await hass.services.async_call(DOMAIN, "mark_replaced", {"device_id": kitchen}, blocking=True)
    await hass.async_block_till_done()
    coordinator = hass.config_entries.async_loaded_entries(DOMAIN)[0].runtime_data
    stats = coordinator.replacements.cycle_stats(kitchen)
    assert stats["cycles"] == 1
    assert stats["average_days"] == 10
    assert stats["average_rate_per_day"] == 2


async def test_a_jump_is_detected_as_a_replacement(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, device_ids = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    # 92 % -> 60 % over time (a sudden drop too), then a fresh battery at 100 %.
    await _set_level(hass, freezer, 60)
    assert _device(hass, "Kitchen H&T")["unusual"] == "level dropped suddenly"
    freezer.tick(timedelta(days=1))
    await _set_level(hass, freezer, 100)
    device = _device(hass, "Kitchen H&T")
    assert device["lastReplaced"].startswith("2026-10-16T10:00")
    coordinator = hass.config_entries.async_loaded_entries(DOMAIN)[0].runtime_data
    event = coordinator.replacements.last_event(device_ids["dev_shelly_ht"])
    assert event["kind"] == "replaced"
    assert event["auto"] is True
    assert event["level_before"] == 60
    assert event["level_after"] == 100


async def test_per_device_sensors_appear_when_enabled(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, device_ids = await _set_up(
        hass, fixture_snapshot, freezer, fixed_now, {CONF_PER_DEVICE_SENSORS: True}
    )
    registry = er.async_get(hass)
    kitchen = device_ids["dev_shelly_ht"]

    def entity_id(device_id: str, key: str) -> str | None:
        return registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{device_id}_{key}")

    days_left_id = entity_id(kitchen, "days_left")
    # Named after the device (Home Assistant may prefix the area as well).
    assert days_left_id is not None
    assert days_left_id.endswith("kitchen_h_t_battery_days_left")
    days_left = hass.states.get(days_left_id)
    assert days_left is not None
    assert days_left.state == "unknown"  # no recorder history in tests
    # The sensor sits on the Shelly's own device, which keeps its name.
    assert registry.async_get(days_left_id).device_id == kitchen  # type: ignore[union-attr]
    assert dr.async_get(hass).async_get(kitchen).name == "Kitchen H&T"  # type: ignore[union-attr]
    last_id = entity_id(kitchen, "last_replaced")
    assert last_id is not None
    last = hass.states.get(last_id)
    assert last is not None
    assert last.state == "unknown"
    assert last.attributes["cycles"] == 0
    # Orphans have no device page, so no per-device sensors.
    assert entity_id("entity:sensor.remote_battery_template", "days_left") is None

    await hass.services.async_call(DOMAIN, "mark_charged", {"device_id": kitchen}, blocking=True)
    await hass.async_block_till_done()
    last = hass.states.get(last_id)
    assert last is not None
    assert last.state == "2026-10-15T10:00:00+00:00"
    assert last.attributes["kind"] == "charged"
