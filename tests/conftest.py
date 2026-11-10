"""Shared pytest fixtures.

`pytest_homeassistant_custom_component` provides a real, in-memory Home
Assistant instance as the `hass` fixture, plus helpers to add config
entries and fire events. `enable_custom_integrations` tells that instance
to load integrations from `custom_components/` as well as its built-ins;
it is applied to every test here so nobody forgets it.
"""

from __future__ import annotations

import functools
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check import card
from custom_components.pulse_check.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load `custom_components/` in every test."""


@pytest.fixture(autouse=True)
def card_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Where the integration looks for the card bundle, absent by default.

    The real bundle exists only after a frontend build, so tests never
    depend on it. Tests that want the card served write this file first.
    """
    path = tmp_path / "pulse-check-card.js"
    monkeypatch.setattr(card, "CARD_PATH", path)
    return path


@functools.cache
def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixture_snapshot() -> dict[str, Any]:
    """The card's fixture, exported as JSON (`buildHass(FIXED_NOW)` in frontend/test/fixtures).

    A fresh copy per test, so a test that changes it cannot leak into the next.
    """
    return json.loads(_read_fixture("hass.json"))  # type: ignore[no-any-return]


@pytest.fixture
def golden() -> dict[str, Any]:
    """The card's expected output for each golden case, a fresh copy per test."""
    return json.loads(_read_fixture("golden.json"))  # type: ignore[no-any-return]


@pytest.fixture
def fixed_now(golden: dict[str, Any]) -> datetime:
    """The `now` the golden output was computed at: 2026-10-15T10:00:00Z."""
    return datetime.fromisoformat(golden["now"])


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A Pulse Check config entry, added to hass but not yet set up."""
    entry = MockConfigEntry(domain=DOMAIN, title="Pulse Check", unique_id=DOMAIN, data={})
    entry.add_to_hass(hass)
    return entry
