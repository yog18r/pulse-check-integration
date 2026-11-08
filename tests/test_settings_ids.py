"""Per-device settings saved under an id that no longer matches what is watched."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check.const import DOMAIN
from tests.conftest import load_fixture_into_hass

ORPHAN = "entity:sensor.remote_battery_template"


async def _set_up(
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


async def test_stale_settings_can_be_cleared(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Settings for something no longer watched used to be stuck for ever."""
    await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    store = config_entry.runtime_data.store
    store.update_device_settings("entity:sensor.gone", {"name": "Old battery"})

    # By its bare entity id, as the card's chip or an automation would send it.
    await hass.services.async_call(
        DOMAIN, "set_device_settings", {"device_id": "sensor.gone", "name": ""}, blocking=True
    )
    assert "entity:sensor.gone" not in store.device_settings

    # Something that is neither watched nor has settings is still an error.
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_device_settings",
            {"device_id": "sensor.nothing", "name": "x"},
            blocking=True,
        )


async def test_settings_follow_an_entity_onto_its_new_device(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """An integration gives a lone battery sensor a device: its settings go with it."""
    await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    coordinator = config_entry.runtime_data
    await hass.services.async_call(
        DOMAIN,
        "set_device_settings",
        {"device_id": ORPHAN, "battery_type": "CR2032", "rechargeable": False},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "snooze", {"device_id": ORPHAN, "days": 2}, blocking=True
    )

    host = MockConfigEntry(domain="template")
    host.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=host.entry_id, identifiers={("template", "remote")}, name="TV Remote"
    )
    er.async_get(hass).async_update_entity("sensor.remote_battery_template", device_id=device.id)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    store = coordinator.store
    assert ORPHAN not in store.device_settings
    assert store.device_settings[device.id]["battery_type"] == "CR2032"
    assert device.id in store.data["snoozes"]
    assert coordinator.core_config.device_settings
    [moved] = [s for s in coordinator.core_config.device_settings if s.device_id == device.id]
    assert moved.battery_type == "CR2032"


async def test_a_device_with_its_own_settings_keeps_them(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    coordinator = config_entry.runtime_data
    host = MockConfigEntry(domain="template")
    host.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=host.entry_id, identifiers={("template", "remote")}, name="TV Remote"
    )
    coordinator.store.update_device_settings(ORPHAN, {"battery_type": "CR2032"})
    coordinator.store.update_device_settings(device.id, {"battery_type": "AAA"})
    er.async_get(hass).async_update_entity("sensor.remote_battery_template", device_id=device.id)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.store.device_settings[device.id]["battery_type"] == "AAA"
    # The old entry stays, still clearable from the card or the action.
    assert coordinator.store.device_settings[ORPHAN]["battery_type"] == "CR2032"
