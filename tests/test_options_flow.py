"""Tests for the options flow (the Configure dialog)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check.config_flow import (
    SECTIONS,
    _options_schema,
    flatten_options,
    nest_options,
)
from custom_components.pulse_check.const import (
    CONF_BATTERY_CRITICAL,
    CONF_BATTERY_WARNING,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_INTEGRATION_THRESHOLDS,
    CONF_PING_QUIET,
    CONF_QUIET_SCOPE,
    CONF_QUIET_THRESHOLD_HOURS,
    CONF_WATCH_NON_DEVICES,
)
from tests.helpers import (
    load_fixture_into_hass,
    open_general_options,
)

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
        "entities": {},
    }
    assert flatten_options(nested) == flat


def test_every_form_field_is_offered_back() -> None:
    """A field missing from its section would show its default again and be saved over."""
    timings = {
        "startup_grace_minutes": 10,
        "confirm_minutes": 2,
        "restart_timeout_minutes": 45,
    }
    assert nest_options(timings)["notifications"] == timings


def test_each_form_section_holds_exactly_its_keys() -> None:
    """The form and `SECTIONS` must agree, or a stored value is not offered back."""
    form = {
        marker.schema: {field.schema for field in value.schema.schema}
        for marker, value in _options_schema([], []).schema.items()
    }
    assert form == {name: set(keys) for name, keys in SECTIONS.items()}


def _suggested(result: ConfigFlowResult) -> dict[str, dict[str, Any]]:
    """The values a form offers back, by section."""
    schema = result["data_schema"]
    assert schema is not None
    return {
        marker.schema: {
            field.schema: field.description["suggested_value"]
            for field in value.schema.schema
            if field.description and "suggested_value" in field.description
        }
        for marker, value in schema.schema.items()
    }


def test_flatten_drops_empty_values() -> None:
    nested = {"thresholds": {CONF_BATTERY_WARNING: 30}, "filters": {CONF_EXCLUDE_ENTITIES: []}}
    assert flatten_options(nested) == {CONF_BATTERY_WARNING: 30}


async def test_options_form_rejects_critical_above_warning(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    result = await open_general_options(hass, config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "general"

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
    await hass.async_block_till_done(wait_background_tasks=True)
    before = int(hass.states.get(ATTENTION).state)  # type: ignore[union-attr]
    assert before == golden["cases"][0]["summary"]["attention"]

    result = await open_general_options(hass, config_entry.entry_id)
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
                # The orphan template battery at 9 %, the garden sensor with no
                # registry entry at 22 % and the critical motion sensor.
                CONF_EXCLUDE_ENTITIES: [
                    "sensor.remote_battery_template",
                    "sensor.garden_soil_moisture",
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
        CONF_PING_QUIET: True,
        CONF_INTEGRATION_THRESHOLDS: [{"integration": "zwave_js", "hours": 48}],
        CONF_EXCLUDE_ENTITIES: [
            "sensor.remote_battery_template",
            "sensor.garden_soil_moisture",
            "sensor.living_room_motion_battery",
        ],
        CONF_EXCLUDE_INTEGRATIONS: ["zha"],
        CONF_WATCH_NON_DEVICES: True,
    }

    # OptionsFlowWithReload reloaded the entry, so the new config is live.
    await hass.async_block_till_done()
    after = int(hass.states.get(ATTENTION).state)  # type: ignore[union-attr]
    # Gone: TV remote (orphan), garden sensor, motion sensor battery, ZHA
    # climate, ZHA smoke alarm, Z-Wave multisensor (no longer quiet). Left:
    # the dead lock.
    assert after == before - 6
    assert after == 1

    # Reopening the form offers the stored values back, in sections.
    result = await open_general_options(hass, config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    offered = _suggested(result)
    assert flatten_options(offered) == config_entry.options
    assert offered["filters"][CONF_EXCLUDE_INTEGRATIONS] == ["zha"]


async def test_configure_opens_with_a_menu(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["general", "device"]


def _placeholders(result: Any) -> dict[str, str]:
    return dict(result["description_placeholders"] or {})


async def _set_up_with_settings(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> dict[str, str]:
    freezer.move_to(fixed_now)
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    store = config_entry.runtime_data.store
    store.update_device_settings(
        device_ids["dev_shelly_ht"],
        {"battery_type": "CR2032", "battery_count": 2, "quiet_threshold_hours": 48.0},
    )
    store.update_device_settings("entity:sensor.gone", {"name": "Old", "notify_policy": "weekly"})
    return device_ids


async def _open_devices(hass: HomeAssistant, entry_id: str) -> Any:
    result = await hass.config_entries.options.async_init(entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "device"}
    )


async def test_the_per_device_menu_lists_what_is_saved(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up_with_settings(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    result = await _open_devices(hass, config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["device_edit", "device_add", "device_done"]
    saved = _placeholders(result)["saved"]
    assert "- **Kitchen H&T (" in saved
    assert "2 × CR2032 · quiet after 48 h" in saved
    assert "- **⚠ entity:sensor.gone**: shown as “Old” · weekly digest · no longer found" in saved


async def test_with_nothing_saved_or_to_add_the_menu_only_closes(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    result = await _open_devices(hass, config_entry.entry_id)
    assert result["menu_options"] == ["device_done"]  # no devices: nothing to add
    assert _placeholders(result)["saved"] == "No device has saved settings yet."


async def test_edit_lists_only_saved_and_add_only_the_rest(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    device_ids = await _set_up_with_settings(
        hass, config_entry, fixture_snapshot, freezer, fixed_now
    )
    kitchen = device_ids["dev_shelly_ht"]

    result = await _open_devices(hass, config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "device_edit"}
    )
    options = result["data_schema"].schema["device"].config["options"]  # type: ignore[union-attr]
    assert {o["value"] for o in options} == {kitchen, "entity:sensor.gone"}

    result = await _open_devices(hass, config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "device_add"}
    )
    options = result["data_schema"].schema["device"].config["options"]  # type: ignore[union-attr]
    values = {o["value"] for o in options}
    assert kitchen not in values
    assert "entity:sensor.gone" not in values
    assert device_ids["dev_zwave_lock"] in values


async def test_per_device_settings_are_saved_to_the_store_without_a_reload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Every card and notification reads them; the options stay as they were."""
    device_ids = await _set_up_with_settings(
        hass, config_entry, fixture_snapshot, freezer, fixed_now
    )
    coordinator = config_entry.runtime_data
    kitchen = device_ids["dev_shelly_ht"]
    result = await _open_devices(hass, config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "device_edit"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": kitchen}
    )
    assert result["step_id"] == "device_settings"
    placeholders = _placeholders(result)
    assert placeholders["device"].startswith("Kitchen H&T (")
    assert "Empty fields use: warning at 30 % and critical at 15 %" in placeholders["status"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "name": " Kitchen sensor ",
            "battery_type": "CR2450",
            "battery_count": 2.0,
            "battery_kind": "auto",
        },
    )
    # Back to the list, which shows the change, until Done.
    assert result["type"] is FlowResultType.MENU
    assert "Kitchen sensor" in _placeholders(result)["saved"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "device_done"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert coordinator.store.device_settings[kitchen] == {
        "name": "Kitchen sensor",
        "battery_type": "CR2450",
        "battery_count": 2,
    }
    # No reload: the same coordinator still runs, and the change is live.
    assert config_entry.runtime_data is coordinator
    assert config_entry.options == {}
    assert any(s.name == "Kitchen sensor" for s in coordinator.core_config.device_settings)


async def test_per_device_settings_can_be_cleared(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up_with_settings(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    store = config_entry.runtime_data.store
    result = await _open_devices(hass, config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "device_edit"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": "entity:sensor.gone"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"clear": True})
    assert result["type"] is FlowResultType.MENU
    assert "entity:sensor.gone" not in store.device_settings


async def _edit(hass: HomeAssistant, entry_id: str, step: str, device_id: str) -> Any:
    result = await _open_devices(hass, entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": device_id}
    )


async def test_charged_or_replaced_and_own_levels(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    device_ids = await _set_up_with_settings(
        hass, config_entry, fixture_snapshot, freezer, fixed_now
    )
    store = config_entry.runtime_data.store
    phone = device_ids["dev_phone"]
    result = await _edit(hass, config_entry.entry_id, "device_add", phone)
    # Critical above warning (10 % own warning, 15 % default critical) is refused.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"battery_kind": "replaceable", "battery_warning": 10}
    )
    assert result["errors"] == {"base": "critical_above_warning"}
    assert phone not in store.device_settings
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"battery_kind": "replaceable", "battery_warning": 10, "battery_critical": 5},
    )
    assert store.device_settings[phone] == {
        "rechargeable": False,
        "battery_warning": 10.0,
        "battery_critical": 5.0,
    }
    assert (
        "replaced, not charged · warning at 10 % · critical at 5 %"
        in (_placeholders(result)["saved"])
    )
    device = config_entry.runtime_data.data.by_id[phone]
    assert (device.battery_warning, device.battery_critical) == (10, 5)

    # The form shows the choice again, and "work it out" clears it.
    result = await _edit(hass, config_entry.entry_id, "device_edit", phone)
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested["battery_kind"] == "replaceable"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"battery_kind": "auto"}
    )
    assert phone not in store.device_settings


