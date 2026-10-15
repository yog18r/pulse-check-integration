"""Tests for the options flow (the Configure dialog)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check.config_flow import flatten_options, nest_options
from custom_components.pulse_check.const import (
    CONF_BATTERY_CRITICAL,
    CONF_BATTERY_WARNING,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_INTEGRATION_THRESHOLDS,
    CONF_QUIET_SCOPE,
    CONF_QUIET_THRESHOLD_HOURS,
)
from tests.conftest import load_fixture_into_hass

ATTENTION = "sensor.pulse_check_attention"


def test_nest_and_flatten_round_trip() -> None:
    flat = {
        CONF_BATTERY_WARNING: 40,
        CONF_QUIET_SCOPE: "all",
        CONF_EXCLUDE_INTEGRATIONS: ["mobile_app"],
    }
    nested = nest_options(flat)
    assert nested == {
        "thresholds": {CONF_BATTERY_WARNING: 40, CONF_QUIET_SCOPE: "all"},
        "filters": {CONF_EXCLUDE_INTEGRATIONS: ["mobile_app"]},
        "notifications": {},
    }
    assert flatten_options(nested) == flat


def test_flatten_drops_empty_values() -> None:
    nested = {"thresholds": {CONF_BATTERY_WARNING: 30}, "filters": {CONF_EXCLUDE_ENTITIES: []}}
    assert flatten_options(nested) == {CONF_BATTERY_WARNING: 30}


async def test_options_form_rejects_critical_above_warning(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "thresholds": {
                CONF_BATTERY_WARNING: 20,
                CONF_BATTERY_CRITICAL: 50,
                CONF_QUIET_THRESHOLD_HOURS: 24,
                CONF_QUIET_SCOPE: "battery",
            },
            "filters": {},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "critical_above_warning"}


async def test_options_are_stored_flat_and_applied(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    golden: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The scenario from the author's instance: exclusions bring the count down."""
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    before = int(hass.states.get(ATTENTION).state)  # type: ignore[union-attr]
    assert before == golden["cases"][0]["summary"]["attention"]

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "thresholds": {
                CONF_BATTERY_WARNING: 30,
                CONF_BATTERY_CRITICAL: 15,
                CONF_QUIET_THRESHOLD_HOURS: 24,
                CONF_QUIET_SCOPE: "battery",
                # The Z-Wave multisensor was last heard 40 h ago: no longer quiet.
                CONF_INTEGRATION_THRESHOLDS: [{"integration": "zwave_js", "hours": 48}],
            },
            "filters": {
                # The orphan template battery at 9 % and the critical motion sensor.
                CONF_EXCLUDE_ENTITIES: [
                    "sensor.remote_battery_template",
                    "sensor.living_room_motion_battery",
                ],
                # The ZHA devices: a warning (28 % and quiet) and a binary low.
                CONF_EXCLUDE_INTEGRATIONS: ["zha"],
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_BATTERY_WARNING: 30,
        CONF_BATTERY_CRITICAL: 15,
        CONF_QUIET_THRESHOLD_HOURS: 24,
        CONF_QUIET_SCOPE: "battery",
        CONF_INTEGRATION_THRESHOLDS: [{"integration": "zwave_js", "hours": 48}],
        CONF_EXCLUDE_ENTITIES: [
            "sensor.remote_battery_template",
            "sensor.living_room_motion_battery",
        ],
        CONF_EXCLUDE_INTEGRATIONS: ["zha"],
    }

    # OptionsFlowWithReload reloaded the entry, so the new config is live.
    await hass.async_block_till_done()
    after = int(hass.states.get(ATTENTION).state)  # type: ignore[union-attr]
    # Gone: TV remote (orphan), motion sensor battery, ZHA climate, ZHA smoke
    # alarm, Z-Wave multisensor (no longer quiet). Left: the dead lock.
    assert after == before - 5
    assert after == 1

    # Reopening the form offers the stored values back, in sections.
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
