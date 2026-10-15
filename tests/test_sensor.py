"""End-to-end tests: the fixture inside a real Home Assistant, read through the sensor."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.pulse_check.const import ATTR_SUMMARY, DEBOUNCE_SECONDS
from tests.conftest import device_dicts, load_fixture_into_hass

ENTITY_ID = "sensor.pulse_check_attention"


def _with_real_ids(
    devices: list[dict[str, Any]], device_ids: dict[str, str]
) -> list[dict[str, Any]]:
    """The golden devices with Home Assistant's generated device ids."""
    return [
        {**device, "deviceId": device_ids.get(device["deviceId"], device["deviceId"])}
        for device in devices
    ]


async def _set_up(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> dict[str, str]:
    freezer.move_to(fixed_now)
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return device_ids


async def test_attention_sensor_matches_the_golden_output(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    golden: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    device_ids = await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    expected = golden["cases"][0]  # the defaults case

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == str(expected["summary"]["attention"])
    assert device_dicts(hass) == _with_real_ids(expected["devices"], device_ids)
    # The device list itself is not a state attribute any more.
    assert "devices" not in state.attributes
    for key, value in expected["summary"].items():
        assert state.attributes[ATTR_SUMMARY][key] == value


async def test_a_state_change_refreshes_after_the_debounce(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    before = int(hass.states.get(ENTITY_ID).state)  # type: ignore[union-attr]

    # The healthy Shelly H&T drops to 5%: one more device needs attention.
    hass.states.async_set(
        "sensor.kitchen_ht_battery", "5", {"device_class": "battery", "unit_of_measurement": "%"}
    )
    await hass.async_block_till_done()
    assert int(hass.states.get(ENTITY_ID).state) == before  # type: ignore[union-attr]

    freezer.tick(timedelta(seconds=DEBOUNCE_SECONDS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert int(hass.states.get(ENTITY_ID).state) == before + 1  # type: ignore[union-attr]


async def test_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    unloaded = hass.config_entries.async_get_entry(config_entry.entry_id)
    assert unloaded is not None
    assert unloaded.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(ENTITY_ID).state == "unavailable"  # type: ignore[union-attr]
