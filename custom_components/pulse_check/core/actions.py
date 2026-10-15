"""The action list: what to actually do about each low battery.

  replace   "Replace 2 × AA in Kitchen Mini Switch"
  charge    "Charge Office 1 Large"  (rechargeable: true in the device settings)

plus a shopping summary: how many of each battery type to buy, totalled
across the devices that need replacing.

A device is on the list when its battery is at or below the warning
threshold or its binary sensor says "low", unless it is charging or
snoozed. Battery type, count and rechargeable come from the user's device
settings; Home Assistant has no reliable way to know them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .settings import settings_for_device
from .thresholds import battery_severity

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import CoreConfig, DeviceHealth, Severity

UNKNOWN_BATTERY_TYPE = "Unknown type"

# Worst first within each list.
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "ok": 2}

type ActionKind = Literal["replace", "charge"]


@dataclass(frozen=True, slots=True)
class ActionItem:
    """One thing to do: replace or charge a device's battery."""

    kind: ActionKind
    device: DeviceHealth
    severity: Severity
    # Battery type, or UNKNOWN_BATTERY_TYPE when not configured.
    battery_type: str
    # Cells to replace (1 when not configured). Meaningless for "charge".
    count: int
    # "Replace 2 × AA in Kitchen Mini Switch"
    label: str

    def to_dict(self) -> dict[str, Any]:
        """A compact JSON shape: the device is referred to by id and name."""
        return {
            "kind": self.kind,
            "deviceId": self.device.device_id,
            "name": self.device.name,
            "severity": self.severity,
            "batteryType": self.battery_type,
            "count": self.count,
            "label": self.label,
        }


@dataclass(slots=True)
class ShoppingLine:
    """How many cells of one type to buy, and for how many devices."""

    battery_type: str
    count: int = 0
    devices: int = 0

    def to_dict(self) -> dict[str, Any]:
        """JSON shape."""
        return {"batteryType": self.battery_type, "count": self.count, "devices": self.devices}


@dataclass(frozen=True, slots=True)
class ActionList:
    """Replace and charge lists plus the to-buy summary."""

    replace: list[ActionItem] = field(default_factory=list)
    charge: list[ActionItem] = field(default_factory=list)
    # Totals for the "to buy" summary, biggest first, unknown last.
    shopping: list[ShoppingLine] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON shape."""
        return {
            "replace": [item.to_dict() for item in self.replace],
            "charge": [item.to_dict() for item in self.charge],
            "shopping": [line.to_dict() for line in self.shopping],
        }


def needs_attention(device: DeviceHealth, config: CoreConfig) -> bool:
    """True when the device's battery is low enough to act on and not muted."""
    if device.battery is None or device.snoozed_until is not None:
        return False
    return battery_severity(device.battery, config) != "ok"


def _describe(kind: ActionKind, device: DeviceHealth, battery_type: str, count: int) -> str:
    if kind == "charge":
        return f"Charge {device.name}"
    if battery_type == UNKNOWN_BATTERY_TYPE:
        return f"Replace the battery in {device.name}"
    what = f"{count} × {battery_type}" if count > 1 else battery_type
    return f"Replace {what} in {device.name}"


def _order(item: ActionItem) -> tuple[int, str, str]:
    """Worst first, then by name for stability."""
    return (_SEVERITY_ORDER[item.severity], item.device.name.casefold(), item.device.name)


def action_list(devices: Iterable[DeviceHealth], config: CoreConfig) -> ActionList:
    """Build the replace and charge lists and the shopping totals."""
    replace: list[ActionItem] = []
    charge: list[ActionItem] = []

    for device in devices:
        if not needs_attention(device, config) or device.battery is None:
            continue
        settings = settings_for_device(config, device.device_id)
        rechargeable = settings is not None and settings.rechargeable is True
        kind: ActionKind = "charge" if rechargeable else "replace"
        battery_type = (settings.battery_type if settings else None) or UNKNOWN_BATTERY_TYPE
        count = (settings.battery_count if settings else None) or 1
        item = ActionItem(
            kind=kind,
            device=device,
            severity=battery_severity(device.battery, config),
            battery_type=battery_type,
            count=count,
            label=_describe(kind, device, battery_type, count),
        )
        (charge if kind == "charge" else replace).append(item)

    replace.sort(key=_order)
    charge.sort(key=_order)

    totals: dict[str, ShoppingLine] = {}
    for item in replace:
        line = totals.setdefault(item.battery_type, ShoppingLine(battery_type=item.battery_type))
        line.count += item.count
        line.devices += 1
    shopping = sorted(
        totals.values(),
        key=lambda line: (
            line.battery_type == UNKNOWN_BATTERY_TYPE,
            -line.count,
            line.battery_type.casefold(),
        ),
    )

    return ActionList(replace=replace, charge=charge, shopping=shopping)
