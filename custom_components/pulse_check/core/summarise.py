"""Summary counts: the one-line verdict and its breakdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .thresholds import battery_severity

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import CoreConfig, DeviceHealth


@dataclass(slots=True)
class Summary:
    """How many devices are in each kind of trouble."""

    # Devices that are warning or critical.
    attention: int = 0
    critical: int = 0
    warning: int = 0
    # Battery-powered devices seen.
    battery_devices: int = 0
    # Battery-powered devices at or below the warning threshold (or binary low).
    low_batteries: int = 0
    # Battery-powered devices at or below the critical threshold (or binary low).
    critical_batteries: int = 0
    offline: int = 0
    quiet: int = 0
    # Devices whose integration no longer provides them (stale configuration).
    not_provided: int = 0
    # Devices the user has muted; they count in nothing else.
    snoozed: int = 0

    def to_dict(self) -> dict[str, Any]:
        """JSON shape with the card's camelCase keys."""
        return {
            "attention": self.attention,
            "critical": self.critical,
            "warning": self.warning,
            "batteryDevices": self.battery_devices,
            "lowBatteries": self.low_batteries,
            "criticalBatteries": self.critical_batteries,
            "offline": self.offline,
            "quiet": self.quiet,
            "notProvided": self.not_provided,
            "snoozed": self.snoozed,
        }


def summarise(devices: Iterable[DeviceHealth], config: CoreConfig) -> Summary:
    """Count devices by the kind of trouble they are in."""
    summary = Summary()
    for device in devices:
        if device.snoozed_until is not None:
            summary.snoozed += 1
            continue
        if device.severity == "critical":
            summary.critical += 1
        if device.severity == "warning":
            summary.warning += 1
        if device.severity != "ok":
            summary.attention += 1
        if device.battery is not None:
            summary.battery_devices += 1
            battery = battery_severity(device.battery, config)
            if battery != "ok":
                summary.low_batteries += 1
            if battery == "critical":
                summary.critical_batteries += 1
        if device.is_offline:
            summary.offline += 1
        if device.is_quiet:
            summary.quiet += 1
        if device.is_not_provided:
            summary.not_provided += 1
    return summary
