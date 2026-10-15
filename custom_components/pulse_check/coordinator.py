"""The coordinator: when and how the device list is recomputed.

A `DataUpdateCoordinator` is Home Assistant's standard way to fetch data
once and share it with many entities. Ours does not fetch anything from
the network: it reads Home Assistant's own state machine and registries,
hands a plain snapshot to the pure core, and keeps the result in `data`.

It recomputes:

- about 2 seconds after any state change of a registered entity (a
  debounce, so a burst of changes costs one run), and
- every 5 minutes regardless, so a device that simply stops reporting is
  noticed, and a snooze that expires takes effect.

Battery history (for drain estimates) is heavier, so it is read from the
recorder separately, every 6 hours, and merged into the next result.

It never talks to devices. Everything it reads is already in memory or in
the recorder's database.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DEBOUNCE_SECONDS, DOMAIN, HISTORY_INTERVAL, UPDATE_INTERVAL
from .core import (
    ActionList,
    CoreConfig,
    DeviceHealth,
    Summary,
    action_list,
    analyse_devices,
    summarise,
)
from .core.enhancers import ENHANCERS
from .core.models import (
    AreaEntry,
    DeviceEntry,
    EntityEntry,
    EntityState,
    EstimateInfo,
    Snapshot,
)
from .history import HistoryTracker
from .options import core_config_from_options
from .replacements import ReplacementTracker
from .storage import PulseCheckStore

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Entity attributes the analysis reads: a battery that only exists as an
# attribute (trackers, vacuums) and the charging flags.
_WATCHED_ATTRIBUTES = (
    "battery_level",
    "battery_state",
    "is_charging",
    "charging",
    "battery_charging",
)
# Entities whose state *value* the analysis reads. For every other entity
# only its availability matters (a power sensor's watts never do).
_VALUE_DEVICE_CLASSES = frozenset({"battery", "battery_charging"})

# Registry changes (a renamed device, a new area) also change the result.
_REGISTRY_EVENTS = (
    er.EVENT_ENTITY_REGISTRY_UPDATED,
    dr.EVENT_DEVICE_REGISTRY_UPDATED,
    ar.EVENT_AREA_REGISTRY_UPDATED,
)


@dataclass(slots=True)
class PulseCheckData:
    """One computed result, shared with every entity."""

    devices: list[DeviceHealth]
    summary: Summary
    actions: ActionList
    config: CoreConfig
    computed_at: datetime
    # The battery device with the fewest days left, when any has an estimate.
    next_to_run_out: DeviceHealth | None = None


class PulseCheckCoordinator(DataUpdateCoordinator[PulseCheckData]):
    """Recomputes device health from Home Assistant's state and registries."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up the timer and the debounced refresh."""
        # The debouncer collapses a burst of state changes into one refresh.
        # `immediate=False` means it waits the cooldown first, then runs once,
        # so however often relevant entities change there is at most one
        # recompute per cooldown.
        self._refresh_debouncer: Debouncer[Any] = Debouncer(
            hass, _LOGGER, cooldown=DEBOUNCE_SECONDS, immediate=False
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            request_refresh_debouncer=self._refresh_debouncer,
        )
        self.store = PulseCheckStore(hass)
        self.core_config = core_config_from_options(entry.options)
        self.history = HistoryTracker(hass)
        self.replacements = ReplacementTracker(self.store)
        # Entity ids that belong to an analysed device, from the last run.
        # State changes elsewhere cannot change the result and are ignored.
        self._watched: set[str] = set()

    @callback
    def rebuild_config(self) -> None:
        """Recombine the options and the stored per-device settings."""
        self.core_config = core_config_from_options(
            self.config_entry.options, self.store.device_settings
        )

    async def _async_setup(self) -> None:
        """Subscribe to the events that can change the result.

        Called once by the coordinator before the first refresh. The
        listeners are tied to the config entry so unloading removes them.
        """
        unsubscribe_state = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED,
            self._handle_event,
            event_filter=self._state_event_is_relevant,
        )
        self.config_entry.async_on_unload(unsubscribe_state)
        for event_type in _REGISTRY_EVENTS:
            self.config_entry.async_on_unload(
                self.hass.bus.async_listen(event_type, self._handle_event)
            )
        self.config_entry.async_on_unload(
            async_track_time_interval(self.hass, self._handle_history_timer, HISTORY_INTERVAL)
        )

    @callback
    def _state_event_is_relevant(self, event_data: EventStateChangedData) -> bool:
        """Only a change that can alter the result triggers a recompute.

        Runs for every state change in the house, so it must be cheap: a
        set lookup, then a few comparisons. Power sensors updating every
        second never get past it. Time-based transitions (a device going
        quiet, a snooze expiring) come from the periodic timer instead.
        """
        entity_id = event_data["entity_id"]
        if entity_id not in self._watched:
            return False
        reason = change_reason(entity_id, event_data["old_state"], event_data["new_state"])
        if reason is None:
            return False
        _LOGGER.debug("Recompute: %s %s", entity_id, reason)
        return True

    @callback
    def _handle_event(self, _event: Event[Any]) -> None:
        """Schedule a debounced refresh. Cheap: no task per event."""
        self._refresh_debouncer.async_schedule_call()

    @callback
    def _handle_history_timer(self, _now: datetime) -> None:
        """Every few hours, re-read battery history in the background."""
        self.config_entry.async_create_background_task(
            self.hass, self.async_refresh_history(), "pulse_check history"
        )

    async def async_refresh_history(self) -> None:
        """Re-read battery history from the recorder, then recompute.

        Recorder trouble must never take the sensors down, so failures are
        logged and the previous estimates (if any) are kept.
        """
        try:
            await self.history.async_refresh(self.data.devices, self.store, self.core_config)
        except Exception:
            _LOGGER.warning("Reading battery history from the recorder failed", exc_info=True)
            return
        await self.async_refresh()

    async def _async_update_data(self) -> PulseCheckData:
        """Build a snapshot in the event loop, then analyse it in a worker thread.

        Registries must be read from the event loop. The analysis is pure
        Python over plain dicts, so it runs in the executor and never
        blocks Home Assistant, however many devices there are.
        """
        started = time.perf_counter()
        now = dt_util.utcnow()
        snapshot = build_snapshot(self.hass)
        config = self.core_config
        snoozes = self.store.snoozes(now)
        devices = await self.hass.async_add_executor_job(_analyse, snapshot, config, now, snoozes)
        self._watched = {entity_id for device in devices for entity_id in device.entity_ids}
        self.replacements.observe(devices, now)
        next_to_run_out = self._attach_drain_estimates(devices, now)
        _LOGGER.debug(
            "Analysed %d entities into %d devices in %.1f ms",
            len(snapshot["entities"]),
            len(devices),
            (time.perf_counter() - started) * 1000,
        )
        return PulseCheckData(
            devices=devices,
            summary=summarise(devices, config),
            actions=action_list(devices, config),
            config=config,
            computed_at=now,
            next_to_run_out=next_to_run_out,
        )

    def _attach_drain_estimates(
        self, devices: list[DeviceHealth], now: datetime
    ) -> DeviceHealth | None:
        """Copy the battery insight onto each device; return the soonest to run out."""
        soonest: DeviceHealth | None = None
        for device in devices:
            battery = device.battery
            if battery is None:
                continue
            insight = self.history.insights.get(battery.entity_id)
            if insight is not None:
                device.battery_kind = insight.kind
                device.unusual = insight.unusual
                estimate = insight.estimate
                if estimate is not None:
                    device.days_left = estimate.days_left
                    device.estimate = EstimateInfo(
                        days_left=estimate.days_left,
                        basis=estimate.basis,
                        confidence=estimate.confidence,
                        kind=estimate.kind,
                        open_ended=estimate.open_ended,
                    )
                    sooner = soonest is None or (soonest.days_left or 0) > estimate.days_left
                    if not estimate.open_ended and sooner:
                        soonest = device
            self.replacements.annotate(device, now)
        return soonest


