"""Offline: judged by the entities that can tell whether the hardware answers.

Primary entities (no category) decide. A device without any falls back to
its other entities, but settings and update checkers never count: Home
Assistant's SkyConnect has only a firmware update entity and a settings
switch, and the update entity goes unavailable whenever its firmware check
fails, while the Zigbee radio carries on working.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices, summarise
from custom_components.pulse_check.core.availability import (
    UNAVAILABLE_PART_AFTER,
    detect_last_heard,
    detect_offline,
)
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
        domain = "binary_sensor" if key.startswith("binary_sensor_") else key.split("_", 1)[0]
        entity_id = f"{domain}.{key[len(domain) + 1 :]}"
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


def test_unavailable_and_unknown_are_not_heard_from() -> None:
    """At a restart Home Assistant stamps them "now"; the device said nothing."""
    states = _states(sensor_temp="21", sensor_battery="80")
    restarted: EntityState = {
        **states["sensor.battery"],
        "state": "unavailable",
        "last_reported": NOW.isoformat(),
    }
    assert detect_last_heard([states["sensor.temp"], restarted]) == datetime.fromisoformat(EARLIER)
    unknown: EntityState = {**restarted, "state": "unknown"}
    assert detect_last_heard([restarted, unknown]) is None


def test_a_device_that_says_it_is_connected_is_not_offline() -> None:
    """Hydrawise: the daily watering time comes from a slower request than the rest."""
    entities = [
        _entity("binary_sensor.controller_connectivity", "diagnostic"),
        _entity("sensor.controller_daily_active_watering_time"),
    ]
    states = _states(
        binary_sensor_controller_connectivity="on",
        sensor_controller_daily_active_watering_time="unavailable",
    )
    states["binary_sensor.controller_connectivity"]["attributes"] = {"device_class": "connectivity"}
    assert not detect_offline(entities, states)
    states["binary_sensor.controller_connectivity"]["state"] = "off"
    assert detect_offline(entities, states)


def _controller(entities: list[EntityEntry], states: dict[str, EntityState]) -> Snapshot:
    """One device, "Controller", with the given entities."""
    snapshot = _unifi_policy(*entities, states=states)
    snapshot["devices"]["dev"]["name"] = "Controller"
    return snapshot


def _hydrawise() -> tuple[list[EntityEntry], dict[str, EntityState]]:
    """A connected controller whose daily watering time is unavailable."""
    hidden = _entity("sensor.controller_hidden")
    hidden["hidden"] = True
    entities = [
        _entity("binary_sensor.controller_connectivity", "diagnostic"),
        _entity("sensor.controller_daily_active_watering_time"),
        _entity("switch.controller_zone_1"),
        _entity("sensor.controller_signal", "diagnostic"),
        hidden,
        _not_provided("sensor.controller_old"),
    ]
    states = _states(
        binary_sensor_controller_connectivity="on",
        sensor_controller_daily_active_watering_time="unavailable",
        switch_controller_zone_1="off",
        sensor_controller_signal="unavailable",
        sensor_controller_hidden="unavailable",
        sensor_controller_old="unavailable",
    )
    states["binary_sensor.controller_connectivity"]["attributes"] = {"device_class": "connectivity"}
    states["sensor.controller_daily_active_watering_time"]["attributes"] = {
        "friendly_name": "Controller Daily active watering time"
    }
    return entities, states


def test_unavailable_parts_of_a_working_device_are_listed_not_alerted() -> None:
    """Only main entities count; diagnostic, hidden and no-longer-provided ones do not."""
    entities, states = _hydrawise()
    [device] = analyse_devices(_controller(entities, states), CoreConfig(), NOW)
    assert (device.is_offline, device.severity) == (False, "ok")
    assert device.to_dict()["unavailableParts"] == [
        {
            "entityId": "sensor.controller_daily_active_watering_time",
            "name": "Daily active watering time",
        }
    ]
    assert summarise([device], CoreConfig()).to_dict()["attention"] == 0


def test_a_part_unavailable_only_moments_ago_is_not_listed_yet() -> None:
    """A restart or a quick reconnect clears itself."""
    entities, states = _hydrawise()
    moments_ago = (NOW - UNAVAILABLE_PART_AFTER + timedelta(minutes=1)).isoformat()
    states["sensor.controller_daily_active_watering_time"]["last_changed"] = moments_ago
    [device] = analyse_devices(_controller(entities, states), CoreConfig(), NOW)
    assert device.unavailable_parts == []
    assert "unavailableParts" not in device.to_dict()


def test_an_offline_device_has_no_unavailable_parts() -> None:
    entities, states = _hydrawise()
    states["binary_sensor.controller_connectivity"]["state"] = "off"
    states["switch.controller_zone_1"]["state"] = "unavailable"
    [device] = analyse_devices(_controller(entities, states), CoreConfig(), NOW)
    assert device.is_offline
    assert device.unavailable_parts == []


def test_an_unknown_part_is_not_listed() -> None:
    entities, states = _hydrawise()
    states["sensor.controller_daily_active_watering_time"]["state"] = "unknown"
    [device] = analyse_devices(_controller(entities, states), CoreConfig(), NOW)
    assert device.unavailable_parts == []


def _printer(**states: str) -> tuple[list[EntityEntry], dict[str, EntityState]]:
    """A 3D printer whose webcam is served straight from a URL (Moonraker's).

    Home Assistant rewrites every camera's state each 5 minutes to rotate
    its access token, so the camera always looks just reported.
    """
    entities = [
        _entity("sensor.printer_extruder"),
        _entity("sensor.printer_queue"),
        _entity("camera.printer_webcam"),
        _entity("image.printer_thumbnail"),
    ]
    out = _states(**states)
    for entity_id in ("camera.printer_webcam", "image.printer_thumbnail"):
        if entity_id in out:
            out[entity_id]["last_updated"] = NOW.isoformat()
            out[entity_id]["last_reported"] = NOW.isoformat()
    return entities, out


def test_a_camera_left_idle_does_not_keep_a_switched_off_printer_online() -> None:
    entities, states = _printer(
        sensor_printer_extruder="unavailable",
        sensor_printer_queue="unavailable",
        camera_printer_webcam="idle",
        image_printer_thumbnail="2026-10-23T08:00:00+00:00",
    )
    heard_at = datetime.fromisoformat(EARLIER)
    [device] = analyse_devices(
        _controller(entities, states), CoreConfig(), NOW, heard={"dev": heard_at}
    )
    assert (device.is_offline, device.last_heard) == (True, heard_at)


def test_a_camera_rotating_its_token_is_not_heard_from() -> None:
    _, states = _printer(
        sensor_printer_extruder="210",
        camera_printer_webcam="idle",
        image_printer_thumbnail="2026-10-23T08:00:00+00:00",
    )
    assert detect_last_heard(list(states.values())) == datetime.fromisoformat(EARLIER)


def test_a_device_that_is_only_a_camera_is_judged_by_it() -> None:
    """Nothing else can say whether it answers; its timestamps still say nothing."""
    camera = [_entity("camera.porch")]
    assert detect_offline(camera, _states(camera_porch="unavailable"))
    assert not detect_offline(camera, _states(camera_porch="idle"))
    assert detect_last_heard(list(_states(camera_porch="idle").values())) is None
