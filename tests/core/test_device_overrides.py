"""Per-device battery levels and the one rule for "charged or replaced"."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pulse_check.core import CoreConfig
from custom_components.pulse_check.core.actions import action_list
from custom_components.pulse_check.core.cycles import Cycle, classify_battery
from custom_components.pulse_check.core.models import BatteryReading, DeviceHealth
from custom_components.pulse_check.core.settings import is_charged
from custom_components.pulse_check.core.thresholds import battery_levels, battery_severity
from custom_components.pulse_check.options import levels_clash


def _device(
    device_id: str = "dev",
    level: int = 20,
    integration: str = "zha",
    battery_kind: str | None = None,
    device_type: str = "other",
) -> DeviceHealth:
    return DeviceHealth(
        device_id=device_id,
        name=device_id.title(),
        integration=integration,
        is_offline=False,
        is_quiet=False,
        quiet_threshold_hours=24,
        severity="warning",
        device_type=device_type,
        battery=BatteryReading(is_low=False, source="sensor", entity_id="sensor.x", level=level),
        battery_kind=battery_kind,
    )


def _config(**settings: object) -> CoreConfig:
    return CoreConfig.from_dict({"device_settings": [{"device_id": "dev", **settings}]})


def test_a_device_uses_its_own_levels_and_others_the_options() -> None:
    config = _config(battery_warning=10, battery_critical=5)
    assert battery_levels(config, "dev") == (10, 5)
    assert battery_levels(config, "other") == (30, 15)
    battery = BatteryReading(is_low=False, source="sensor", entity_id="sensor.x", level=12)
    assert battery_severity(battery, config, "dev") == "ok"
    assert battery_severity(battery, config, "other") == "critical"
    assert battery_severity(battery, config) == "critical"


def test_one_own_level_keeps_the_other_from_the_options() -> None:
    assert battery_levels(_config(battery_warning=50), "dev") == (50, 15)


@pytest.mark.parametrize(
    ("settings", "clash"),
    [
        ({}, False),
        ({"battery_warning": 10}, True),  # under the 15 % critical default
        ({"battery_warning": 10, "battery_critical": 5}, False),
        ({"battery_critical": 40}, True),  # over the 30 % warning default
        ({"battery_critical": 30}, False),
    ],
)
def test_levels_clash_against_the_options_defaults(settings: dict[str, float], clash: bool) -> None:
    assert levels_clash(CoreConfig(), settings) is clash


@pytest.mark.parametrize(
    ("device", "rechargeable", "charged"),
    [
        (_device(integration="mobile_app"), None, True),  # a phone, before any history
        (_device(device_type="vacuum"), None, True),
        (_device(), None, False),
        (_device(battery_kind="charged"), None, True),  # what the history showed
        (_device(integration="mobile_app", battery_kind="replaceable"), None, False),
        (_device(battery_kind="charged"), False, False),  # the user's say wins
        (_device(), True, True),
    ],
)
def test_is_charged(device: DeviceHealth, rechargeable: bool | None, charged: bool) -> None:
    assert is_charged(device, rechargeable) is charged


def test_a_phone_low_on_charge_is_charged_not_replaced() -> None:
    """It used to read "Replace the battery in …" unless ticked rechargeable."""
    phone = _device("phone", integration="mobile_app")
    lock = _device("lock")
    actions = action_list([phone, lock], CoreConfig())
    assert [item.label for item in actions.charge] == ["Charge Phone"]
    assert [item.label for item in actions.replace] == ["Replace the battery in Lock"]
    assert [line.count for line in actions.shopping] == [1]


def test_actions_use_the_device_s_own_levels() -> None:
    config = CoreConfig.from_dict(
        {"device_settings": [{"device_id": "phone", "battery_warning": 10, "battery_critical": 5}]}
    )
    phone = _device("phone", level=20, integration="mobile_app")
    assert action_list([phone], config).charge == []


def test_the_user_can_say_a_battery_is_replaced() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    cycles = [
        Cycle(start, start + timedelta(days=10), 60, 20, ()),
        Cycle(start + timedelta(days=10), start + timedelta(days=18), 55, 25, ()),
    ]
    assert classify_battery(cycles, mobile_app=True) == "charged"
    assert classify_battery(cycles, mobile_app=True, rechargeable=False) == "replaceable"
    assert classify_battery(cycles, rechargeable=True) == "charged"


def test_critical_is_never_above_warning_after_the_options_change() -> None:
    """Saved with a 30 % warning; then the general warning dropped to 8 %."""
    config = CoreConfig.from_dict(
        {"battery_warning": 8, "device_settings": [{"device_id": "dev", "battery_critical": 10}]}
    )
    assert battery_levels(config, "dev") == (8, 8)
