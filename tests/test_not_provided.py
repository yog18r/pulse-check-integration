"""Entities an integration no longer provides: marked in the snapshot, worded in messages.

Home Assistant keeps the registry entry of an entity its integration stops
providing, with a restored `unavailable` placeholder state. That is stale
configuration while the integration runs. While it fails to start, the
same placeholder may mean the hardware is down, so it is not marked.
"""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check.coordinator import build_snapshot
from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices
from custom_components.pulse_check.messages import load_messages
from custom_components.pulse_check.notify import Issue, device_issues

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
PLACEHOLDER = {"restored": True, "friendly_name": "Allow DNS"}


async def test_only_placeholders_of_running_integrations_are_marked(hass: HomeAssistant) -> None:
    running = MockConfigEntry(domain="unifi", state=ConfigEntryState.LOADED)
    failed = MockConfigEntry(domain="shelly", state=ConfigEntryState.SETUP_RETRY)
    running.add_to_hass(hass)
    failed.add_to_hass(hass)
    registry = er.async_get(hass)
    dropped = registry.async_get_or_create("switch", "unifi", "policy-1", config_entry=running)
    working = registry.async_get_or_create("switch", "unifi", "policy-2", config_entry=running)
    down = registry.async_get_or_create("switch", "shelly", "plug-1", config_entry=failed)

    hass.states.async_set(dropped.entity_id, "unavailable", PLACEHOLDER)
    hass.states.async_set(working.entity_id, "unavailable")  # set up, really unavailable
    hass.states.async_set(down.entity_id, "unavailable", PLACEHOLDER)

    entities = build_snapshot(hass)["entities"]
    assert entities[dropped.entity_id].get("not_provided") is True
    assert "not_provided" not in entities[working.entity_id]
    assert "not_provided" not in entities[down.entity_id]

    # Otherwise the harness unloads them at teardown, which imports the
    # real UniFi and Shelly integrations and their libraries.
    running.mock_state(hass, ConfigEntryState.NOT_LOADED)
    failed.mock_state(hass, ConfigEntryState.NOT_LOADED)


def _leftover_device() -> Snapshot:
    return {
        "states": {
            "switch.allow_dns": {
                "entity_id": "switch.allow_dns",
                "state": "unavailable",
                "attributes": PLACEHOLDER,
                "last_updated": "2026-10-25T11:00:00.000Z",
            }
        },
        "entities": {
            "switch.allow_dns": {
                "entity_id": "switch.allow_dns",
                "platform": "unifi",
                "device_id": "dev",
                "not_provided": True,
            }
        },
        "devices": {
            "dev": {
                "id": "dev",
                "name": "UniFi Network Allow DNS",
                "name_by_user": None,
                "manufacturer": None,
                "model": None,
                "area_id": None,
                "entry_type": None,
                "disabled_by": None,
            }
        },
        "areas": {},
    }


def test_the_message_names_the_integration() -> None:
    [device] = analyse_devices(_leftover_device(), CoreConfig(), NOW)
    messages = load_messages()

    def name(domain: str) -> str:
        return {"unifi": "UniFi Network"}[domain]

    issues = device_issues(device, CoreConfig(), NOW, messages.catalog("en"), name)
    assert issues == {
        "not_provided": Issue(
            "not_provided",
            "warning",
            "UniFi Network Allow DNS: no longer provided by UniFi Network",
        )
    }
    german = device_issues(device, CoreConfig(), NOW, messages.catalog("de"), name)
    assert german["not_provided"].message == (
        "UniFi Network Allow DNS: wird von UniFi Network nicht mehr bereitgestellt"
    )
