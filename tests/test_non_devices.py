"""Services and entities with no device: worded as unavailable, sent to the card when it matters."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.pulse_check.core import CoreConfig
from custom_components.pulse_check.core.models import BatteryReading, DeviceHealth, Source
from custom_components.pulse_check.messages import load_messages
from custom_components.pulse_check.notify import device_issues, wording
from custom_components.pulse_check.websocket import _worth_showing

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _health(source: Source, *, offline: bool = False, name: str = "AdGuard Home") -> DeviceHealth:
    return DeviceHealth(
        device_id="dev_adguard",
        name=name,
        integration="adguard",
        is_offline=offline,
        is_quiet=False,
        quiet_threshold_hours=24,
        severity="critical" if offline else "ok",
        source=source,
    )


def test_a_service_is_unavailable_not_offline() -> None:
    messages = load_messages()
    service = _health("service", offline=True)
    issues = device_issues(service, CoreConfig(), NOW, messages.catalog("en"))
    # The issue keeps its key, so events and automations see one name.
    assert list(issues) == ["offline"]
    assert issues["offline"].message == "AdGuard Home: unavailable"
    german = device_issues(service, CoreConfig(), NOW, messages.catalog("de"))
    assert german["offline"].message == "AdGuard Home: nicht verfügbar"

    hardware = _health("device", offline=True, name="Hallway plug")
    issues = device_issues(hardware, CoreConfig(), NOW, messages.catalog("en"))
    assert issues["offline"].message == "Hallway plug: offline"


def test_the_resolved_wording_follows() -> None:
    messages = load_messages()
    entity = _health("entity", name="Front door")
    key = wording("offline", entity)
    assert key == "unavailable"
    assert messages.catalog("en")(f"resolved_{key}", name="Front door") == (
        "Front door: available again"
    )
    assert wording("offline", _health("device")) == "offline"
    assert wording("quiet", entity) == "quiet"


def test_the_card_gets_them_only_when_they_matter() -> None:
    assert _worth_showing(_health("device"))
    assert not _worth_showing(_health("service"))
    assert not _worth_showing(_health("entity"))
    assert _worth_showing(_health("service", offline=True))

    snoozed = _health("entity")
    snoozed.snoozed_until = NOW
    assert _worth_showing(snoozed)

    battery = _health("entity")
    battery.battery = BatteryReading(is_low=False, source="sensor", entity_id="sensor.x", level=80)
    assert _worth_showing(battery)
