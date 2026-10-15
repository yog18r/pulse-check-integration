"""Services: snooze, unsnooze, set_device_settings, refresh."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.pulse_check.const import ATTR_DEVICES, DOMAIN
from tests.conftest import load_fixture_into_hass

ATTENTION = "sensor.pulse_check_attention"


def _device(hass: HomeAssistant, name: str) -> dict[str, Any]:
    state = hass.states.get(ATTENTION)
    assert state is not None
    for device in state.attributes[ATTR_DEVICES]:
        if device["name"] == name:
            return device  # type: ignore[no-any-return]
    raise AssertionError(f"no device named {name}")


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


async def test_snooze_mutes_a_device_and_is_persisted(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    hass_storage: dict[str, Any],
) -> None:
    device_ids = await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    lock = device_ids["dev_zwave_lock"]
    before = int(hass.states.get(ATTENTION).state)  # type: ignore[union-attr]
    assert _device(hass, "Front Door Lock")["severity"] == "critical"

    await hass.services.async_call(DOMAIN, "snooze", {"device_id": lock, "days": 2}, blocking=True)
    await hass.async_block_till_done()
    snoozed = _device(hass, "Front Door Lock")
    assert snoozed["severity"] == "ok"
    assert snoozed["isOffline"] is True  # the facts stay
    assert snoozed["snoozedUntil"] == "2026-10-17T10:00:00.000Z"
    assert int(hass.states.get(ATTENTION).state) == before - 1  # type: ignore[union-attr]

    # Written to .storage (after the short save delay) so it survives a restart.
    freezer.tick(timedelta(seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    saved = hass_storage["pulse_check.data"]["data"]
    assert saved["snoozes"] == {lock: "2026-10-17T10:00:00.000Z"}

    await hass.services.async_call(DOMAIN, "unsnooze", {"device_id": lock}, blocking=True)
    await hass.async_block_till_done()
    assert _device(hass, "Front Door Lock")["severity"] == "critical"


async def test_snooze_expires_on_its_own(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    device_ids = await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    await hass.services.async_call(
        DOMAIN, "snooze", {"device_id": device_ids["dev_zwave_lock"], "days": 1}, blocking=True
    )
    await hass.async_block_till_done()
    assert _device(hass, "Front Door Lock")["severity"] == "ok"

    freezer.tick(timedelta(days=1, minutes=1))
    await hass.services.async_call(DOMAIN, "refresh", blocking=True)
    await hass.async_block_till_done()
    assert _device(hass, "Front Door Lock")["severity"] == "critical"


async def test_snooze_accepts_a_bare_entity_id_for_orphans(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    await hass.services.async_call(
        DOMAIN, "snooze", {"device_id": "sensor.remote_battery_template"}, blocking=True
    )
    await hass.async_block_till_done()
    assert _device(hass, "TV Remote Battery")["severity"] == "ok"


async def test_unknown_device_is_a_validation_error(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "snooze", {"device_id": "nope"}, blocking=True)


async def test_set_device_settings_changes_the_analysis(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    device_ids = await _set_up(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    zha = device_ids["dev_zha_temp"]
    assert _device(hass, "Bedroom Temp & Humidity")["isQuiet"] is True

    await hass.services.async_call(
        DOMAIN,
        "set_device_settings",
        {
            "device_id": zha,
            "name": "Bedroom Climate",
            "area": "Attic",
            "quiet_threshold_hours": 48,
            "battery_type": "CR2450",
            "battery_count": 2,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    device = _device(hass, "Bedroom Climate")
    assert device["area"] == "Attic"
    assert device["quietThresholdHours"] == 48
    assert device["isQuiet"] is False  # 32 h < 48 h
    actions = hass.states.get(ATTENTION).attributes["actions"]  # type: ignore[union-attr]
    labels = [item["label"] for item in actions["replace"]]
    assert "Replace 2 × CR2450 in Bedroom Climate" in labels

    # An empty value clears a setting.
    await hass.services.async_call(
        DOMAIN, "set_device_settings", {"device_id": zha, "name": ""}, blocking=True
    )
    await hass.async_block_till_done()
    assert _device(hass, "Bedroom Temp & Humidity")["area"] == "Attic"
