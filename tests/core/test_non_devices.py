"""Services and entities with no device: watched for being unavailable.

A service device (Sun, AdGuard Home, Backup) has no hardware and an entity
with no device (a template sensor, an automation) has nothing behind it,
but either can stop working. They count as offline, shown as unavailable,
when everything that decides is `unavailable`; they are never quiet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
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


def _device(device_id: str, name: str, entry_type: str | None = "service") -> dict[str, Any]:
    return {
        "id": device_id,
        "name": name,
        "name_by_user": None,
        "manufacturer": None,
        "model": None,
        "area_id": None,
        "entry_type": entry_type,
        "disabled_by": None,
    }


def _entity(entity_id: str, platform: str, device_id: str | None = None, **extra: Any) -> Any:
    entry: dict[str, Any] = {"entity_id": entity_id, "platform": platform, **extra}
    if device_id is not None:
        entry["device_id"] = device_id
    return entry


def _snapshot() -> Snapshot:
    """AdGuard down, Sun up, a broken template sensor, a working automation."""
    states = [
        _state("sensor.adguard_dns_queries", "unavailable"),
        _state("switch.adguard_protection", "unavailable"),
        _state("sensor.sun_next_setting", "2026-11-08T08:31:00+00:00"),
        _state("sensor.front_door", "unavailable", friendly_name="Front door"),
        _state("automation.lights_at_sunset", "on", friendly_name="Lights at sunset"),
        _state("sensor.pulse_check_offline", "1"),
        _state("button.restart_everything", "unavailable"),
    ]
    entities = [
        _entity("sensor.adguard_dns_queries", "adguard", "dev_adguard"),
        _entity("switch.adguard_protection", "adguard", "dev_adguard"),
        _entity("sensor.sun_next_setting", "sun", "dev_sun"),
        _entity("sensor.front_door", "template"),
        _entity("automation.lights_at_sunset", "automation"),
        _entity("sensor.pulse_check_offline", "pulse_check", "dev_pulse_check"),
        _entity("button.restart_everything", "template", entity_category="config"),
    ]
    devices = [
        _device("dev_adguard", "AdGuard Home"),
        _device("dev_sun", "Sun"),
        _device("dev_pulse_check", "Pulse Check"),
    ]
    return {
        "states": {s["entity_id"]: s for s in states},  # type: ignore[misc]
        "entities": {e["entity_id"]: e for e in entities},
        "devices": {d["id"]: d for d in devices},  # type: ignore[misc]
        "areas": {},
    }


def _by_id(config: CoreConfig) -> dict[str, Any]:
    return {d.device_id: d for d in analyse_devices(_snapshot(), config, NOW)}


def test_a_service_and_a_lone_entity_can_be_unavailable() -> None:
    devices = _by_id(CoreConfig())
    adguard = devices["dev_adguard"]
    assert adguard.source == "service"
    assert adguard.is_offline
    assert adguard.severity == "critical"
    assert adguard.to_dict()["source"] == "service"

    door = devices["entity:sensor.front_door"]
    assert door.source == "entity"
    assert door.name == "Front door"
    assert door.is_offline

    assert not devices["dev_sun"].is_offline
    assert not devices["entity:automation.lights_at_sunset"].is_offline


def test_they_are_never_quiet() -> None:
    """Sun and a working automation were last heard weeks ago, which means nothing."""
    devices = _by_id(CoreConfig(quiet_scope="all"))
    assert not devices["dev_sun"].is_quiet
    assert not devices["entity:automation.lights_at_sunset"].is_quiet


def test_pulse_check_and_lone_settings_are_left_out() -> None:
    devices = _by_id(CoreConfig())
    assert "dev_pulse_check" not in devices
    # A lone settings entity never decides, so there is nothing to watch.
    assert "entity:button.restart_everything" not in devices


def test_hardware_keeps_no_source_in_the_payload() -> None:
    snapshot = _snapshot()
    snapshot["devices"]["dev_sun"]["entry_type"] = None
    [sun] = [d for d in analyse_devices(snapshot, CoreConfig(), NOW) if d.device_id == "dev_sun"]
    assert sun.source == "device"
    assert "source" not in sun.to_dict()


def test_the_option_turns_it_off() -> None:
    devices = _by_id(CoreConfig(watch_non_devices=False))
    assert devices == {}
    assert CoreConfig.from_dict({"watch_non_devices": False}).watch_non_devices is False
    assert CoreConfig.from_dict({}).watch_non_devices is True


def test_they_can_be_excluded() -> None:
    config = CoreConfig(exclude_integrations=("adguard",), exclude_entities=("sensor.front_door",))
    devices = _by_id(config)
    assert "dev_adguard" not in devices
    assert "entity:sensor.front_door" not in devices
