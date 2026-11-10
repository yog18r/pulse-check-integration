"""Battery levels are "at or below", and the most specific quiet threshold wins."""

from __future__ import annotations

import pytest

from custom_components.pulse_check.core import BatteryReading, CoreConfig, DeviceSettings
from custom_components.pulse_check.core.thresholds import battery_severity, resolve_quiet_threshold


def _battery(level: int) -> BatteryReading:
    return BatteryReading(is_low=False, source="sensor", entity_id="sensor.battery", level=level)


@pytest.mark.parametrize(
    ("level", "severity"), [(15, "critical"), (16, "warning"), (30, "warning"), (31, "ok")]
)
def test_the_default_levels_include_the_level_itself(level: int, severity: str) -> None:
    """Defaults: critical at or below 15 %, warning at or below 30 %."""
    assert battery_severity(_battery(level), CoreConfig()) == severity


@pytest.mark.parametrize(
    ("level", "severity"), [(5, "critical"), (6, "warning"), (10, "warning"), (11, "ok")]
)
def test_a_devices_own_levels_include_the_level_itself(level: int, severity: str) -> None:
    """A phone charged every night: warning at 10 %, critical at 5 %."""
    config = CoreConfig(
        device_settings=(DeviceSettings("dev", battery_warning=10, battery_critical=5),)
    )
    assert battery_severity(_battery(level), config, "dev") == severity


QUIET = CoreConfig(
    quiet_threshold_hours=24,
    integration_thresholds={"zwave_js": 48},
    device_settings=(DeviceSettings("dev_lock", quiet_threshold_hours=6),),
)


@pytest.mark.parametrize(
    ("integration", "device_id", "hours"),
    [
        pytest.param("zwave_js", "dev_lock", 6, id="device beats integration"),
        pytest.param("zha", "dev_lock", 6, id="device beats default"),
        pytest.param("zwave_js", "dev_other", 48, id="integration beats default"),
        pytest.param("zha", "dev_other", 24, id="default"),
    ],
)
def test_the_most_specific_quiet_threshold_wins(
    integration: str, device_id: str, hours: float
) -> None:
    assert resolve_quiet_threshold(QUIET, integration, device_id) == hours
