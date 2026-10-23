"""Availability and "last heard from".

- A device is OFFLINE when every one of its primary entities is
  `unavailable`. Primary means no `entity_category`; diagnostic and config
  entities (signal strength, firmware, identify buttons) are ignored
  because integrations often leave those available even when the hardware
  is gone, or vice versa. A device with no primary entities is judged by
  its diagnostic ones; settings and update checkers never decide it, so a
  Zigbee stick whose firmware check is unavailable is not offline.
- A device's LAST HEARD timestamp is the newest `last_reported` across its
  live entities (`last_updated` when an entity has no `last_reported`).
- A device is QUIET when that timestamp is older than a threshold.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .models import as_utc

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .models import EntityEntry, EntityState

UNAVAILABLE = "unavailable"


def is_primary(entity: EntityEntry) -> bool:
    """Primary entities have no entity category."""
    return entity.get("entity_category") is None


def detect_offline(entities: Sequence[EntityEntry], states: Mapping[str, EntityState]) -> bool:
    """Decide whether a device is offline from its registry entries and states.

    Prefers primary entities. A device with none is judged by its other
    live entities, such as diagnostic sensors, but never by static ones
    (settings, buttons, update checkers): those say nothing about whether
    the hardware answers. A firmware update entity goes unavailable when
    its check fails, as Home Assistant's SkyConnect does while the radio
    works normally. A device with nothing left to judge by is not offline.
    """
    primary = [e for e in entities if is_primary(e)]
    candidates = primary or [e for e in entities if not is_static_entity(e["entity_id"], e)]
    with_state = [states[e["entity_id"]] for e in candidates if e["entity_id"] in states]
    if not with_state:
        return False
    return all(s["state"] == UNAVAILABLE for s in with_state)


def parse_timestamp(value: object) -> datetime | None:
    """Parse a timestamp defensively. Returns None for garbage.

    Accepts a datetime (from Home Assistant) or an ISO 8601 string (from
    JSON). The result is always timezone-aware, in UTC.
    """
    if isinstance(value, datetime):
        return as_utc(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


# Entity domains whose timestamps say nothing about whether the device is
# alive: they only change when a person changes a setting.
STATIC_DOMAINS = frozenset({"number", "select", "button", "update", "text", "scene", "script"})


def is_static_entity(entity_id: str, entry: EntityEntry | None) -> bool:
    """True for entities that cannot tell us the device was heard from."""
    if entry is not None and entry.get("entity_category") == "config":
        return True
    return entity_id.split(".", 1)[0] in STATIC_DOMAINS


def reported_at(state: EntityState) -> datetime | None:
    """When the entity last reported: `last_reported`, else `last_updated`."""
    return parse_timestamp(state.get("last_reported") or state["last_updated"])


def detect_last_heard(
    states: Sequence[EntityState], registry: Mapping[str, EntityEntry] | None = None
) -> datetime | None:
    """The newest report among the given states, or None if none parse.

    Static entities (settings, buttons, update checkers) are ignored so that
    "I changed a setting an hour ago" does not count as "the sensor
    reported an hour ago". If a device has nothing but static entities,
    they are used as a last resort.
    """
    registry = registry or {}
    live = [s for s in states if not is_static_entity(s["entity_id"], registry.get(s["entity_id"]))]
    candidates = live or list(states)
    latest: datetime | None = None
    for state in candidates:
        moment = reported_at(state)
        if moment is not None and (latest is None or moment > latest):
            latest = moment
    return latest


def is_quiet(last_heard: datetime | None, now: datetime, threshold_hours: float) -> bool:
    """True when `last_heard` is more than `threshold_hours` before `now`."""
    if last_heard is None:
        return False  # unknown is not the same as quiet
    return as_utc(now) - as_utc(last_heard) > timedelta(hours=threshold_hours)
