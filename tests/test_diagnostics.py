"""The diagnostics download: useful for a bug report, safe to post in public."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check.const import (
    CONF_EXCLUDE_AREAS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_INTEGRATION_THRESHOLDS,
    CONF_NOTIFY_TARGETS,
    CONF_PING_QUIET,
)
from custom_components.pulse_check.coordinator import PulseCheckCoordinator
from custom_components.pulse_check.diagnostics import async_get_config_entry_diagnostics
from custom_components.pulse_check.notify import repair_id

from .helpers import BATTERY, start_integration

TARGET = "notify.mobile_app_jordans_phone"
ADDRESS = "192.168.1.77"


def _strings(value: object) -> list[str]:
    """Every key and text value in the report."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for key, item in value.items() for s in (*_strings(key), *_strings(item))]
    if isinstance(value, list | tuple):
        return [s for item in value for s in _strings(item)]
    return []


def _identifying(hass: HomeAssistant) -> set[str]:
    """Everything in this home that must stay out of a public report."""
    found: set[str] = {TARGET, ADDRESS, "Jordan"}
    for device in dr.async_get(hass).devices:
        found.update(
            value
            for value in (device.id, device.name, device.name_by_user, device.configuration_url)
            if value
        )
    for entity in er.async_get(hass).entities.values():
        found.update((entity.entity_id, entity.id, entity.unique_id))
    for area in ar.async_get(hass).async_list_areas():
        found.update((area.id, area.name))
    return {value.lower() for value in found if len(value) >= 4}


async def _report(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> tuple[dict[str, Any], str]:
    entry, _ = await start_integration(
        hass,
        fixture_snapshot,
        freezer,
        fixed_now,
        options={
            CONF_NOTIFY_TARGETS: [TARGET],
            CONF_EXCLUDE_AREAS: ["Jordan's room"],
            CONF_EXCLUDE_ENTITIES: ["sensor.jordans_diary_lock_battery"],
            CONF_EXCLUDE_INTEGRATIONS: ["made_up"],
            CONF_INTEGRATION_THRESHOLDS: [{"integration": "zha", "hours": 48}],
            CONF_PING_QUIET: True,
        },
    )
    owner = MockConfigEntry(domain="shelly")
    owner.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("shelly", "aa:bb:cc:dd:ee:ff")},
        name="Jordan's bedside sensor",
        configuration_url=f"http://{ADDRESS}",
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        "shelly",
        "aa:bb:cc:dd:ee:ff-battery",
        suggested_object_id="jordans_bedside_battery",
        device_id=device.id,
        config_entry=owner,
    )
    hass.states.async_set("sensor.jordans_bedside_battery", "80", BATTERY)
    coordinator: PulseCheckCoordinator = entry.runtime_data
    coordinator.store.update_device_settings(
        device.id,
        {
            "name": "Jordan's",
            "area": "Jordan's study",
            "battery_type": "Jordan",
            "battery_count": 2,
        },
    )
    coordinator.rebuild_config()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    return await async_get_config_entry_diagnostics(hass, entry), device.id


async def test_the_report_holds_nothing_that_identifies_a_home(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    report, _ = await _report(hass, fixture_snapshot, freezer, fixed_now)
    secrets = _identifying(hass)
    # Every device, entity and area of the fixture is looked for.
    assert len(secrets) > 100
    assert len(report["devices"]) > 10
    leaks = [
        (text, secret) for text in _strings(report) for secret in secrets if secret in text.lower()
    ]
    assert not leaks


async def test_the_report_still_says_what_a_bug_report_needs(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    report, _ = await _report(hass, fixture_snapshot, freezer, fixed_now)
    options = report["options"]
    assert options[CONF_PING_QUIET] is True
    assert options[CONF_INTEGRATION_THRESHOLDS] == {"zha": 48}
    assert options[CONF_EXCLUDE_INTEGRATIONS] == ["made_up"]
    assert options[CONF_NOTIFY_TARGETS] == {"count": 1}
    assert options[CONF_EXCLUDE_AREAS] == {"count": 1}
    assert report["loaded"] is True
    assert report["counts"]["devices"] == len(report["devices"])

    [shelly] = [d for d in report["devices"] if "settings" in d]
    assert shelly["id"].startswith("device_")
    assert shelly["ping"] == {"method": "network", "address_from": "configuration_url"}
    assert shelly["battery"]["level"] == 80
    assert shelly["settings"] == {
        "area": "(set)",
        "battery_count": 2,
        "battery_type": "(set)",
        "name": "(set)",
    }


async def test_a_report_before_setup_has_the_options_only(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    report = await async_get_config_entry_diagnostics(hass, config_entry)
    assert report["loaded"] is False
    assert "devices" not in report


def test_a_repair_s_id_does_not_name_its_target() -> None:
    """Home Assistant puts the integration's repair ids in the download too."""
    issue = repair_id("notify_failed", TARGET)
    assert "jordan" not in issue
    assert issue.startswith("notify_failed_")
    assert issue == repair_id("notify_failed", TARGET)
