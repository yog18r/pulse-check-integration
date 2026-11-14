"""Thresholds and severity.

Resolution order for the quiet threshold, most specific wins:
  device override > integration override > global default
Battery warning and critical levels: device override > global default.

Severity rules for a device:
  critical  offline, battery at/below critical %, binary "low battery", or an
            enhancer says so (e.g. a dead Z-Wave node)
  warning   battery at/below warning %, quiet, or not provided
  ok        everything else
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .settings import settings_for_device

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import BatteryReading, CoreConfig, EnhancerExtra, Severity

# Order used for comparing severities. Higher = worse.
SEVERITY_RANK: dict[str, int] = {"ok": 0, "warning": 1, "critical": 2}


def worst_severity(*severities: Severity) -> Severity:
    """The worst of several severities; "ok" when given none."""
    worst: Severity = "ok"
    for severity in severities:
        if SEVERITY_RANK[severity] > SEVERITY_RANK[worst]:
            worst = severity
    return worst


def resolve_quiet_threshold(config: CoreConfig, integration: str, device_id: str) -> float:
    """Quiet threshold in hours for one device, after overrides."""
    override = settings_for_device(config, device_id)
    if override is not None and override.quiet_threshold_hours is not None:
        return override.quiet_threshold_hours
    per_integration = config.integration_thresholds.get(integration)
    if per_integration is not None:
        return per_integration
    return config.quiet_threshold_hours


def battery_levels(config: CoreConfig, device_id: str | None = None) -> tuple[float, float]:
    """The warning and critical levels for one device: its own, else the options'.

    One level of a device's own is checked against the options when it is
    saved, but the options can change later, so critical is capped at
    warning here.
    """
    override = settings_for_device(config, device_id) if device_id is not None else None
    warning = config.battery_warning
    critical = config.battery_critical
    if override is not None and override.battery_warning is not None:
        warning = override.battery_warning
    if override is not None and override.battery_critical is not None:
        critical = override.battery_critical
    return warning, min(critical, warning)


def battery_severity(
    battery: BatteryReading | None, config: CoreConfig, device_id: str | None = None
) -> Severity:
    """Severity from the battery reading alone, at the device's own levels when it has them."""
    if battery is None:
        return "ok"
    if battery.is_charging:
        return "ok"  # it is being dealt with
    if battery.is_low:
        return "critical"
    if battery.level is None:
        return "ok"  # binary sensor saying "not low"
    warning, critical = battery_levels(config, device_id)
    if battery.level <= critical:
        return "critical"
    if battery.level <= warning:
        return "warning"
    return "ok"


def connectivity_severity(
    is_offline: bool, is_quiet: bool, is_not_provided: bool = False
) -> Severity:
    """Severity from connectivity alone. Stale configuration is only a warning."""
    if is_offline:
        return "critical"
    if is_quiet or is_not_provided:
        return "warning"
    return "ok"


def extras_severity(extras: Iterable[EnhancerExtra]) -> Severity:
    """The worst severity any enhancer attached."""
    return worst_severity(*(extra.severity or "ok" for extra in extras))
