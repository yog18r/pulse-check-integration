"""The count sensors, the next-to-run-out sensor and the problem binary sensor."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import load_fixture_into_hass


async def test_counts_match_the_golden_summary(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    golden: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    summary = golden["cases"][0]["summary"]

    def state_of(entity_id: str) -> str:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        return state.state

    assert state_of("sensor.pulse_check_low_batteries") == str(summary["lowBatteries"])
    assert state_of("sensor.pulse_check_offline") == str(summary["offline"])
    assert state_of("sensor.pulse_check_quiet") == str(summary["quiet"])
    # Critical batteries: the 12 % motion sensor, the binary-low smoke alarm
    # and the 9 % template remote.
    assert state_of("sensor.pulse_check_critical_batteries") == "3"
    assert state_of("binary_sensor.pulse_check_problem") == "on"
    # No recorder in the test instance, so no drain estimates yet.
    assert state_of("sensor.pulse_check_next_to_run_out") == "unknown"


async def test_problem_is_off_when_all_is_well(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An instance with no devices at all has nothing to report."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.pulse_check_problem").state == "off"  # type: ignore[union-attr]
    assert hass.states.get("sensor.pulse_check_attention").state == "0"  # type: ignore[union-attr]
