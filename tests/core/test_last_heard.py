"""Last heard falls back to settings-type entities only when nothing else is left."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.pulse_check.core.availability import detect_last_heard
from custom_components.pulse_check.core.models import EntityState

OLDER = "2026-11-10T09:00:00+00:00"
NEWER = "2026-11-10T11:00:00+00:00"


def _state(entity_id: str, reported: str) -> EntityState:
    """One entity's state, by its full entity id, last reported at `reported`."""
    return {
        "entity_id": entity_id,
        "state": "1",
        "attributes": {},
        "last_updated": reported,
        "last_reported": reported,
    }


def test_a_device_with_only_settings_is_heard_from_through_them() -> None:
    """A last resort: without it such a device would never have a last heard."""
    states = [_state("number.valve_limit", OLDER), _state("button.valve_identify", NEWER)]
    assert detect_last_heard(states) == datetime(2026, 11, 10, 11, 0, tzinfo=UTC)


def test_a_setting_changed_later_does_not_count_beside_a_live_entity() -> None:
    states = [_state("sensor.valve_flow", OLDER), _state("number.valve_limit", NEWER)]
    assert detect_last_heard(states) == datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
