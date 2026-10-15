"""Battery history from the recorder, with the recorder's queries mocked.

The recorder itself is not started here (it needs a database). The two
query functions are replaced with fakes that return what the recorder
would, so the test covers everything from "which entities to ask about"
to the days-left value on the device.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check.const import DOMAIN
from tests.conftest import device_dicts, load_fixture_into_hass

DAY = timedelta(days=1)


class FakeRecorder:
    """Just enough of the recorder: run a function in the executor."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return self.hass.async_add_executor_job(func, *args)


def linear_rows(now: datetime, start_level: float, per_day: float) -> list[dict[str, Any]]:
    """Fourteen daily means ending yesterday."""
    return [
        {"start": (now - (14 - i) * DAY).timestamp(), "mean": start_level + i * per_day}
        for i in range(14)
    ]


@pytest.fixture
def recorder(hass: HomeAssistant, fixed_now: datetime) -> Iterator[dict[str, Any]]:
    """Pretend the recorder is loaded and answer its queries from canned data."""
    hass.config.components.add("recorder")
    calls: dict[str, Any] = {"statistics": [], "history": []}

    def statistics(
        _hass: HomeAssistant, start: datetime, end: Any, ids: set[str], period: str, *_: Any
    ) -> dict[str, list[dict[str, Any]]]:
        calls["statistics"].append((period, ids))
        if period == "hour":
            return {}  # no hourly statistics in this house
        # The motion sensor drops 2 %/day. The phone's means also decline
        # (its history looks like a clean drain). The window sensor drains
        # 1.5 %/day. The garage multisensor dipped and recovered once (a glitch).
        window = linear_rows(fixed_now, 60, -1.5)  # 60 % down to 40.5 %, live 40 %
        glitch = linear_rows(fixed_now, 68, -1)  # 68 % down to 55 %, live 55 %
        glitch[9]["mean"] = 42
        return {
            "sensor.living_room_motion_battery": linear_rows(fixed_now, 40, -2),
            "sensor.pixel_9_battery_level": linear_rows(fixed_now, 97, -2),
            "sensor.window_sensor_battery": window,
            "sensor.garage_multisensor_battery_level": glitch,
        }

    def history(
        _hass: HomeAssistant, start: datetime, end: Any, entity_id: str, **kwargs: Any
    ) -> dict[str, list[State]]:
        calls["history"].append((entity_id, kwargs.get("no_attributes")))
        if entity_id == "sensor.front_door_battery":
            # Raw history for a sensor without statistics: 1 %/day.
            return {
                entity_id: [
                    State(entity_id, str(100 - i), last_updated=fixed_now - (14 - i) * DAY)
                    for i in range(14)
                ]
            }
        if entity_id == "device_tracker.dog_collar":
            # Attribute battery: the level only appears when it changes.
            return {
                entity_id: [
                    State(
                        entity_id, "home", {"battery_level": 58}, last_updated=fixed_now - 10 * DAY
                    ),
                    State(entity_id, "away", last_updated=fixed_now - 6 * DAY),
                    State(
                        entity_id, "home", {"battery_level": 50}, last_updated=fixed_now - 2 * DAY
                    ),
                ]
            }
        return {entity_id: []}

    with (
        patch("custom_components.pulse_check.history.get_instance", FakeRecorder),
        patch("custom_components.pulse_check.history.statistics_during_period", statistics),
        patch("custom_components.pulse_check.history.state_changes_during_period", history),
    ):
        yield calls


