"""Shared pytest fixtures.

`pytest_homeassistant_custom_component` provides a real, in-memory Home
Assistant instance as the `hass` fixture, plus helpers to add config
entries and fire events. `enable_custom_integrations` tells that instance
to load integrations from `custom_components/` as well as its built-ins;
it is applied to every test here so nobody forgets it.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load `custom_components/` in every test."""


@pytest.fixture(scope="session")
def fixture_snapshot() -> dict[str, Any]:
    """The card's fixture, exported as JSON (`buildHass(FIXED_NOW)`)."""
    return json.loads((FIXTURES / "hass.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def golden() -> dict[str, Any]:
    """The card's expected output for each golden case."""
    return json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def fixed_now(golden: dict[str, Any]) -> datetime:
    """The `now` the golden output was computed at: 2026-10-15T10:00:00Z."""
    return datetime.fromisoformat(golden["now"])
