"""Entities with no registry entry: watched as device-less battery readings.

An entity without a `unique_id` (a YAML template sensor, some MQTT
entities) exists only in the state machine. The golden fixture has one
(`sensor.garden_soil_moisture`); these tests pin the edges around it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
LONG_AGO = "2026-09-01T00:00:00.000Z"


def _state(entity_id: str, state: str, **attributes: Any) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes,
        "last_changed": LONG_AGO,
        "last_updated": LONG_AGO,
        "last_reported": LONG_AGO,
    }


def _snapshot(*states: dict[str, Any], entities: dict[str, Any] | None = None) -> Snapshot:
    return {
        "states": {state["entity_id"]: state for state in states},  # type: ignore[misc]
        "entities": entities or {},
        "devices": {},
        "areas": {},
    }


def _ids(snapshot: Snapshot, **config: Any) -> list[str]:
    devices = analyse_devices(snapshot, CoreConfig.from_dict(config), NOW)
    return [device.device_id for device in devices]


def test_a_battery_without_a_registry_entry_is_watched() -> None:
    snapshot = _snapshot(
        _state("binary_sensor.shed_battery_low", "on", device_class="battery"),
        _state("sensor.shed_temperature", "14", device_class="temperature"),
        _state("sun.sun", "above_horizon"),
    )
    devices = analyse_devices(snapshot, CoreConfig(), NOW)
    assert [device.device_id for device in devices] == ["entity:binary_sensor.shed_battery_low"]
    shed = devices[0]
    assert shed.integration == "unknown"
    assert shed.severity == "critical"  # a binary low battery
    # Unheard of for six weeks, yet neither offline nor quiet: with no
    # device behind it there is nothing that could be.
    assert not shed.is_offline
    assert not shed.is_quiet


def test_it_can_be_excluded_like_any_entity() -> None:
    snapshot = _snapshot(_state("sensor.shed_battery", "50", device_class="battery"))
    assert _ids(snapshot) == ["entity:sensor.shed_battery"]
    assert _ids(snapshot, exclude_entities=["sensor.shed_battery"]) == []
    assert _ids(snapshot, exclude_devices=["sensor.shed_battery"]) == []
    assert _ids(snapshot, exclude_devices=["entity:sensor.shed_battery"]) == []
    assert _ids(snapshot, exclude_integrations=["unknown"]) == []


def test_a_registry_entry_still_decides_the_category_rule() -> None:
    """A config entity keeps its registry entry, so it never becomes a bare state."""
    snapshot = _snapshot(
        _state("sensor.inverter_min_soc", "10", device_class="battery"),
        entities={
            "sensor.inverter_min_soc": {
                "entity_id": "sensor.inverter_min_soc",
                "platform": "foxess",
                "entity_category": "config",
            }
        },
    )
    assert _ids(snapshot) == []
