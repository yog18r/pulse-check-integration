"""Serving the card and keeping its dashboard resource current."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.pulse_check.card import CARD_URL
from custom_components.pulse_check.const import DOMAIN

BUNDLE = "customElements.define('pulse-check-card', class extends HTMLElement {});\n"


async def _setup_dashboards(hass: HomeAssistant, config: dict[str, Any] | None = None) -> None:
    assert await async_setup_component(hass, "lovelace", {"lovelace": config or {}})


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _expected_url(hass: HomeAssistant) -> str:
    integration = await async_get_integration(hass, DOMAIN)
    return f"{CARD_URL}?v={integration.version}"


def _storage(hass: HomeAssistant) -> ResourceStorageCollection:
    resources = hass.data[LOVELACE_DATA].resources
    assert isinstance(resources, ResourceStorageCollection)
    return resources


def _ours(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        item
        for item in hass.data[LOVELACE_DATA].resources.async_items()
        if item["url"].startswith(CARD_URL)
    ]


async def test_the_card_is_served_and_added_once(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    card_bundle: Path,
) -> None:
    card_bundle.write_text(BUNDLE, encoding="utf-8")
    await _setup_dashboards(hass)
    await _setup(hass, config_entry)

    url = await _expected_url(hass)
    assert url.startswith("/pulse_check/pulse-check-card.js?v=")
    assert [(item["type"], item["url"]) for item in _ours(hass)] == [("module", url)]

    # Saving options reloads the entry: still one resource, no second route.
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(_ours(hass)) == 1

    client = await hass_client()
    response = await client.get(url)
    assert response.status == 200
    assert await response.text() == BUNDLE


async def test_an_older_version_is_updated_and_copies_dropped(
    hass: HomeAssistant, config_entry: MockConfigEntry, card_bundle: Path
) -> None:
    card_bundle.write_text(BUNDLE, encoding="utf-8")
    await _setup_dashboards(hass)
    resources = _storage(hass)
    old = await resources.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=0.0.1"})
    await resources.async_create_item({"res_type": "js", "url": CARD_URL})
    other = await resources.async_create_item({"res_type": "module", "url": "/local/other.js"})

    await _setup(hass, config_entry)

    ours = _ours(hass)
    assert [(item["id"], item["type"], item["url"]) for item in ours] == [
        (old["id"], "module", await _expected_url(hass))
    ]
    assert other in resources.async_items()


async def test_yaml_dashboards_get_a_log_line_instead(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    card_bundle: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    card_bundle.write_text(BUNDLE, encoding="utf-8")
    await _setup_dashboards(hass, {"resource_mode": "yaml"})
    caplog.set_level(logging.INFO, logger="custom_components.pulse_check")

    await _setup(hass, config_entry)

    url = await _expected_url(hass)
    assert f"url: {url}, type: module" in caplog.text
    assert _ours(hass) == []


async def test_yaml_dashboards_that_list_the_card_are_left_quiet(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    card_bundle: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    card_bundle.write_text(BUNDLE, encoding="utf-8")
    await _setup_dashboards(
        hass,
        {"resource_mode": "yaml", "resources": [{"url": f"{CARD_URL}?v=1", "type": "module"}]},
    )
    caplog.set_level(logging.INFO, logger="custom_components.pulse_check")

    await _setup(hass, config_entry)

    assert "managed in YAML" not in caplog.text


async def test_the_card_is_served_before_the_entry_sets_up(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    card_bundle: Path,
) -> None:
    """A dashboard opened while Home Assistant starts must be able to load it."""
    card_bundle.write_text(BUNDLE, encoding="utf-8")
    # The integration's own setup, with no config entry at all: what
    # Home Assistant has run by the time the entry is still setting up.
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(f"{CARD_URL}?v=0.0.0")
    assert response.status == 200
    assert await response.text() == BUNDLE


async def test_a_missing_bundle_is_logged_and_setup_carries_on(
    hass: HomeAssistant, config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    await _setup_dashboards(hass)

    await _setup(hass, config_entry)

    assert caplog.text.count("The Pulse Check card is missing") == 1
    assert _ours(hass) == []
    assert hass.states.get("sensor.pulse_check_attention") is not None


async def test_removing_the_integration_removes_the_resource(
    hass: HomeAssistant, config_entry: MockConfigEntry, card_bundle: Path
) -> None:
    card_bundle.write_text(BUNDLE, encoding="utf-8")
    await _setup_dashboards(hass)
    await _setup(hass, config_entry)
    assert len(_ours(hass)) == 1

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _ours(hass) == []
