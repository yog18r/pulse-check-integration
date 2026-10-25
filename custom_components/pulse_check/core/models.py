"""Core data types.

Two groups of types live here:

1. The input: a plain snapshot of Home Assistant's states and registries.
   These are `TypedDict`s (dictionaries with a declared shape) rather than
   classes so a JSON fixture loads straight into them and the Home
   Assistant layer can build them cheaply from its own objects.
2. The output: one `DeviceHealth` per physical device, as dataclasses with
   a `to_dict()` that produces the exact JSON shape the Pulse Check Card
   uses (camelCase keys, optional keys left out, ISO timestamps).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping

# --------------------------------------------------------------------------
# Input: the snapshot
# --------------------------------------------------------------------------

# A timestamp is either an ISO 8601 string (from JSON) or a datetime (from HA).
type Timestamp = str | datetime


class EntityState(TypedDict):
    """One entity's current state: the subset of HA's `State` we read."""

    entity_id: str
    # Always a string in HA, even for numbers ("87") or timestamps.
    state: str
    attributes: Mapping[str, Any]
    last_changed: NotRequired[Timestamp]
    # When the state or attributes last changed.
    last_updated: Timestamp
    # When the entity last reported, even if nothing changed. The frontend
    # never sees this, but the backend does, so it is the better "last
    # heard" signal. Falls back to last_updated when absent.
    last_reported: NotRequired[Timestamp]


type EntityCategory = Literal["diagnostic", "config"]


class EntityEntry(TypedDict):
    """One entity registry entry."""

    entity_id: str
    device_id: NotRequired[str]
    area_id: NotRequired[str]
    # Integration domain that provides the entity: "zha", "mqtt", "zwave_js".
    platform: NotRequired[str]
    # "diagnostic" or "config" entities are secondary; absent means primary.
    entity_category: NotRequired[EntityCategory]
    hidden: NotRequired[bool]
    name: NotRequired[str]
    # True when the integration no longer provides the entity: its config
    # entry is loaded, yet the state is Home Assistant's restored
    # placeholder. Typically left behind by an integration update.
    not_provided: NotRequired[bool]


class DeviceEntry(TypedDict):
    """One device registry entry."""

    id: str
    name: str | None
    # The user's rename, which wins over `name` when present.
    name_by_user: str | None
    manufacturer: str | None
    model: str | None
    area_id: str | None
    # "service" marks virtual devices (Sun, Forecast...) with no hardware.
    entry_type: Literal["service"] | None
    disabled_by: str | None


class AreaEntry(TypedDict):
    """One area registry entry."""

    area_id: str
    name: str


class Snapshot(TypedDict):
    """Everything the core reads, keyed the way HA keys it."""

    states: Mapping[str, EntityState]
    entities: Mapping[str, EntityEntry]
    devices: Mapping[str, DeviceEntry]
    areas: Mapping[str, AreaEntry]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

type QuietScope = Literal["battery", "all"]


@dataclass(frozen=True, slots=True)
class DeviceSettings:
    """Per-device settings: what the device needs and how patient to be."""

    device_id: str
    quiet_threshold_hours: float | None = None
    # Free text, usually a standard size: "CR2032", "AA".
    battery_type: str | None = None
    # How many cells the device takes. Treated as 1 when unset.
    battery_count: int | None = None
    # Charge it rather than replace it.
    rechargeable: bool | None = None
    # Shown instead of the registry name. Does not rename the device.
    name: str | None = None
    # Area shown for this device and used by the area filters.
    area: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """The card's `DeviceSettings` shape, without unset fields."""
        out: dict[str, Any] = {"device_id": self.device_id}
        for key in (
            "quiet_threshold_hours",
            "battery_type",
            "battery_count",
            "rechargeable",
            "name",
            "area",
        ):
            value = getattr(self, key)
            if value is not None:
                out[key] = plain_number(value) if isinstance(value, float) else value
        return out

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DeviceSettings:
        """Build from a plain mapping, ignoring unknown keys."""
        return cls(
            device_id=str(raw["device_id"]),
            quiet_threshold_hours=_optional_number(raw.get("quiet_threshold_hours")),
            battery_type=_optional_text(raw.get("battery_type")),
            battery_count=_optional_int(raw.get("battery_count")),
            rechargeable=_optional_bool(raw.get("rechargeable")),
            name=_optional_text(raw.get("name")),
            area=_optional_text(raw.get("area")),
        )


