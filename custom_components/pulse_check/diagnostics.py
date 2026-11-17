"""Diagnostics: Settings > Devices & services > Pulse Check > ⋮ > Download diagnostics.

People attach this file to bug reports, often in public, so it is built
from an allowlist: only values known to be safe to share are copied in,
and everything else is left out or reduced to a count. It never holds a
name (of a device, an area, a person or their phone), an entity or device
id, an IP address or any other address, a notification target, or text
typed into a setting. Devices are numbered instead ("device_1"), so one
report can still be followed from top to bottom.

A new option or setting is left out until it is added to an allowlist
here, so forgetting this file can only make the report less useful, never
leak anything.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .const import (
    CONF_BATTERY_CRITICAL,
    CONF_BATTERY_WARNING,
    CONF_CHARGING_QUIET_FACTOR,
    CONF_CLEAR_RESOLVED,
    CONF_CONFIRM_MINUTES,
    CONF_DIGEST_TIME,
    CONF_DIGEST_WEEKDAY,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_INCLUDE_INTEGRATIONS,
    CONF_INTEGRATION_LIMIT,
    CONF_INTEGRATION_THRESHOLDS,
    CONF_MAINTENANCE_HOURS,
    CONF_NOTIFY_CRITICAL,
    CONF_NOTIFY_WARNING,
    CONF_PER_DEVICE_SENSORS,
    CONF_PING_QUIET,
    CONF_QUIET_SCOPE,
    CONF_QUIET_THRESHOLD_HOURS,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_MAX,
    CONF_RESTART_TIMEOUT_MINUTES,
    CONF_STARTUP_GRACE_MINUTES,
    CONF_WATCH_NON_DEVICES,
    CONF_WEEKLY_ALL_CLEAR,
    DATA_VERSION,
)
from .core.group import ORPHAN_PREFIX
from .notify import DATA_RUNTIME
from .options import integration_thresholds_from_options
from .ping import ping_method

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import PulseCheckCoordinator
    from .core.models import DeviceHealth

# Options copied as they are: numbers, switches and fixed choices.
_PLAIN_OPTIONS = frozenset(
    {
        CONF_BATTERY_WARNING,
        CONF_BATTERY_CRITICAL,
        CONF_QUIET_THRESHOLD_HOURS,
        CONF_QUIET_SCOPE,
        CONF_WATCH_NON_DEVICES,
        CONF_PING_QUIET,
        CONF_CHARGING_QUIET_FACTOR,
        CONF_NOTIFY_CRITICAL,
        CONF_NOTIFY_WARNING,
        CONF_REMINDER_DAYS,
        CONF_REMINDER_MAX,
        CONF_DIGEST_TIME,
        CONF_DIGEST_WEEKDAY,
        CONF_WEEKLY_ALL_CLEAR,
        CONF_CLEAR_RESOLVED,
        CONF_STARTUP_GRACE_MINUTES,
        CONF_CONFIRM_MINUTES,
        CONF_RESTART_TIMEOUT_MINUTES,
        CONF_MAINTENANCE_HOURS,
        CONF_INTEGRATION_LIMIT,
        CONF_PER_DEVICE_SENSORS,
    }
)
# Options that list integrations ("zha", "mobile_app"), which say nothing
# about the home. Every other list (areas, devices, entities, notification
# targets) is only counted.
_INTEGRATION_OPTIONS = frozenset({CONF_INCLUDE_INTEGRATIONS, CONF_EXCLUDE_INTEGRATIONS})
# Per-device settings copied as they are; the others (name, area, battery
# type) are typed by the user and only said to be set.
_PLAIN_SETTINGS = frozenset(
    {
        "quiet_threshold_hours",
        "battery_count",
        "rechargeable",
        "notify_policy",
        "sparkline_days",
        "battery_warning",
        "battery_critical",
    }
)
# A fixed choice or code ("battery", "instant", "09:00:00", "zwave_js"),
# never free text: anything else is left out even where a code is expected.
_CODE = re.compile(r"[a-z0-9_:.\-]{1,32}")


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """What a bug report needs, and nothing that identifies a home or a person."""
    report: dict[str, Any] = {
        "version": hass.data.get(DATA_VERSION),
        "options": _options(entry.options),
    }
    coordinator: PulseCheckCoordinator | None = getattr(entry, "runtime_data", None)
    if coordinator is None or coordinator.data is None:
        report["loaded"] = False
        return report
    data = coordinator.data
    numbers = {device.device_id: f"device_{n}" for n, device in enumerate(data.devices, 1)}
    ready_at = hass.data.get(DATA_RUNTIME, {}).get("ready_at")
    report["loaded"] = True
    report["runtime"] = {
        "last_update_success": coordinator.last_update_success,
        "computed_at": data.computed_at.isoformat(),
        "home_assistant_running": hass.is_running,
        "startup_grace_over": ready_at is not None and data.computed_at >= ready_at,
        "history_loaded": coordinator.history_loaded,
        "batteries_with_history": len(coordinator.history.insights),
        "silent_after_asking": coordinator.silent_after_asking,
    }
    report["counts"] = _counts(data.devices)
    report["store"] = _store(coordinator.store.data)
    report["devices"] = [
        _device(hass, coordinator, device, numbers[device.device_id]) for device in data.devices
    ]
    return report


def _code(value: object) -> str | None:
    """`value` when it is a short code, else None."""
    return value if isinstance(value, str) and _CODE.fullmatch(value) else None


def _plain(value: object) -> object:
    """A number, a switch or a code as it is; anything else only as "set"."""
    if value is None or isinstance(value, bool | int | float):
        return value
    return _code(value) or "(set)"


def _counted(value: object) -> object:
    """How many items a list or mapping has; whether anything else is set."""
    if isinstance(value, list | tuple | set | frozenset | dict):
        return {"count": len(value)}
    return None if value in (None, "") else "(set)"


def _options(options: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in sorted(options.items()):
        if key in _PLAIN_OPTIONS:
            out[key] = _plain(value)
        elif key in _INTEGRATION_OPTIONS and isinstance(value, list | tuple):
            codes = [code for item in value if (code := _code(item)) is not None]
            out[key] = sorted(codes) if len(codes) == len(value) else {"count": len(value)}
        elif key == CONF_INTEGRATION_THRESHOLDS:
            thresholds = integration_thresholds_from_options(options)
            out[key] = {
                platform: hours
                for platform, hours in sorted(thresholds.items())
                if _code(platform) is not None
            }
        elif _code(key) is not None:
            out[key] = _counted(value)
    return out


def _counts(devices: list[DeviceHealth]) -> dict[str, int]:
    return {
        "devices": len(devices),
        "offline": sum(d.is_offline for d in devices),
        "quiet": sum(d.is_quiet for d in devices),
        "not_provided": sum(d.is_not_provided for d in devices),
        "warning": sum(d.severity == "warning" for d in devices),
        "critical": sum(d.severity == "critical" for d in devices),
        "snoozed": sum(d.snoozed_until is not None for d in devices),
        "with_battery": sum(d.battery is not None for d in devices),
        "without_a_device": sum(d.device_id.startswith(ORPHAN_PREFIX) for d in devices),
    }


def _store(data: Mapping[str, Any]) -> dict[str, Any]:
    """How much is saved in each section, not what."""
    out: dict[str, Any] = {}
    for section, value in sorted(data.items()):
        if _code(section) is None:
            continue
        if section == "maintenance":
            out[section] = {"active": bool(isinstance(value, dict) and value.get("until"))}
        else:
            out[section] = _counted(value)
    return out


def _device(
    hass: HomeAssistant, coordinator: PulseCheckCoordinator, device: DeviceHealth, number: str
) -> dict[str, Any]:
    computed_at = coordinator.data.computed_at
    out: dict[str, Any] = {
        "id": number,
        "source": device.source,
        "integration": _code(device.integration),
        "device_type": _code(device.device_type),
        "severity": device.severity,
        "offline": device.is_offline,
        "quiet": device.is_quiet,
        "not_provided": device.is_not_provided,
        "snoozed": device.snoozed_until is not None,
        "quiet_threshold_hours": device.quiet_threshold_hours,
        "last_heard_hours_ago": (
            round((computed_at - device.last_heard).total_seconds() / 3600, 2)
            if device.last_heard is not None
            else None
        ),
        "entities": len(device.entity_ids),
        "unavailable_parts": len(device.unavailable_parts),
        "extras": len(device.extras),
    }
    battery = device.battery
    if battery is not None:
        out["battery"] = {
            "source": battery.source,
            "level": battery.level,
            "low": battery.is_low,
            "charging": battery.is_charging,
            "kind": _code(device.battery_kind),
            "days_left": round(device.days_left, 1) if device.days_left is not None else None,
            "estimate": (
                {
                    "basis": _code(device.estimate.basis),
                    "confidence": _code(device.estimate.confidence),
                    "kind": _code(device.estimate.kind),
                }
                if device.estimate is not None
                else None
            ),
        }
    settings = coordinator.store.device_settings.get(device.device_id)
    if isinstance(settings, dict) and settings:
        out["settings"] = {
            key: _plain(value) if key in _PLAIN_SETTINGS else "(set)"
            for key, value in sorted(settings.items())
            if _code(key) is not None
        }
    notify = coordinator.store.notify.get(device.device_id)
    if isinstance(notify, dict) and notify:
        out["open_problems"] = sorted(kind for kind in notify if _code(kind) is not None)
    if not device.device_id.startswith(ORPHAN_PREFIX):
        method, address_from = ping_method(hass, device.device_id)
        out["ping"] = {"method": method, "address_from": address_from}
    return out
