"""Defences against bad input: service values, a damaged saved file, overlapping reads."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import probatio
import pytest
from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.pulse_check.coordinator import PulseCheckCoordinator
from custom_components.pulse_check.core import CoreConfig
from custom_components.pulse_check.core.models import BatteryReading, DeviceHealth
from custom_components.pulse_check.history import HistoryTracker
from custom_components.pulse_check.notify import log_transition
from custom_components.pulse_check.services import (
    MARK_SCHEMA,
    MAX_TEXT_LENGTH,
    SET_DEVICE_SETTINGS_SCHEMA,
    SNOOZE_SCHEMA,
    _text_or_clear,
)
from custom_components.pulse_check.storage import PulseCheckStore, normalise

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
        "maintenance": {"started_at": GOOD_TIME, "until": GOOD_TIME},
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


# -- limits on service values -------------------------------------------------


@pytest.mark.parametrize("hours", [1e12, float("inf"), 24 * 365 + 1])
def test_a_quiet_time_beyond_a_year_is_refused(hours: float) -> None:
    """A huge one overflowed the analysis and stopped every refresh."""
    with pytest.raises(probatio.Invalid):
        SET_DEVICE_SETTINGS_SCHEMA({"device_id": "dev_a", "quiet_threshold_hours": hours})
    assert SET_DEVICE_SETTINGS_SCHEMA({"device_id": "dev_a", "quiet_threshold_hours": 24 * 365})


def test_a_snooze_beyond_ten_years_is_refused() -> None:
    with pytest.raises(probatio.Invalid):
        SNOOZE_SCHEMA({"device_id": "dev_a", "days": 1e9})


def test_a_marked_battery_type_is_text() -> None:
    with pytest.raises(probatio.Invalid):
        MARK_SCHEMA({"device_id": "dev_a", "battery_type": {"type": "AA"}})
    assert MARK_SCHEMA({"device_id": "dev_a", "battery_type": " AA "})["battery_type"] == "AA"


# -- the saved file, one level down -------------------------------------------


def test_bad_records_inside_a_section_are_left_out() -> None:
    data = normalise(
        {
            "levels": {
                "dev_a": {"level": 80, "jump": {"from": 40, "at": GOOD_TIME}},
                "dev_b": {"level": 80, "jump": {"from": 40, "at": "never"}},
                "dev_c": {"level": 80, "sudden_drop_at": 7},
            },
            "notify": {
                "dev_a": {
                    "quiet": {"since": GOOD_TIME},
                    "offline": {"since": "never"},
                    "battery_low": {"since": GOOD_TIME, "held": {"at": GOOD_TIME}},
                },
            },
            "device_settings": {
                "dev_a": {"name": "Kitchen", "quiet_threshold_hours": 1e12},
                "dev_b": {"quiet_threshold_hours": 48},
            },
            "maintenance": {"until": GOOD_TIME},
        }
    )
    assert list(data["levels"]) == ["dev_a"]
    # A held message must say which integration it is held for.
    assert data["notify"] == {"dev_a": {"quiet": {"since": GOOD_TIME}}}
    assert data["device_settings"] == {
        "dev_a": {"name": "Kitchen"},
        "dev_b": {"quiet_threshold_hours": 48},
    }
    # A window that does not say when it began cannot summarise it.
    assert data["maintenance"] == {}


# -- the logbook --------------------------------------------------------------


async def test_an_entity_with_no_device_gets_the_line_on_its_own_logbook(
    hass: HomeAssistant,
) -> None:
    events = async_capture_events(hass, EVENT_LOGBOOK_ENTRY)
    log_transition(hass, "entity:sensor.inverter_soc", "Inverter", "Inverter: unavailable")
    log_transition(hass, "dev_a", "Kitchen", "Kitchen: offline")
    await hass.async_block_till_done()
    assert [(e.data.get("entity_id"), e.data.get("device_id")) for e in events] == [
        ("sensor.inverter_soc", None),
        (None, "dev_a"),
    ]


# -- history reads ------------------------------------------------------------


async def test_a_reload_judges_recent_history_again_without_reading_it(
    hass: HomeAssistant,
) -> None:
    """Saving the options re-reads nothing the last six hours already read."""
    hass.config.components.add("recorder")
    tracker = HistoryTracker(hass)
    device = DeviceHealth(
        device_id="dev_a",
        name="Kitchen",
        integration="zha",
        is_offline=False,
        is_quiet=False,
        quiet_threshold_hours=24,
        severity="ok",
        source="device",
        battery=BatteryReading(is_low=False, source="sensor", entity_id="sensor.a", level=50),
    )
    store = PulseCheckStore(hass)
    fetch = AsyncMock(return_value=({"sensor.a": []}, {"sensor.a": []}))
    with patch.object(tracker, "_fetch", fetch):
        await tracker.async_refresh([device], store, CoreConfig())
        await tracker.async_refresh([device], store, CoreConfig(), reuse=True)
        assert fetch.await_count == 1
        # The timer's and the refresh service's reads always go to the recorder.
        await tracker.async_refresh([device], store, CoreConfig())
        assert fetch.await_count == 2
    assert "sensor.a" in tracker.insights
