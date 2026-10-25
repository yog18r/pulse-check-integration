"""Offline: judged by the entities that can tell whether the hardware answers.

Primary entities (no category) decide. A device without any falls back to
its other entities, but settings and update checkers never count: Home
Assistant's SkyConnect has only a firmware update entity and a settings
switch, and the update entity goes unavailable whenever its firmware check
fails, while the Zigbee radio carries on working.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices, summarise
from custom_components.pulse_check.core.availability import detect_offline
from custom_components.pulse_check.core.models import EntityEntry, EntityState

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
EARLIER = "2026-10-23T11:00:00.000Z"


def _entity(entity_id: str, category: str | None = None) -> EntityEntry:
    entity: dict[str, Any] = {"entity_id": entity_id, "platform": "test", "device_id": "dev"}
    if category is not None:
        entity["entity_category"] = category
    return entity  # type: ignore[return-value]


def _states(**states: str) -> dict[str, EntityState]:
    """`update_firmware="unavailable"` -> {"update.firmware": {...}}."""
    out: dict[str, EntityState] = {}
    for key, state in states.items():
        entity_id = key.replace("_", ".", 1)
        out[entity_id] = {
            "entity_id": entity_id,
            "state": state,
            "attributes": {},
            "last_changed": EARLIER,
            "last_updated": EARLIER,
            "last_reported": EARLIER,
        }
    return out


def test_a_failed_firmware_check_is_not_offline() -> None:
    """The SkyConnect: nothing but an update checker and a settings switch."""
    entities = [_entity("update.firmware", "config"), _entity("switch.beta", "config")]
    states = _states(update_firmware="unavailable", switch_beta="unavailable")
    assert not detect_offline(entities, states)


def test_diagnostic_entities_still_decide_without_primary_ones() -> None:
    entities = [_entity("sensor.signal", "diagnostic"), _entity("update.firmware", "config")]
    assert detect_offline(entities, _states(sensor_signal="unavailable", update_firmware="on"))
    assert not detect_offline(entities, _states(sensor_signal="-60", update_firmware="unavailable"))


def test_primary_entities_decide_as_before() -> None:
    entities = [
        _entity("switch.plug"),
        _entity("sensor.signal", "diagnostic"),
        _entity("update.firmware", "config"),
    ]
    down = _states(switch_plug="unavailable", sensor_signal="-60", update_firmware="off")
    assert detect_offline(entities, down)
    up = _states(switch_plug="on", sensor_signal="unavailable", update_firmware="unavailable")
    assert not detect_offline(entities, up)


def test_the_skyconnect_reads_as_ok() -> None:
    """Through the whole analysis: listed, not offline, nothing to report."""
    snapshot: Snapshot = {
        "states": _states(update_skyconnect="unavailable"),
        "entities": {
            "update.skyconnect": {
                "entity_id": "update.skyconnect",
                "platform": "homeassistant_sky_connect",
                "device_id": "dev_skyconnect",
                "entity_category": "config",
            }
        },
        "devices": {
            "dev_skyconnect": {
                "id": "dev_skyconnect",
                "name": "Home Assistant SkyConnect",
                "name_by_user": None,
                "manufacturer": "Nabu Casa",
                "model": "SkyConnect",
                "area_id": None,
                "entry_type": None,
                "disabled_by": None,
            }
        },
        "areas": {},
    }
    devices = analyse_devices(snapshot, CoreConfig(), NOW)
    assert [(d.device_id, d.is_offline, d.severity) for d in devices] == [
        ("dev_skyconnect", False, "ok")
    ]


def _unifi_policy(*entities: EntityEntry, states: dict[str, EntityState]) -> Snapshot:
    """One device, "UniFi Network Allow DNS", with the given entities."""
    return {
        "states": states,
        "entities": {e["entity_id"]: e for e in entities},
        "devices": {
            "dev": {
                "id": "dev",
                "name": "UniFi Network Allow DNS",
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


def _not_provided(entity_id: str) -> EntityEntry:
    entity = _entity(entity_id)
    entity["not_provided"] = True
    return entity


def test_entities_the_integration_dropped_are_not_provided_not_offline() -> None:
    """What a UniFi update leaves behind: stale configuration, a warning."""
    snapshot = _unifi_policy(
        _not_provided("switch.allow_dns"), states=_states(switch_allow_dns="unavailable")
    )
    [device] = analyse_devices(snapshot, CoreConfig(), NOW)
    assert (device.is_offline, device.is_not_provided, device.is_quiet) == (False, True, False)
    assert device.severity == "warning"
    assert device.to_dict()["isNotProvided"] is True
    assert summarise([device], CoreConfig()).to_dict()["notProvided"] == 1


def test_one_real_unavailable_entity_makes_it_offline() -> None:
    snapshot = _unifi_policy(
        _not_provided("switch.allow_dns"),
        _entity("switch.block_ads"),
        states=_states(switch_allow_dns="unavailable", switch_block_ads="unavailable"),
    )
    [device] = analyse_devices(snapshot, CoreConfig(), NOW)
    assert (device.is_offline, device.is_not_provided, device.severity) == (True, False, "critical")
    assert "isNotProvided" not in device.to_dict()


def test_a_working_entity_beside_a_dropped_one_is_fine() -> None:
    snapshot = _unifi_policy(
        _not_provided("switch.allow_dns"),
        _entity("switch.block_ads"),
        states=_states(switch_allow_dns="unavailable", switch_block_ads="on"),
    )
    [device] = analyse_devices(snapshot, CoreConfig(), NOW)
    assert (device.is_offline, device.is_not_provided, device.severity) == (False, False, "ok")
