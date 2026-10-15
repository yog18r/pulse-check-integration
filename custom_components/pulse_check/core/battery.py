"""Battery detection.

Three rules, applied to every entity of a device, in order of preference:

1. `sensor.*` with `device_class: battery` and a numeric state -> level in %
2. `binary_sensor.*` with `device_class: battery` -> "on" means LOW
3. Any entity with a numeric `battery_level` attribute -> level in %
   (older or custom integrations that never got a dedicated sensor)

Everything here is a pure function: same input, same output.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .models import BatteryReading, BatterySource, js_round

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .models import EntityEntry, EntityState


def domain_of(entity_id: str) -> str:
    """The part before the dot: "sensor" for "sensor.kitchen_battery"."""
    return entity_id.split(".", 1)[0]


def parse_numeric(value: object) -> float | None:
    """A finite number from a state or attribute, or None.

    HA stores every state as a string: "87" is a battery level, and so are
    "87.0" and " 87 ". "unavailable", "unknown" and "" are not.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        number = float(stripped)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def clamp_percent(value: float) -> int:
    """Round to a whole percentage between 0 and 100."""
    return min(100, max(0, js_round(value)))


def read_battery(state: EntityState) -> BatteryReading | None:
    """Read a battery value from one entity, or None if it says nothing about battery."""
    entity_id = state["entity_id"]
    domain = domain_of(entity_id)
    attributes = state["attributes"]
    device_class = attributes.get("device_class")

    # Rule 1: numeric battery sensor.
    if domain == "sensor" and device_class == "battery":
        level = parse_numeric(state["state"])
        if level is not None:
            return BatteryReading(
                is_low=False, source="sensor", entity_id=entity_id, level=clamp_percent(level)
            )
        # Unavailable or unknown: fall through, in case the integration also
        # puts the level in a battery_level attribute (rule 3).

    # Rule 2: binary low-battery sensor. "on" means the battery IS low.
    if domain == "binary_sensor" and device_class == "battery":
        if state["state"] not in ("on", "off"):
            return None
        return BatteryReading(is_low=state["state"] == "on", source="binary", entity_id=entity_id)

    # Rule 3: battery_level attribute on anything else.
    attribute_level = parse_numeric(attributes.get("battery_level"))
    if attribute_level is not None:
        return BatteryReading(
            is_low=False,
            source="attribute",
            entity_id=entity_id,
            level=clamp_percent(attribute_level),
        )

    return None


# Lower number = preferred source when a device offers several.
_SOURCE_RANK: dict[BatterySource, int] = {"sensor": 0, "attribute": 1, "binary": 2}


def combine_battery_readings(readings: Sequence[BatteryReading]) -> BatteryReading | None:
    """Collapse a device's several battery signals into one.

    - prefer a numeric level from a sensor, then an attribute, then binary
    - among numeric readings the lowest level wins (the weakest cell matters)
    - if ANY binary sensor says low, the combined reading is flagged low
    """
    if not readings:
        return None
    any_binary_low = any(r.source == "binary" and r.is_low for r in readings)
    best = min(
        readings,
        key=lambda r: (_SOURCE_RANK[r.source], 101 if r.level is None else r.level),
    )
    return BatteryReading(
        is_low=best.is_low or any_binary_low,
        source=best.source,
        entity_id=best.entity_id,
        level=best.level,
        is_charging=best.is_charging,
    )


def detect_battery(
    states: Sequence[EntityState], registry: Mapping[str, EntityEntry] | None = None
) -> BatteryReading | None:
    """Scan a device's entity states and return its single battery reading.

    Entities marked `entity_category: config` are skipped: those are
    settings (an inverter's "minimum state of charge"), and some
    integrations label them `device_class: battery` because the unit is %.
    """
    registry = registry or {}
    readings = []
    for state in states:
        entry = registry.get(state["entity_id"])
        if entry is not None and entry.get("entity_category") == "config":
            continue
        reading = read_battery(state)
        if reading is not None:
            readings.append(reading)
    combined = combine_battery_readings(readings)
    if combined is not None and detect_charging(states):
        combined.is_charging = True
    return combined


# States that integrations use to say "plugged in".
_CHARGING_STATES = frozenset({"charging", "full"})
_CHARGING_ATTRIBUTES = ("is_charging", "charging", "battery_charging")


def detect_charging(states: Sequence[EntityState]) -> bool:
    """Is any entity on this device saying it is charging?

    Integrations spell this many ways; these cover the common ones:

    - binary_sensor with device_class battery_charging (the HA standard)
    - a "battery state" sensor reading charging/full (companion app)
    - a vacuum that is docked
    - boolean attributes: is_charging, charging, battery_charging
    - a battery_state attribute reading charging
    """
    for state in states:
        entity_id = state["entity_id"]
        domain = domain_of(entity_id)
        attributes = state["attributes"]
        value = state["state"]

        if domain == "binary_sensor" and attributes.get("device_class") == "battery_charging":
            if value == "on":
                return True
            continue
        if domain == "sensor" and "battery" in entity_id and value in _CHARGING_STATES:
            return True
        if domain == "vacuum" and value == "docked":
            return True
        if any(attributes.get(key) is True for key in _CHARGING_ATTRIBUTES):
            return True
        battery_state = attributes.get("battery_state")
        if isinstance(battery_state, str) and battery_state in _CHARGING_STATES:
            return True
    return False
