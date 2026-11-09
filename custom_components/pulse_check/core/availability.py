"""Availability and "last heard from".

- A device is OFFLINE when every one of its primary entities is
  `unavailable`, unless a connectivity sensor of its own reads "on".
  Primary means no `entity_category`; diagnostic and config entities
  (signal strength, firmware, identify buttons) are ignored
  because integrations often leave those available even when the hardware
  is gone, or vice versa. A device with no primary entities is judged by
  its diagnostic ones; settings and update checkers never decide it, so a
  Zigbee stick whose firmware check is unavailable is not offline.
- A device is NOT PROVIDED when it would be offline, but every entity
  deciding that is a placeholder Home Assistant keeps for an entity its
  (running) integration no longer provides. That is stale configuration
  to clean up, not hardware that stopped answering.
- A device's LAST HEARD timestamp is the newest `last_reported` across its
  live entities (`last_updated` when an entity has no `last_reported`).
  An `unavailable` or `unknown` state is not a report: Home Assistant
  sets those, with a fresh timestamp, at every restart.
- A device is QUIET when that timestamp is older than a threshold.
- A device that is not offline can still have UNAVAILABLE PARTS: main
  entities that have been `unavailable` for a while. They are listed for
  a look, never alerted on (a Hydrawise controller's daily watering time
  comes from a separate cloud request that can fail on its own).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .models import as_utc

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .models import EntityEntry, EntityState

UNAVAILABLE = "unavailable"
# States Home Assistant writes itself, not the device: they say nothing
# about when the device was heard from.
NOT_HEARD = frozenset({UNAVAILABLE, "unknown"})


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

    A device that says itself it is connected is not offline either: a
    connectivity sensor reading "on" (ESPHome's status, Hydrawise's
    controller) outranks other entities that are unavailable for their own
    reasons, such as Hydrawise's daily watering time, which comes from a
    separate, slower cloud request.
    """
    if _says_connected(entities, states):
        return False
    deciding = _deciding_entities(entities, states)
    return bool(deciding) and all(states[e["entity_id"]]["state"] == UNAVAILABLE for e in deciding)


def _says_connected(entities: Sequence[EntityEntry], states: Mapping[str, EntityState]) -> bool:
    """True when one of the device's connectivity sensors reads "on"."""
    for entity in entities:
        state = states.get(entity["entity_id"])
        if (
            state is not None
            and entity["entity_id"].startswith("binary_sensor.")
            and state["attributes"].get("device_class") == "connectivity"
            and state["state"] == "on"
        ):
            return True
    return False


def detect_not_provided(entities: Sequence[EntityEntry], states: Mapping[str, EntityState]) -> bool:
    """True when the device would be offline only because its integration dropped it.

    Every entity that decides offline is unavailable and marked
    `not_provided`. One real unavailable entity among them makes it a
    genuine offline instead.
    """
    deciding = _deciding_entities(entities, states)
    return (
        bool(deciding)
        and all(states[e["entity_id"]]["state"] == UNAVAILABLE for e in deciding)
        and all(e.get("not_provided", False) for e in deciding)
    )


# How long a main entity must have been unavailable before it is listed:
# a restart or a quick reconnect clears itself.
UNAVAILABLE_PART_AFTER = timedelta(minutes=10)


def unavailable_parts(
    entities: Sequence[EntityEntry], states: Mapping[str, EntityState], now: datetime
) -> list[EntityEntry]:
    """Main entities unavailable for at least `UNAVAILABLE_PART_AFTER`.

    Meant for a device that is not offline. Diagnostic and config entities,
    hidden ones and those the integration no longer provides are skipped.
    """
    parts: list[EntityEntry] = []
    for entity in entities:
        state = states.get(entity["entity_id"])
        if (
            state is None
            or state["state"] != UNAVAILABLE
            or not is_primary(entity)
            or entity.get("hidden", False)
            or entity.get("not_provided", False)
        ):
            continue
        since = parse_timestamp(state.get("last_changed") or state["last_updated"])
        if since is not None and as_utc(now) - since >= UNAVAILABLE_PART_AFTER:
            parts.append(entity)
    return parts


def can_be_offline(entities: Sequence[EntityEntry]) -> bool:
    """False when only settings, buttons and update checkers are left to judge by."""
    return any(is_primary(e) or not is_static_entity(e["entity_id"], e) for e in entities)


def _deciding_entities(
    entities: Sequence[EntityEntry], states: Mapping[str, EntityState]
) -> list[EntityEntry]:
    """The entities, with a state, that decide whether a device is offline."""
    primary = [e for e in entities if is_primary(e)]
    candidates = primary or [e for e in entities if not is_static_entity(e["entity_id"], e)]
    return [e for e in candidates if e["entity_id"] in states]


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
    they are used as a last resort. Unavailable and unknown states are
    never used: after a restart they would all read "just now".
    """
    registry = registry or {}
    live = [s for s in states if not is_static_entity(s["entity_id"], registry.get(s["entity_id"]))]
    candidates = [s for s in (live or list(states)) if s["state"] not in NOT_HEARD]
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
