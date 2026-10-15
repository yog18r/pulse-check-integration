"""Device type classification over the fixture."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices


def test_fixture_devices_are_classified(
    fixture_snapshot: dict[str, Any], fixed_now: datetime
) -> None:
    snapshot: Snapshot = fixture_snapshot  # type: ignore[assignment]
    by_name = {d.name: d.device_type for d in analyse_devices(snapshot, CoreConfig(), fixed_now)}
    assert by_name["Front Door Sensor"] == "contact"
    assert by_name["Living Room Motion"] == "motion"
    assert by_name["Bedroom Temp & Humidity"] == "climate"
    assert by_name["Garage Multisensor"] == "motion"  # motion wins over temperature
    assert by_name["Front Door Lock"] == "lock"
    assert by_name["Office Plug"] == "switch"
    assert by_name["Pixel 9"] == "phone"
    assert by_name["Dog Collar Tracker"] == "phone"  # tracker with a battery
    assert by_name["Mr Roboto"] == "vacuum"
    assert by_name["Garage Lights"] == "light"
    assert by_name["Plant Monitor"] == "other"
    assert by_name["TV Remote Battery"] == "other"  # a lone sensor says nothing
