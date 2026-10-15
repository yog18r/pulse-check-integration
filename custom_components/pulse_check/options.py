"""Turning the config entry's options and the stored settings into core config.

Home Assistant stores an integration's user settings in `entry.options`,
a plain dict that the options flow writes. Per-device settings live in
the integration's own store. The core wants a `CoreConfig`. This module
is the only place that knows about all three shapes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import (
    CONF_BATTERY_CRITICAL,
    CONF_BATTERY_WARNING,
    CONF_EXCLUDE_AREAS,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_HOURS,
    CONF_INCLUDE_AREAS,
    CONF_INCLUDE_INTEGRATIONS,
    CONF_INTEGRATION,
    CONF_INTEGRATION_THRESHOLDS,
    CONF_QUIET_SCOPE,
    CONF_QUIET_THRESHOLD_HOURS,
    DEFAULT_BATTERY_CRITICAL,
    DEFAULT_BATTERY_WARNING,
    DEFAULT_QUIET_SCOPE,
    DEFAULT_QUIET_THRESHOLD_HOURS,
)
from .core import CoreConfig

if TYPE_CHECKING:
    from collections.abc import Mapping


def integration_thresholds_from_options(options: Mapping[str, Any]) -> dict[str, float]:
    """The per-integration quiet thresholds as a platform -> hours mapping.

    The options flow stores them as a list of `{integration, hours}` rows
    (that is what the form's list editor produces); the core wants a dict.
    """
    thresholds: dict[str, float] = {}
    for row in options.get(CONF_INTEGRATION_THRESHOLDS) or []:
        platform = str(row.get(CONF_INTEGRATION, "")).strip()
        hours = row.get(CONF_HOURS)
        if platform and isinstance(hours, int | float) and hours > 0:
            thresholds[platform] = float(hours)
    return thresholds


def core_config_from_options(
    options: Mapping[str, Any],
    device_settings: Mapping[str, Mapping[str, Any]] | None = None,
) -> CoreConfig:
    """Build the core configuration, with the card's defaults for anything unset.

    `device_settings` is the store's per-device section, keyed by device id.
    """
    settings = [
        {"device_id": device_id, **values} for device_id, values in (device_settings or {}).items()
    ]
    return CoreConfig.from_dict(
        {
            CONF_BATTERY_WARNING: options.get(CONF_BATTERY_WARNING, DEFAULT_BATTERY_WARNING),
            CONF_BATTERY_CRITICAL: options.get(CONF_BATTERY_CRITICAL, DEFAULT_BATTERY_CRITICAL),
            CONF_QUIET_THRESHOLD_HOURS: options.get(
                CONF_QUIET_THRESHOLD_HOURS, DEFAULT_QUIET_THRESHOLD_HOURS
            ),
            CONF_QUIET_SCOPE: options.get(CONF_QUIET_SCOPE, DEFAULT_QUIET_SCOPE),
            CONF_INTEGRATION_THRESHOLDS: integration_thresholds_from_options(options),
            "device_settings": settings,
            CONF_INCLUDE_AREAS: options.get(CONF_INCLUDE_AREAS) or [],
            CONF_EXCLUDE_AREAS: options.get(CONF_EXCLUDE_AREAS) or [],
            CONF_INCLUDE_INTEGRATIONS: options.get(CONF_INCLUDE_INTEGRATIONS) or [],
            CONF_EXCLUDE_INTEGRATIONS: options.get(CONF_EXCLUDE_INTEGRATIONS) or [],
            CONF_EXCLUDE_DEVICES: options.get(CONF_EXCLUDE_DEVICES) or [],
            CONF_EXCLUDE_ENTITIES: options.get(CONF_EXCLUDE_ENTITIES) or [],
        }
    )
