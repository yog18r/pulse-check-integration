"""Charging: a device being charged is never flagged for its level.

One case per signal the README lists under "How detection works", each with
a look-alike that must not count.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices
from custom_components.pulse_check.core.battery import detect_battery, detect_charging
from custom_components.pulse_check.core.models import EntityState

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
EARLIER = "2026-11-10T11:00:00+00:00"


def _state(entity_id: str, state: str, **attributes: Any) -> EntityState:
    """One entity's state, by its full entity id."""
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes,
        "last_changed": EARLIER,
        "last_updated": EARLIER,
        "last_reported": EARLIER,
    }


@pytest.mark.parametrize(
    ("state", "charging"),
    [
        pytest.param(
            _state("binary_sensor.phone_is_charging", "on", device_class="battery_charging"),
            True,
            id="battery_charging binary sensor on",
        ),
        pytest.param(
            _state("binary_sensor.phone_is_charging", "off", device_class="battery_charging"),
            False,
            id="battery_charging binary sensor off",
        ),
        pytest.param(
            _state("sensor.phone_battery_state", "charging"), True, id="battery state charging"
        ),
        pytest.param(_state("sensor.phone_battery_state", "full"), True, id="battery state full"),
        pytest.param(
            _state("sensor.phone_battery_state", "discharging"),
            False,
            id="battery state discharging",
        ),
        pytest.param(_state("vacuum.robot", "docked"), True, id="vacuum docked"),
        pytest.param(_state("vacuum.robot", "cleaning"), False, id="vacuum cleaning"),
        pytest.param(
            _state("sensor.tablet", "idle", is_charging=True), True, id="is_charging attribute"
        ),
        pytest.param(_state("sensor.tablet", "idle", charging=True), True, id="charging attribute"),
        pytest.param(
            _state("sensor.tablet", "idle", battery_charging=True),
            True,
            id="battery_charging attribute",
        ),
        pytest.param(
            _state("sensor.tablet", "idle", is_charging=False, charging=False),
            False,
            id="charging attributes false",
        ),
        pytest.param(
            _state("sensor.tablet", "idle", battery_state="charging"),
            True,
            id="battery_state attribute charging",
        ),
        pytest.param(
            _state("sensor.tablet", "idle", battery_state="discharging"),
            False,
            id="battery_state attribute discharging",
        ),
    ],
)
def test_each_charging_signal_is_recognised(state: EntityState, charging: bool) -> None:
    assert detect_charging([state]) is charging


def test_a_charging_signal_marks_the_battery_reading_as_charging() -> None:
    """The signal and the level come from different entities of the same device."""
    level = _state("sensor.phone_battery_level", "10", device_class="battery")
    plugged = _state("binary_sensor.phone_is_charging", "on", device_class="battery_charging")
    reading = detect_battery([level, plugged])
    assert reading is not None
    assert (reading.level, reading.is_charging) == (10, True)


def _phone(charging: str) -> Snapshot:
    """A companion-app phone at 10 % whose charging sensor reads `charging`."""
    states = [
        _state("sensor.phone_battery_level", "10", device_class="battery"),
        _state("binary_sensor.phone_is_charging", charging, device_class="battery_charging"),
    ]
    return {
        "states": {s["entity_id"]: s for s in states},
        "entities": {
            s["entity_id"]: {
                "entity_id": s["entity_id"],
                "platform": "mobile_app",
                "device_id": "dev_phone",
            }
            for s in states
        },
        "devices": {
            "dev_phone": {
                "id": "dev_phone",
                "name": "Phone",
                "name_by_user": None,
                "manufacturer": None,
                "model": None,
                "area_id": None,
                "entry_type": None,
                "disabled_by": None,
            }
        },
        "areas": {},
    }


@pytest.mark.parametrize(("charging", "severity"), [("on", "ok"), ("off", "critical")])
def test_a_phone_at_ten_percent_is_only_flagged_when_not_charging(
    charging: str, severity: str
) -> None:
    [device] = analyse_devices(_phone(charging), CoreConfig(), NOW)
    assert device.battery is not None
    assert device.battery.level == 10
    assert (device.battery.is_charging, device.severity) == (charging == "on", severity)
