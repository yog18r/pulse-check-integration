"""Device type classification, so views can group "all the locks" together.

Home Assistant has no "kind of device" field. The nearest thing is what
a device's primary entities are: a device with a `lock` entity is a lock,
one with a `binary_sensor` of class `motion` is a motion sensor. When a
device has several kinds of entity the more specific one wins, in the
order of `_RULES` below: a lock with a door sensor is still a lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .models import EntityEntry, EntityState

type DeviceType = Literal[
    "lock",
    "cover",
    "vacuum",
    "phone",
    "media",
    "remote",
    "climate",
    "motion",
    "contact",
    "light",
    "switch",
    "other",
]

DEVICE_TYPES: tuple[DeviceType, ...] = (
    "lock",
    "cover",
    "vacuum",
    "phone",
    "media",
    "remote",
    "climate",
    "motion",
    "contact",
    "light",
    "switch",
    "other",
)

_MOTION_CLASSES = frozenset({"motion", "occupancy", "presence", "moving"})
_CONTACT_CLASSES = frozenset({"door", "window", "opening", "garage_door", "vibration"})
_CLIMATE_CLASSES = frozenset({"temperature", "humidity"})

# (type, test) pairs in priority order. Each test looks at one entity's
# domain and device class.
_RULES: tuple[tuple[DeviceType, str, frozenset[str] | None], ...] = (
    ("lock", "lock", None),
    ("cover", "cover", None),
    ("vacuum", "vacuum", None),
    ("media", "media_player", None),
    ("remote", "remote", None),
    ("climate", "climate", None),
    ("motion", "binary_sensor", _MOTION_CLASSES),
    ("contact", "binary_sensor", _CONTACT_CLASSES),
    ("light", "light", None),
    ("switch", "switch", None),
    ("climate", "sensor", _CLIMATE_CLASSES),
)


def classify_device(
    entities: Sequence[EntityEntry],
    states: Sequence[EntityState],
    integration: str,
) -> DeviceType:
    """The most specific type any of the device's primary entities implies."""
    if integration == "mobile_app":
        return "phone"
    by_id = {state["entity_id"]: state for state in states}
    primary = [e for e in entities if e.get("entity_category") is None] or list(entities)
    kinds: list[tuple[str, str | None]] = []
    for entity in primary:
        entity_id = entity["entity_id"]
        domain = entity_id.split(".", 1)[0]
        state = by_id.get(entity_id)
        device_class = state["attributes"].get("device_class") if state else None
        kinds.append((domain, device_class if isinstance(device_class, str) else None))

    if any(domain == "device_tracker" for domain, _ in kinds) and any(
        "battery_level" in (by_id[e["entity_id"]]["attributes"] if e["entity_id"] in by_id else {})
        for e in primary
    ):
        return "phone"

    for device_type, wanted_domain, wanted_classes in _RULES:
        for domain, device_class in kinds:
            if domain != wanted_domain:
                continue
            if wanted_classes is None or (device_class in wanted_classes):
                return device_type
    return "other"