async def test_ignore_a_device_from_its_settings(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """It goes on the options' ignore list at once, without a reload, and can come back."""
    device_ids = await _set_up_with_settings(
        hass, config_entry, fixture_snapshot, freezer, fixed_now
    )
    coordinator = config_entry.runtime_data
    lock = device_ids["dev_zwave_lock"]
    result = await _edit(hass, config_entry.entry_id, "device_add", lock)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"battery_kind": "auto", "ignore": True}
    )
    assert config_entry.options[CONF_EXCLUDE_DEVICES] == [lock]
    assert lock not in coordinator.data.by_id
    assert "ignored" in _placeholders(result)["saved"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "device_done"}
    )
    await hass.async_block_till_done()
    assert config_entry.runtime_data is coordinator  # no reload

    result = await _edit(hass, config_entry.entry_id, "device_edit", lock)
    assert "Ignored" in _placeholders(result)["status"]
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"battery_kind": "auto", "ignore": False}
    )
    assert CONF_EXCLUDE_DEVICES not in config_entry.options
    assert lock in coordinator.data.by_id


async def test_ignoring_an_entity_with_no_device_uses_the_entity_list(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up_with_settings(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    orphan = "entity:sensor.remote_battery_template"
    result = await _edit(hass, config_entry.entry_id, "device_add", orphan)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"battery_kind": "auto", "ignore": True}
    )
    assert config_entry.options[CONF_EXCLUDE_ENTITIES] == ["sensor.remote_battery_template"]
    assert orphan not in config_entry.runtime_data.data.by_id
