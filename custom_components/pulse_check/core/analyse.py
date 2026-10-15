"""The orchestrator: snapshot + config -> one DeviceHealth per device.

This is the single function the Home Assistant layer calls. Everything
else in the core is a building block it composes. Keeping it pure (no HA,
`now` passed in) means the whole pipeline is testable with one fixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .availability import detect_last_heard, detect_offline, is_quiet
from .battery import detect_battery
from .enhancers import apply_enhancers
from .group import (
    DeviceGroup,
    area_id_of,
    area_name,
    collect_device_groups,
    display_name,
    dominant_integration,
)
from .models import DeviceHealth, Severity, as_utc
from .settings import settings_for_device
from .thresholds import (
    battery_severity,
    connectivity_severity,
    extras_severity,
    resolve_quiet_threshold,
    worst_severity,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from .enhancers import Enhancer
    from .models import CoreConfig, Snapshot


def _list_has(items: Iterable[str], *values: str | None) -> bool:
    """Case-insensitive membership test for user-typed lists."""
    wanted = {item.strip().lower() for item in items}
    return any(value is not None and value.strip().lower() in wanted for value in values)


def _is_excluded(
    group: DeviceGroup, integration: str, config: CoreConfig, snapshot: Snapshot
) -> bool:
    """Apply the integration, area and device allow/deny lists."""
    if config.include_integrations and not _list_has(config.include_integrations, integration):
        return True
    if _list_has(config.exclude_integrations, integration):
        return True

    # Area lists match the area's id or its display name. A per-device
    # `area` setting stands in for the registry's area.
    if config.include_areas or config.exclude_areas:
        settings = settings_for_device(config, group.device_id)
        override = settings.area if settings is not None else None
        area_id = override if override is not None else area_id_of(group)
        if override is not None:
            name = override
        elif area_id is not None and area_id in snapshot["areas"]:
            name = snapshot["areas"][area_id]["name"]
        else:
            name = None
        if config.include_areas and not _list_has(config.include_areas, area_id, name):
            return True
        if _list_has(config.exclude_areas, area_id, name):
            return True

    if group.device_id in config.exclude_devices:
        return True
    # Allow excluding an orphan by its bare entity id too.
    if group.device is None and group.entities:
        entity_id = group.entities[0]["entity_id"]
        if entity_id in config.exclude_devices:
            return True
    return False


def _without_excluded_entities(group: DeviceGroup, config: CoreConfig) -> DeviceGroup | None:
    """Drop individually excluded entities. Returns None if nothing is left."""
    if not config.exclude_entities:
        return group
    banned = set(config.exclude_entities)
    entities = [e for e in group.entities if e["entity_id"] not in banned]
    if not entities:
        return None
    states = [s for s in group.states if s["entity_id"] not in banned]
    return DeviceGroup(
        device_id=group.device_id, device=group.device, entities=entities, states=states
    )


def analyse_devices(
    snapshot: Snapshot,
    config: CoreConfig,
    now: datetime,
    enhancers: Iterable[Enhancer] = (),
    snoozes: Mapping[str, datetime] | None = None,
) -> list[DeviceHealth]:
    """Analyse every device in the snapshot.

    Args:
        snapshot: states and registries, see `models.Snapshot`.
        config: thresholds, filters and per-device settings.
        now: the moment to judge "quiet" and snoozes against.
        enhancers: integration-specific extras, usually `enhancers.ENHANCERS`.
        snoozes: device id -> when the user's snooze ends.
    """
    now = as_utc(now)
    enhancers = tuple(enhancers)
    results: list[DeviceHealth] = []

    for raw_group in collect_device_groups(snapshot):
        integration = dominant_integration(raw_group.entities)
        if _is_excluded(raw_group, integration, config, snapshot):
            continue

        group = _without_excluded_entities(raw_group, config)
        if group is None:
            continue

        battery = detect_battery(group.states, snapshot["entities"])

        # A lone entity with no device is only interesting if it tells us
        # about a battery. Otherwise (template helpers, input_booleans...)
        # it is noise. And even then, it can only ever be a battery reading:
        # with no device behind it there is nothing to be offline or quiet.
        is_orphan = group.device is None
        if is_orphan and battery is None:
            continue

        # Enhancers run first so their better signals (a Z-Wave "dead"
        # node, a Zigbee2MQTT last_seen timestamp) can feed the rules below.
        enhanced = apply_enhancers(enhancers, integration, group, snapshot)

        is_offline = not is_orphan and (
            enhanced.offline or detect_offline(group.entities, snapshot["states"])
        )

        # Last heard: the newest of the generic rule and any enhancer signal.
        last_heard = detect_last_heard(group.states, snapshot["entities"])
        if enhanced.last_heard is not None and (
            last_heard is None or enhanced.last_heard > last_heard
        ):
            last_heard = enhanced.last_heard

        # Quiet detection only makes sense for devices expected to report on
        # their own. By default that is battery devices; mains devices go
        # unavailable when they drop off, and an untouched light is not news.
        quiet_eligible = (
            not is_orphan
            and not is_offline
            and (config.quiet_scope == "all" or battery is not None)
        )
        quiet_hours = resolve_quiet_threshold(config, integration, group.device_id)
        quiet = quiet_eligible and is_quiet(last_heard, now, quiet_hours)

        snoozed_until = snoozes.get(group.device_id) if snoozes else None
        snoozed = snoozed_until is not None and as_utc(snoozed_until) > now

        severity: Severity = (
            "ok"
            if snoozed
            else worst_severity(
                battery_severity(battery, config),
                connectivity_severity(is_offline, quiet),
                extras_severity(enhanced.extras),
            )
        )

        settings = settings_for_device(config, group.device_id)
        device = group.device
        results.append(
            DeviceHealth(
                device_id=group.device_id,
                # The user's display name wins over the registry's. It changes
                # only what is shown; the device itself keeps its name.
                name=settings.name if settings and settings.name else display_name(group),
                integration=integration,
                is_offline=is_offline,
                is_quiet=quiet,
                quiet_threshold_hours=quiet_hours,
                severity=severity,
                extras=enhanced.extras,
                entity_ids=[e["entity_id"] for e in group.entities],
                area=settings.area if settings and settings.area else area_name(group, snapshot),
                manufacturer=device["manufacturer"] if device and device["manufacturer"] else None,
                model=device["model"] if device and device["model"] else None,
                battery=battery,
                last_heard=last_heard,
                snoozed_until=as_utc(snoozed_until) if snoozed and snoozed_until else None,
            )
        )

    return results