@dataclass(frozen=True, slots=True)
class CoreConfig:
    """The settings the rules depend on, with the card's defaults."""

    # Battery % at or below which a device is a warning / critical.
    battery_warning: float = 30
    battery_critical: float = 15
    # Hours without a report before a device is "quiet".
    quiet_threshold_hours: float = 24
    # Per-integration quiet thresholds keyed by platform, e.g. {"zwave_js": 48}.
    integration_thresholds: Mapping[str, float] = field(default_factory=dict)
    device_settings: tuple[DeviceSettings, ...] = ()
    exclude_integrations: tuple[str, ...] = ()
    exclude_devices: tuple[str, ...] = ()
    # Entity ids to ignore entirely.
    exclude_entities: tuple[str, ...] = ()
    # Which devices can be "quiet": only battery-powered ones, or all.
    quiet_scope: QuietScope = "battery"
    # Allow and deny lists. Areas by id or name; integrations by platform.
    include_areas: tuple[str, ...] = ()
    exclude_areas: tuple[str, ...] = ()
    include_integrations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """The rules' inputs, in the card's YAML key names, for the card to reuse."""
        return {
            "battery_warning": plain_number(self.battery_warning),
            "battery_critical": plain_number(self.battery_critical),
            "quiet_threshold_hours": plain_number(self.quiet_threshold_hours),
            "quiet_scope": self.quiet_scope,
            "integration_thresholds": {
                k: plain_number(v) for k, v in self.integration_thresholds.items()
            },
            "device_settings": [item.to_dict() for item in self.device_settings],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CoreConfig:
        """Build from a plain mapping such as the card's YAML config.

        Unknown keys (the card's UI-only options) are ignored, and missing
        keys keep their defaults, so a partial mapping is fine.
        """
        defaults = cls()
        quiet_scope: QuietScope = "all" if raw.get("quiet_scope") == "all" else "battery"
        return cls(
            battery_warning=float(raw.get("battery_warning", defaults.battery_warning)),
            battery_critical=float(raw.get("battery_critical", defaults.battery_critical)),
            quiet_threshold_hours=float(
                raw.get("quiet_threshold_hours", defaults.quiet_threshold_hours)
            ),
            integration_thresholds={
                str(k): float(v) for k, v in raw.get("integration_thresholds", {}).items()
            },
            device_settings=tuple(
                DeviceSettings.from_dict(item) for item in raw.get("device_settings", [])
            ),
            exclude_integrations=_text_tuple(raw.get("exclude_integrations")),
            exclude_devices=_text_tuple(raw.get("exclude_devices")),
            exclude_entities=_text_tuple(raw.get("exclude_entities")),
            quiet_scope=quiet_scope,
            include_areas=_text_tuple(raw.get("include_areas")),
            exclude_areas=_text_tuple(raw.get("exclude_areas")),
            include_integrations=_text_tuple(raw.get("include_integrations")),
        )


# --------------------------------------------------------------------------
# Output: what the core computes
# --------------------------------------------------------------------------

type Severity = Literal["ok", "warning", "critical"]
type BatterySource = Literal["sensor", "binary", "attribute"]


@dataclass(slots=True)
class BatteryReading:
    """A device's single combined battery reading."""

    # True when a binary low-battery sensor reports "on".
    is_low: bool
    source: BatterySource
    # The entity the reading was taken from.
    entity_id: str
    # 0-100 when a numeric level is known. None for binary sensors.
    level: int | None = None
    # True when the device reports it is charging or docked.
    is_charging: bool = False

    def to_dict(self) -> dict[str, Any]:
        """The card's `BatteryReading` shape."""
        out: dict[str, Any] = {
            "isLow": self.is_low,
            "source": self.source,
            "entityId": self.entity_id,
        }
        if self.level is not None:
            out["level"] = self.level
        if self.is_charging:
            out["isCharging"] = True
        return out


@dataclass(frozen=True, slots=True)
class EnhancerExtra:
    """A small fact contributed by an integration-specific enhancer."""

    label: str
    value: str
    # An enhancer can escalate severity, e.g. a "dead" Z-Wave node.
    severity: Severity | None = None

    def to_dict(self) -> dict[str, Any]:
        """The card's `EnhancerExtra` shape."""
        out: dict[str, Any] = {"label": self.label, "value": self.value}
        if self.severity is not None:
            out["severity"] = self.severity
        return out


@dataclass(frozen=True, slots=True)
class EstimateInfo:
    """A days-left estimate with its provenance (see core/cycles.py)."""

    days_left: float
    basis: str
    confidence: str
    # "replace" (days until empty) or "charge" (days until the warning level).
    kind: str
    # True for "more than a year": days_left is a floor, not a prediction.
    open_ended: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON shape."""
        out: dict[str, Any] = {
            "daysLeft": round(self.days_left, 1),
            "basis": self.basis,
            "confidence": self.confidence,
            "kind": self.kind,
        }
        if self.open_ended:
            out["openEnded"] = True
        return out


@dataclass(slots=True)
class DeviceHealth:
    """Everything known about one device's health."""

    # Registry id, or `entity:<entity_id>` for an entity with no device.
    device_id: str
    name: str
    # Integration domain, or "unknown" when the registry has no platform.
    integration: str
    # True when every primary entity is unavailable.
    is_offline: bool
    # True when `last_heard` is older than the device's quiet threshold.
    is_quiet: bool
    # The threshold that applied to this device, after overrides, in hours.
    quiet_threshold_hours: float
    severity: Severity
    # What kind of thing it is: "lock", "motion", "phone"... (see device_type.py).
    device_type: str = "other"
    extras: list[EnhancerExtra] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    area: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    battery: BatteryReading | None = None
    # The newest report across the device's live entities.
    last_heard: datetime | None = None
    # Set while the user has snoozed this device. Facts are still reported,
    # but severity is "ok".
    snoozed_until: datetime | None = None
    # Days until empty (or until a charge is needed), when history allows an
    # estimate, with where the number came from and how much to trust it.
    days_left: float | None = None
    estimate: EstimateInfo | None = None
    # "charged", "replaceable" or "unknown", from the battery's cycles.
    battery_kind: str | None = None
    # When the battery was last replaced or charged, from the integration's history.
    last_replaced: datetime | None = None
    # A short note when the battery behaves unlike its own past, e.g.
    # "draining 3× faster than usual".
    unusual: str | None = None
    # True when the integration no longer provides the entities that would
    # decide offline: stale configuration, not a fault. Never also offline.
    is_not_provided: bool = False

    def to_dict(self) -> dict[str, Any]:
        """The card's `DeviceHealth` shape, JSON-ready."""
        out: dict[str, Any] = {
            "deviceId": self.device_id,
            "name": self.name,
            "integration": self.integration,
            "isOffline": self.is_offline,
            "isQuiet": self.is_quiet,
            "quietThresholdHours": plain_number(self.quiet_threshold_hours),
            "severity": self.severity,
            "deviceType": self.device_type,
            "extras": [extra.to_dict() for extra in self.extras],
            "entityIds": list(self.entity_ids),
        }
        if self.area is not None:
            out["area"] = self.area
        if self.manufacturer is not None:
            out["manufacturer"] = self.manufacturer
        if self.model is not None:
            out["model"] = self.model
        if self.battery is not None:
            out["battery"] = self.battery.to_dict()
        if self.last_heard is not None:
            out["lastHeard"] = to_iso(self.last_heard)
        if self.snoozed_until is not None:
            out["snoozedUntil"] = to_iso(self.snoozed_until)
        if self.days_left is not None:
            out["daysLeft"] = round(self.days_left, 1)
        if self.estimate is not None:
            out["estimate"] = self.estimate.to_dict()
        if self.battery_kind is not None:
            out["batteryKind"] = self.battery_kind
        if self.last_replaced is not None:
            out["lastReplaced"] = to_iso(self.last_replaced)
        if self.unusual is not None:
            out["unusual"] = self.unusual
        if self.is_not_provided:
            out["isNotProvided"] = True
        return out


# --------------------------------------------------------------------------
# Small helpers shared across the core
# --------------------------------------------------------------------------


def js_round(value: float) -> int:
    """Round half up, like JavaScript's `Math.round` (Python rounds half to even)."""
    return math.floor(value + 0.5)


def to_iso(moment: datetime) -> str:
    """Format like JavaScript's `Date.toISOString()`: UTC, milliseconds, `Z`."""
    utc = as_utc(moment)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


def as_utc(moment: datetime) -> datetime:
    """Make a datetime timezone-aware in UTC. Naive datetimes are taken as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def plain_number(value: float) -> float | int:
    """24.0 becomes 24, so JSON output matches the card's."""
    return int(value) if float(value).is_integer() else value


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)
