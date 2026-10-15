"""Grouping: turn HA's flat entity list into one group per physical device.

Entities point at their device (`entity.device_id`), so we walk every
entity once and bucket it by device. Entities with no device at all get a
synthetic group of their own, so a lone template battery sensor is still
visible.

Some entities never reach the entity registry: without a `unique_id`
(YAML template sensors, some MQTT entities) they exist only as a state.
They have no device either, so they become synthetic groups too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .models import DeviceEntry, EntityEntry, EntityState, Snapshot

# Prefix used for the synthetic id of a device-less entity.
ORPHAN_PREFIX = "entity:"


@dataclass(slots=True)
class DeviceGroup:
    """All the raw material about one device, before any analysis."""

    # Registry id, or `entity:<entity_id>` for an entity with no device.
    device_id: str
    # None for synthetic single-entity groups.
    device: DeviceEntry | None
    entities: list[EntityEntry] = field(default_factory=list)
    # States for the entities above, in the same order, skipping any without a state.
    states: list[EntityState] = field(default_factory=list)


def is_ignorable_device(device: DeviceEntry) -> bool:
    """Devices never shown: virtual "service" devices and disabled ones."""
    return device["entry_type"] == "service" or device["disabled_by"] is not None


def collect_device_groups(snapshot: Snapshot) -> list[DeviceGroup]:
    """One group per device, in the order devices are first seen in the registry.

    Then one group per state that has no registry entry at all.
    """
    groups: dict[str, DeviceGroup] = {}
    for entity in snapshot["entities"].values():
        device_id = entity.get("device_id")
        device: DeviceEntry | None = None
        if device_id is not None:
            registry_device = snapshot["devices"].get(device_id)
            if registry_device is None:
                # Stale registry or partial fixture: treat as an orphan.
                key = ORPHAN_PREFIX + entity["entity_id"]
            else:
                if is_ignorable_device(registry_device):
                    continue
                key = registry_device["id"]
                device = registry_device
        else:
            key = ORPHAN_PREFIX + entity["entity_id"]

        group = groups.get(key)
        if group is None:
            group = DeviceGroup(device_id=key, device=device)
            groups[key] = group
        group.entities.append(entity)
        state = snapshot["states"].get(entity["entity_id"])
        if state is not None:
            group.states.append(state)

    # States with no registry entry. A bare entry stands in for the missing
    # one: no platform, no category, no area.
    for entity_id, state in snapshot["states"].items():
        if entity_id in snapshot["entities"]:
            continue
        key = ORPHAN_PREFIX + entity_id
        groups[key] = DeviceGroup(
            device_id=key, device=None, entities=[{"entity_id": entity_id}], states=[state]
        )
    return list(groups.values())


def dominant_integration(entities: Sequence[EntityEntry]) -> str:
    """The most common platform among a device's entities; "unknown" if none."""
    counts: dict[str, int] = {}
    for entity in entities:
        platform = entity.get("platform") or "unknown"
        counts[platform] = counts.get(platform, 0) + 1
    best = "unknown"
    best_count = -1
    for platform, count in counts.items():
        if count > best_count:
            best, best_count = platform, count
    return best


def display_name(group: DeviceGroup) -> str:
    """The user's rename, then the device name, then the entity's friendly name."""
    if group.device is not None:
        return group.device["name_by_user"] or group.device["name"] or group.device_id
    if group.states:
        friendly = group.states[0]["attributes"].get("friendly_name")
        if isinstance(friendly, str) and friendly:
            return friendly
    if group.entities:
        return group.entities[0]["entity_id"]
    return group.device_id


def area_id_of(group: DeviceGroup) -> str | None:
    """The device's area id, else the first entity's own area id."""
    if group.device is not None and group.device["area_id"]:
        return group.device["area_id"]
    for entity in group.entities:
        if entity.get("area_id"):
            return entity["area_id"]
    return None


def area_name(group: DeviceGroup, snapshot: Snapshot) -> str | None:
    """Display name of the group's area, if it has one."""
    area_id = area_id_of(group)
    if area_id is None:
        return None
    area = snapshot["areas"].get(area_id)
    return area["name"] if area is not None else None
