"""Defences against bad input: service values, a damaged saved file, overlapping reads."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import probatio
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check.coordinator import PulseCheckCoordinator
from custom_components.pulse_check.services import MAX_TEXT_LENGTH, _text_or_clear
from custom_components.pulse_check.storage import normalise

# -- service values -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("  Kitchen  ", "Kitchen"),
        ("", ""),
        ("   ", ""),
        # YAML reads a battery type of 2032 as a number.
        (2032, "2032"),
        (1.5, "1.5"),
    ],
)
def test_text_values_are_text(value: object, expected: str | None) -> None:
    assert _text_or_clear(value) == expected


@pytest.mark.parametrize(
    "value", [{"name": "Kitchen"}, ["Kitchen"], True, "x" * (MAX_TEXT_LENGTH + 1)]
)
def test_anything_else_is_refused(value: object) -> None:
    with pytest.raises(probatio.Invalid):
        _text_or_clear(value)


# -- the saved file -----------------------------------------------------------

GOOD_TIME = "2026-11-14T10:00:00+00:00"


def test_a_good_file_is_read_as_it_is() -> None:
    saved: dict[str, Any] = {
        "device_settings": {"dev_a": {"name": "Kitchen"}},
        "snoozes": {"dev_a": GOOD_TIME},
        "notify": {"dev_a": {"quiet": {"since": GOOD_TIME}}},
        "digests": {"daily": GOOD_TIME},
        "history": {"dev_a": {"events": [{"at": GOOD_TIME, "kind": "replaced"}], "cycles": []}},
        "levels": {"dev_a": {"level": 80}},
        "maintenance": {"until": GOOD_TIME},
        "gone": {"dev_b": GOOD_TIME},
        "heard": {"dev_a": GOOD_TIME},
        "from_a_newer_version": {"kept": True},
    }
    assert normalise(saved) == saved


def test_a_missing_section_gets_its_default() -> None:
    data = normalise({"snoozes": {"dev_a": GOOD_TIME}})
    assert data["snoozes"] == {"dev_a": GOOD_TIME}
    assert data["device_settings"] == {}
    assert data["heard"] == {}


def test_only_the_bad_records_are_left_out(caplog: pytest.LogCaptureFixture) -> None:
    data = normalise(
        {
            "device_settings": {"dev_a": {"name": "Kitchen"}, "dev_b": "not settings"},
            "snoozes": {"dev_a": GOOD_TIME, "dev_b": "next tuesday", "dev_c": 5},
            "heard": ["not", "a", "mapping"],
            "history": {
                "dev_a": {
                    "events": [{"at": GOOD_TIME}, {"at": "never"}, "junk"],
                    "cycles": [{"days": 30}, 7],
                },
                "dev_b": "junk",
            },
            "maintenance": {"until": "soon"},
        }
    )
    assert data["device_settings"] == {"dev_a": {"name": "Kitchen"}}
    assert data["snoozes"] == {"dev_a": GOOD_TIME}
    assert data["heard"] == {}
    assert data["history"] == {"dev_a": {"events": [{"at": GOOD_TIME}], "cycles": [{"days": 30}]}}
    assert data["maintenance"] == {}
    assert "Left out 7 unreadable records" in caplog.text


# -- history reads ------------------------------------------------------------


async def test_history_reads_never_overlap(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A catch-up merging into a full read's result must not race it."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator: PulseCheckCoordinator = config_entry.runtime_data
    running = 0
    most = 0

    async def read(*_args: object, **_kwargs: object) -> None:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0)
        running -= 1

    with patch.object(coordinator.history, "async_refresh", read):
        await asyncio.gather(
            coordinator.async_refresh_history(),
            coordinator.async_catch_up_history({"sensor.a"}),
            coordinator.async_refresh_history(),
        )
    assert most == 1