def change_reason(entity_id: str, old: State | None, new: State | None) -> str | None:
    """Why this state change matters to the analysis, or None if it does not.

    Appearing, disappearing and availability always matter (offline
    detection). A new state value matters for batteries, charging signals
    and Z-Wave node status; a watched attribute changing matters for
    attribute batteries. Anything else (a new reading from a power or
    temperature sensor, an attribute-only update) is ignored.
    """
    if old is None:
        return "appeared"
    if new is None:
        return "removed"
    if (old.state == STATE_UNAVAILABLE) != (new.state == STATE_UNAVAILABLE):
        return "availability changed"
    if old.state != new.state and value_matters(entity_id, new.attributes):
        return f"{old.state} -> {new.state}"
    for attribute in _WATCHED_ATTRIBUTES:
        if old.attributes.get(attribute) != new.attributes.get(attribute):
            return f"{attribute} changed"
    return None


def value_matters(entity_id: str, attributes: Mapping[str, Any]) -> bool:
    """Does the analysis read this entity's state value, not just its availability?"""
    if attributes.get("device_class") in _VALUE_DEVICE_CLASSES:
        return True
    domain = entity_id.split(".", 1)[0]
    return domain in ("sensor", "binary_sensor") and (
        "battery" in entity_id or entity_id.endswith("_node_status")
    )


