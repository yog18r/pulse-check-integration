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

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
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
from .core.models import AreaEntry, DeviceEntry, EntityEntry, EntityState, Snapshot
from .history import HistoryTracker
from .options import core_config_from_options
from .replacements import ReplacementTracker
from .storage import PulseCheckStore

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

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
        # `immediate=False` means it waits the cooldown first, then runs once.
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
        self._entity_registry = er.async_get(hass)

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
        """Only registered entities can affect the result, so skip the rest early."""
        return event_data["entity_id"] in self._entity_registry.entities

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
            rechargeable = {
                device_id
                for device_id, settings in self.store.device_settings.items()
                if settings.get("rechargeable")
            }
            await self.history.async_refresh(self.data.devices, rechargeable)
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
        """Copy days-left and history facts onto each device; return the soonest to run out."""
        soonest: DeviceHealth | None = None
        for device in devices:
            battery = device.battery
            if battery is None:
                continue
            estimate = self.history.estimates.get(battery.entity_id)
            if estimate is not None:
                device.days_left = estimate.days_left
                if soonest is None or (soonest.days_left or 0) > estimate.days_left:
                    soonest = device
            self.replacements.annotate(device, estimate.rate_per_day if estimate else None, now)
        return soonest


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
