"""Values written while Home Assistant starts are not the device reporting.

Integrations write each device's cached value at a start (ZHA's and Z-Wave
JS's caches, Zigbee2MQTT republishing, the companion app restoring), and
Home Assistant stamps it "reported just now" whether or not the device is
there. A device remembered from before keeps its time until it reports.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.pulse_check.core import CoreConfig, Snapshot, analyse_devices
from custom_components.pulse_check.core.models import EntityState

STARTED = datetime(2026, 11, 14, 8, 0, tzinfo=UTC)
# The start plus its grace period.
READY = STARTED + timedelta(minutes=5)
# Remembered from before the restart: 23 hours before it.
REMEMBERED = STARTED - timedelta(hours=23)


def _sensor(reported: datetime) -> Snapshot:
    """A battery sensor whose entities last reported at `reported`."""
    iso = reported.isoformat()
    states: list[EntityState] = [
        {
            "entity_id": f"sensor.door_{name}",
            "state": value,
            "attributes": attributes,
            "last_changed": iso,
            "last_updated": iso,
            "last_reported": iso,
        }
        for name, value, attributes in (
            ("battery", "80", {"device_class": "battery"}),
            ("contact", "off", {}),
        )
    ]
    return {
        "states": {s["entity_id"]: s for s in states},
        "entities": {
            s["entity_id"]: {"entity_id": s["entity_id"], "platform": "zha", "device_id": "dev"}
            for s in states
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


def _last_heard(reported: datetime, now: datetime, *, remembered: bool = True) -> datetime | None:
    [device] = analyse_devices(
        _sensor(reported),
        CoreConfig(),
        now,
        heard={"dev": REMEMBERED} if remembered else None,
        replayed_until=READY,
    )
    return device.last_heard


def test_a_value_written_at_the_start_keeps_the_remembered_time() -> None:
    """A dead sensor does not read "last heard just now" after a restart."""
    assert _last_heard(STARTED + timedelta(seconds=30), STARTED + timedelta(hours=2)) == REMEMBERED


def test_a_device_with_nothing_remembered_takes_the_value() -> None:
    """A device new to Pulse Check has nothing better to go by."""
    reported = STARTED + timedelta(seconds=30)
    assert _last_heard(reported, STARTED + timedelta(minutes=1), remembered=False) == reported


def test_a_report_after_the_grace_period_counts() -> None:
    reported = READY + timedelta(seconds=1)
    assert _last_heard(reported, READY + timedelta(minutes=1)) == reported


def test_the_remembered_time_goes_quiet_as_usual() -> None:
    """Silent since 23 hours before the restart, quiet an hour after it."""
    [device] = analyse_devices(
        _sensor(STARTED + timedelta(seconds=30)),
        CoreConfig(),
        STARTED + timedelta(hours=1, minutes=1),
        heard={"dev": REMEMBERED},
        replayed_until=READY,
    )
    assert device.is_quiet