def _analyse(
    snapshot: Snapshot, config: CoreConfig, now: datetime, snoozes: dict[str, datetime]
) -> list[DeviceHealth]:
    return analyse_devices(snapshot, config, now, enhancers=ENHANCERS, snoozes=snoozes)


@callback
def build_snapshot(hass: HomeAssistant) -> Snapshot:
    """Copy the parts of Home Assistant's state and registries the core reads.

    The copies are shallow: `attributes` is Home Assistant's own read-only
    mapping, so this costs one small dict per entity and nothing more.
    """
    entities: dict[str, EntityEntry] = {}
    for entry in er.async_get(hass).entities.values():
        if entry.disabled_by is not None:
            continue
        entity: EntityEntry = {"entity_id": entry.entity_id}
        if entry.device_id is not None:
            entity["device_id"] = entry.device_id
        if entry.area_id is not None:
            entity["area_id"] = entry.area_id
        if entry.platform:
            entity["platform"] = entry.platform
        if entry.entity_category is not None:
            entity["entity_category"] = entry.entity_category.value
        if entry.hidden_by is not None:
            entity["hidden"] = True
        if entry.name:
            entity["name"] = entry.name
        entities[entry.entity_id] = entity

    states: dict[str, EntityState] = {}
    for state in hass.states.async_all():
        states[state.entity_id] = {
            "entity_id": state.entity_id,
            "state": state.state,
            "attributes": state.attributes,
            "last_changed": state.last_changed,
            "last_updated": state.last_updated,
            "last_reported": state.last_reported,
        }

    devices: dict[str, DeviceEntry] = {}
    for device in dr.async_get(hass).devices:
        devices[device.id] = {
            "id": device.id,
            "name": device.name,
            "name_by_user": device.name_by_user,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "area_id": device.area_id,
            "entry_type": "service" if device.entry_type is dr.DeviceEntryType.SERVICE else None,
            "disabled_by": device.disabled_by.value if device.disabled_by is not None else None,
        }

    areas: dict[str, AreaEntry] = {
        area.id: {"area_id": area.id, "name": area.name}
        for area in ar.async_get(hass).areas.values()
    }

    return {"states": states, "entities": entities, "devices": devices, "areas": areas}
