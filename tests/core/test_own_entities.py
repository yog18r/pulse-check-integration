"""Pulse Check's own entities never decide whether a device is alive.

Its per-device sensors update on every run, so counting them would make a
device whose real sensors went quiet look freshly heard from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices


def test_pulse_check_entities_on_a_device_are_ignored() -> None:
    """The per-device sensors update every run; they must not make a device look alive."""
    long_ago = "2026-09-01T00:00:00.000Z"
    just_now = "2026-11-08T11:59:00.000Z"

    def state(entity_id: str, value: str, at: str, **attributes: Any) -> dict[str, Any]:
        return {
            "entity_id": entity_id,
            "state": value,
            "attributes": attributes,
            "last_changed": at,
            "last_updated": at,
            "last_reported": at,
        }

    # Built by hand, so loosely typed; the core reads it as a Snapshot.
    snapshot: dict[str, Any] = {
        "states": {
            "sensor.door_battery": state(
                "sensor.door_battery", "60", long_ago, device_class="battery"
            ),
            "sensor.door_battery_days_left": state("sensor.door_battery_days_left", "40", just_now),
            "sensor.door_battery_last_replaced": state(
                "sensor.door_battery_last_replaced", "x", just_now
            ),
        },
        "entities": {
            "sensor.door_battery": {
                "entity_id": "sensor.door_battery",
                "device_id": "dev",
                "platform": "zha",
            },
            "sensor.door_battery_days_left": {
                "entity_id": "sensor.door_battery_days_left",
                "device_id": "dev",
                "platform": "pulse_check",
                "entity_category": "diagnostic",
            },
            "sensor.door_battery_last_replaced": {
                "entity_id": "sensor.door_battery_last_replaced",
                "device_id": "dev",
                "platform": "pulse_check",
                "entity_category": "diagnostic",
            },
        },
        "devices": {
            "dev": {
                "id": "dev",
                "name": "Door",
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
    typed: Snapshot = snapshot  # type: ignore[assignment]
    [door] = analyse_devices(typed, CoreConfig(), datetime(2026, 11, 8, 12, 0, tzinfo=UTC))
    assert door.integration == "zha"  # not "pulse_check", which would drop it
    assert door.is_quiet
    assert door.entity_ids == ["sensor.door_battery"]
