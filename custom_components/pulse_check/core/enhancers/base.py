"""The enhancer contract and shared helpers.

Integrations do not give us a typed "this is the node status sensor" flag,
so enhancers recognise entities by convention: the entity id suffix the
integration generates, the unit, or the device class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..battery import parse_numeric

if TYPE_CHECKING:
    from datetime import datetime

    from ..group import DeviceGroup
    from ..models import EnhancerExtra, EntityState, Snapshot


@dataclass(slots=True)
class EnhancerResult:
    """What an enhancer learned about one device."""

    # Small facts to show on the device, e.g. Node = asleep.
    extras: list[EnhancerExtra] = field(default_factory=list)
    # A better "last heard from" than the generic rule, e.g. Zigbee2MQTT's
    # optional last_seen sensor. Only used if newer.
    last_heard: datetime | None = None
    # The integration knows the device is gone (a dead Z-Wave node).
    offline: bool = False


class Enhancer(ABC):
    """An optional, integration-specific source of extra facts."""

    # Short id, used in logs and tests.
    id: str
    # The integration (platform) this enhancer understands, e.g. "zwave_js".
    platform: str

    @abstractmethod
    def enhance(self, group: DeviceGroup, snapshot: Snapshot) -> EnhancerResult:
        """Inspect a device's entities and states and return extra facts.

        Only called for devices whose dominant integration equals `platform`.
        """


def find_by_suffix(group: DeviceGroup, *suffixes: str) -> EntityState | None:
    """First state in the group whose entity id ends with one of the suffixes."""
    for state in group.states:
        if any(state["entity_id"].endswith(suffix) for suffix in suffixes):
            return state
    return None


def find_by_attribute(group: DeviceGroup, attribute: str, value: object) -> EntityState | None:
    """First state in the group with the given attribute value."""
    for state in group.states:
        if state["attributes"].get(attribute) == value:
            return state
    return None


def numeric_state(state: EntityState | None) -> float | None:
    """Numeric state, or None for unavailable/unknown/garbage."""
    return parse_numeric(state["state"]) if state is not None else None
