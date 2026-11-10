"""Enhancers: Z-Wave JS node status, Zigbee2MQTT last_seen, and weak links.

The golden fixture happens to satisfy these rules in other ways (its dead
node's entities are unavailable anyway), so each is checked here on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices
from custom_components.pulse_check.core.enhancers import ENHANCERS
from custom_components.pulse_check.core.models import DeviceHealth, EntityEntry, EntityState

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
TWO_DAYS_AGO = NOW - timedelta(days=2)


def _state(
    entity_id: str, state: str, reported: datetime = EARLIER, **attributes: Any
) -> EntityState:
    """One entity's state, by its full entity id."""
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes,
        "last_changed": reported.isoformat(),
        "last_updated": reported.isoformat(),
        "last_reported": reported.isoformat(),
    }


def _analyse(platform: str, *states: EntityState, diagnostic: tuple[str, ...] = ()) -> DeviceHealth:
    """One device of `platform` with these states, analysed with every enhancer.

    Entities listed in `diagnostic` get `entity_category: diagnostic`.
    """
    entities: dict[str, EntityEntry] = {}
    for state in states:
        entity: EntityEntry = {
            "entity_id": state["entity_id"],
            "platform": platform,
            "device_id": "dev",
        }
        if state["entity_id"] in diagnostic:
            entity["entity_category"] = "diagnostic"
        entities[state["entity_id"]] = entity
    snapshot: Snapshot = {
        "states": {s["entity_id"]: s for s in states},
        "entities": entities,
        "devices": {
            "dev": {
                "id": "dev",
                "name": "Device",
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
    [device] = analyse_devices(snapshot, CoreConfig(), NOW, ENHANCERS)
    return device


@pytest.mark.parametrize(
    ("status", "offline", "severity"), [("dead", True, "critical"), ("asleep", False, "ok")]
)
def test_a_dead_zwave_node_is_offline_even_when_its_entities_are_available(
    status: str, offline: bool, severity: str
) -> None:
    """The controller has given up on it; its switch only shows the last known state."""
    device = _analyse(
        "zwave_js",
        _state("lock.front_door", "locked"),
        _state("sensor.front_door_node_status", status),
        diagnostic=("sensor.front_door_node_status",),
    )
    assert (device.is_offline, device.severity) == (offline, severity)


def _motion_sensor(last_seen: datetime) -> DeviceHealth:
    """A Zigbee2MQTT battery sensor whose states last reported two days ago."""
    return _analyse(
        "mqtt",
        _state("sensor.motion_battery", "80", TWO_DAYS_AGO, device_class="battery"),
        _state("binary_sensor.motion_occupancy", "off", TWO_DAYS_AGO),
        _state("sensor.motion_last_seen", last_seen.isoformat(), TWO_DAYS_AGO),
        diagnostic=("sensor.motion_battery", "sensor.motion_last_seen"),
    )


def test_a_newer_zigbee2mqtt_last_seen_is_when_the_device_was_last_heard() -> None:
    """Z2M's own last_seen is the true last heard, so the sensor is not quiet."""
    device = _motion_sensor(last_seen=EARLIER)
    assert device.last_heard == EARLIER
    assert (device.is_quiet, device.severity) == (False, "ok")


def test_an_older_zigbee2mqtt_last_seen_does_not_replace_newer_reports() -> None:
    device = _motion_sensor(last_seen=TWO_DAYS_AGO - timedelta(days=1))
    assert device.last_heard == TWO_DAYS_AGO
    assert (device.is_quiet, device.severity) == (True, "warning")


@pytest.mark.parametrize(
    ("platform", "entity_id"),
    [("mqtt", "sensor.plug_linkquality"), ("zha", "sensor.plug_lqi")],
)
@pytest.mark.parametrize(("lqi", "severity"), [(30, "warning"), (31, "ok")])
def test_a_link_quality_of_30_or_less_is_a_weak_link(
    platform: str, entity_id: str, lqi: int, severity: str
) -> None:
    device = _analyse(
        platform, _state("switch.plug", "on"), _state(entity_id, str(lqi)), diagnostic=(entity_id,)
    )
    assert [(e.label, e.value, e.severity) for e in device.extras] == [("LQI", str(lqi), severity)]
    assert device.severity == severity