async def test_drain_estimates_reach_the_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    recorder: dict[str, Any],
) -> None:
    freezer.move_to(fixed_now)
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN,
        "set_device_settings",
        {"device_id": device_ids["dev_z2m_door"], "rechargeable": True},
        blocking=True,
    )
    # The first history load runs as a background task, which
    # async_block_till_done does not wait for; run it explicitly instead.
    recorder["statistics"].clear()
    recorder["history"].clear()
    await config_entry.runtime_data.async_refresh_history()
    await hass.async_block_till_done()

    # One daily and one hourly statistics query for every numeric battery sensor at once.
    assert [period for period, _ in recorder["statistics"]] == ["day", "hour"]
    assert "sensor.living_room_motion_battery" in recorder["statistics"][0][1]
    assert "sensor.front_door_battery" in recorder["statistics"][0][1]
    # Raw history only for sensors without statistics (no attributes) and
    # for attribute batteries (with attributes).
    assert ("sensor.front_door_battery", True) in recorder["history"]
    assert ("device_tracker.dog_collar", False) in recorder["history"]

    by_name = {d["name"]: d for d in device_dicts(hass)}
    # 12 % at 2 %/day: about 6 days, from the current cycle's own trend.
    assert by_name["Living Room Motion"]["daysLeft"] == pytest.approx(6, abs=0.5)
    assert by_name["Living Room Motion"]["estimate"]["basis"] == "trend over current cycle"
    assert by_name["Living Room Motion"]["batteryKind"] == "replaceable"
    # 58 (carried forward to day -6), 50 at day -2, 44 now: about 1.4 %/day.
    assert by_name["Dog Collar Tracker"]["daysLeft"] == pytest.approx(31, abs=3)
    # No history at all: no estimate.
    assert "daysLeft" not in by_name["Kitchen H&T"]
    # A phone (mobile_app) is charged daily: never an estimate, however
    # clean its history looks.
    assert "daysLeft" not in by_name["Pixel 9"]
    # 40 % at 1.5 %/day: about 27 days.
    assert by_name["Window Sensor"]["daysLeft"] == pytest.approx(27, abs=3)
    # One dip-and-recover glitch does not cost the lock-like device its estimate.
    assert 30 < by_name["Garage Multisensor"]["daysLeft"] < 80
    # Phones are "charged"; the others are replaceable.
    assert by_name["Pixel 9"]["batteryKind"] == "charged"
    assert by_name["Garage Multisensor"]["batteryKind"] == "replaceable"
    # The user said this one is rechargeable: it gets a "charge in" estimate
    # instead. 87 % at about 1 %/day, down to the 30 % warning: ~57 days.
    door = by_name["Front Door Sensor"]
    assert door["batteryKind"] == "charged"
    assert door["estimate"]["kind"] == "charge"
    assert door["estimate"]["basis"] == "until charge needed"
    assert door["daysLeft"] == pytest.approx(57, abs=5)
    # And the docked, charging vacuum.
    assert "daysLeft" not in by_name["Mr Roboto"]

    soonest = hass.states.get("sensor.pulse_check_next_to_run_out")
    assert soonest is not None
    assert soonest.state == "Living Room Motion"
    assert soonest.attributes["days_left"] == pytest.approx(6, abs=0.5)
    assert soonest.attributes["entity_id"] == "sensor.living_room_motion_battery"


async def test_recorder_errors_keep_the_sensors_up(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    hass.config.components.add("recorder")

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("database locked")

    with (
        patch("custom_components.pulse_check.history.get_instance", FakeRecorder),
        patch("custom_components.pulse_check.history.statistics_during_period", broken),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        await config_entry.runtime_data.async_refresh_history()
        await hass.async_block_till_done()

    attention = hass.states.get("sensor.pulse_check_attention")
    assert attention is not None
    assert attention.state != "unavailable"
    assert hass.states.get("sensor.pulse_check_next_to_run_out").state == "unknown"  # type: ignore[union-attr]


async def test_the_first_history_load_waits_for_home_assistant_to_start(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    recorder: dict[str, Any],
) -> None:
    """At boot the recorder is not ready; the first read waits for the started event."""
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    hass.set_state(CoreState.not_running)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert recorder["statistics"] == []
    assert hass.states.get("sensor.pulse_check_next_to_run_out").state == "unknown"  # type: ignore[union-attr]

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [period for period, _ in recorder["statistics"]] == ["day", "hour"]
    assert hass.states.get("sensor.pulse_check_next_to_run_out").state == "Living Room Motion"  # type: ignore[union-attr]


async def test_insights_survive_an_options_reload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    recorder: dict[str, Any],
) -> None:
    """Saving options reloads the entry; the estimates must not vanish meanwhile."""
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.pulse_check_next_to_run_out").state == "Living Room Motion"  # type: ignore[union-attr]

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("database locked")

    # The reloaded entry's own first read fails: it keeps the previous insights.
    with patch("custom_components.pulse_check.history.statistics_during_period", broken):
        await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.pulse_check_next_to_run_out").state == "Living Room Motion"  # type: ignore[union-attr]
