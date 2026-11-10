"""Battery history read from a real recorder, not the fakes in `test_history.py`.

The fakes accept any arguments, so a changed Home Assistant signature or row
shape could not fail them. This smoke test imports two weeks of hourly
statistics into a real (in-memory) recorder and checks an estimate comes out.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.recorder.core import Recorder
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.pulse_check.const import DOMAIN

ENTITY_ID = "sensor.smoke_alarm_battery"
PER_DAY = 2.0


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """Replaces conftest's: the recorder must be set up before Home Assistant is."""


async def _battery_device(hass: HomeAssistant) -> None:
    """One smoke alarm at 40 %, on a device of its own."""
    owner = MockConfigEntry(domain="test_fixture", title="Fixture")
    owner.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={("test_fixture", "smoke")}, name="Smoke Alarm"
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        "zha",
        "smoke_battery",
        suggested_object_id="smoke_alarm_battery",
        device_id=device.id,
    )
    hass.states.async_set(ENTITY_ID, "40", {"device_class": "battery", "unit_of_measurement": "%"})


def _hourly_means() -> list[StatisticData]:
    """Fourteen days of hourly means, falling `PER_DAY` % a day to 40 % now."""
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    hours = 14 * 24
    rows: list[StatisticData] = []
    for i in range(hours, 0, -1):
        level = 40 + PER_DAY * i / 24
        rows.append({"start": now - timedelta(hours=i), "mean": level, "min": level, "max": level})
    return rows


async def test_an_estimate_comes_from_real_recorder_statistics(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    await _battery_device(hass)
    metadata: StatisticMetaData = {
        "has_sum": False,
        "mean_type": StatisticMeanType.ARITHMETIC,
        "name": None,
        "source": "recorder",
        "statistic_id": ENTITY_ID,
        "unit_class": None,
        "unit_of_measurement": "%",
    }
    async_import_statistics(hass, metadata, _hourly_means())
    await async_wait_recording_done(hass)

    entry = MockConfigEntry(domain=DOMAIN, title="Pulse Check", unique_id=DOMAIN, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    await coordinator.async_refresh_history()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert "Reading battery history from the recorder failed" not in caplog.text
    insight = coordinator.history.insights.get(ENTITY_ID)
    assert insight is not None
    assert insight.estimate is not None
    # 40 % left at 2 % a day.
    assert insight.estimate.days_left == pytest.approx(40 / PER_DAY, rel=0.25)
