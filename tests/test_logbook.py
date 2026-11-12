"""Transitions show in a device's own logbook, whichever integration owns it."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.components.recorder.core import Recorder
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.pulse_check.const import DOMAIN
from custom_components.pulse_check.messages import without_name
from custom_components.pulse_check.notify import log_transition


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """Replaces conftest's: the recorder must be set up before Home Assistant is."""


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Kitchen H&T: battery critical (5 %)", "battery critical (5 %)"),
        ("Kitchen H&T : de nouveau en ligne", "de nouveau en ligne"),
        ("Kitchen H&T：离线已恢复", "离线已恢复"),
        ("Something else entirely", "Something else entirely"),
        ("Kitchen H&T", "Kitchen H&T"),
    ],
)
def test_the_name_comes_off_the_front_of_the_message(message: str, expected: str) -> None:
    assert without_name("Kitchen H&T", message) == expected


def _device(hass: HomeAssistant, owner: MockConfigEntry, key: str, name: str) -> dr.DeviceEntry:
    """A device of another integration, with one entity, as a watched device has."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={("met", key)}, name=name
    )
    er.async_get(hass).async_get_or_create(
        "weather",
        "met",
        key,
        suggested_object_id=key,
        device_id=device.id,
        config_entry=owner,
    )
    return device


async def test_a_transition_shows_on_its_devices_logbook(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Asked the way a device's page asks: its entities and its own id."""
    owner = MockConfigEntry(domain="met", title="Met.no")
    owner.add_to_hass(hass)
    home = _device(hass, owner, "home", "Home")
    other = _device(hass, owner, "other", "Other")
    # The logbook's only use of the frontend, which the test environment
    # lacks, is its sidebar panel.
    hass.config.components.add("frontend")
    with patch("homeassistant.components.logbook.frontend.async_register_built_in_panel"):
        assert await async_setup_component(hass, "logbook", {})
    await hass.async_block_till_done()

    log_transition(hass, home.id, "Home", "Home: offline")
    log_transition(hass, home.id, "Home", "Home: offline resolved")
    log_transition(hass, other.id, "Other", "Other: offline")
    await async_wait_recording_done(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "logbook/get_events",
            "start_time": "2000-01-01T00:00:00+00:00",
            "entity_ids": ["weather.home"],
            "device_ids": [home.id],
        }
    )
    response = await client.receive_json()
    assert response["success"], response
    assert [(row["domain"], row["name"], row["message"]) for row in response["result"]] == [
        (DOMAIN, "Home", "offline"),
        (DOMAIN, "Home", "offline resolved"),
    ]
