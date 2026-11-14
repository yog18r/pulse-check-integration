"""The coordinator: when and how the device list is recomputed.

A `DataUpdateCoordinator` is Home Assistant's standard way to fetch data
once and share it with many entities. Ours does not fetch anything from
the network: it reads Home Assistant's own state machine and registries,
hands a plain snapshot to the pure core, and keeps the result in `data`.

It recomputes:

- about 10 seconds after a relevant state change of an analysed entity,
  a registry change, or a new battery entity appearing (a debounce, so a
  burst of changes costs one run), and
- every 5 minutes regardless, so a device that simply stops reporting is
  noticed, and a snooze that expires takes effect.

Battery history (for drain estimates) is heavier, so it is read from the
recorder separately, every 6 hours, and merged into the next result.

Everything it reads is already in memory or in the recorder's database.
The one time it talks to a device is when the device is about to be marked
quiet: with `ping_quiet` on, it is asked once whether it is still there
(see `ping.py`), and one that answers is not quiet.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PING_QUIET,
    DEBOUNCE_SECONDS,
    DEFAULT_PING_QUIET,
    DOMAIN,
    HISTORY_CATCH_UP_DELAY,
    HISTORY_INTERVAL,
    UPDATE_INTERVAL,
)
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
from .core.group import ORPHAN_PREFIX
from .core.models import (
    AreaEntry,
    DeviceEntry,
    EntityEntry,
    EntityState,
    EstimateInfo,
    Snapshot,
)
from .history import HistoryTracker
from .notify import DATA_RUNTIME
from .options import core_config_from_options
from .ping import async_ping_device
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

# Quiet devices asked at the same time, at most.
MAX_CONCURRENT_PINGS = 10
# The quiet devices already asked, kept across reloads (see `_asked`).
DATA_ASKED = f"{DOMAIN}_asked"

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
    # The replaceable battery with the fewest days left, when any has an estimate.
    next_to_run_out: DeviceHealth | None = None
    # The devices by id, for entities that look up their own.
    by_id: dict[str, DeviceHealth] = field(default_factory=dict)


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
        # The websocket snapshot for the current `data`, shared by subscribers.
        self.payload_cache: tuple[PulseCheckData, dict[str, Any]] | None = None
        self.core_config = core_config_from_options(entry.options)
        self.history = HistoryTracker(hass)
        self.replacements = ReplacementTracker(self.store)
        # Entity ids that belong to an analysed device, from the last run.
        # State changes elsewhere cannot change the result and are ignored.
        self._watched: set[str] = set()
        # True once a full history read has finished; a battery with a level
        # but no insight after that has appeared since, and is caught up.
        self._history_loaded = False
        self._catch_up_cancel: CALLBACK_TYPE | None = None
        # One history read at a time. The timer, the refresh service, the
        # start and a catch-up can each ask for one; a full read finishing
        # after a catch-up would otherwise drop what the catch-up found.
        self._history_lock = asyncio.Lock()
        # Quiet devices already asked whether they are there, and silent.
        # Each is asked once when its timer runs out, not on every run, and
        # not again because the options were saved: the set outlives a reload.
        self._asked: set[str] = hass.data.setdefault(DATA_ASKED, set())

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
        self.config_entry.async_on_unload(self._cancel_catch_up)
        self.config_entry.async_on_unload(
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._save_on_stop)
        )

    @callback
    def _save_on_stop(self, _event: Event) -> None:
        """Write last heard, which is saved only now and then, before the restart."""
        self.store.async_save()

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
            # A new battery with no registry entry announces itself only
            # here; registry entities also bring a registry event.
            return event_data["old_state"] is None and looks_like_battery(event_data["new_state"])
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

    async def async_refresh_history(self, reuse: bool = False) -> None:
        """Re-read battery history from the recorder, then recompute.

        Recorder trouble must never take the sensors down, so failures are
        logged and the previous estimates (if any) are kept. With `reuse`
        (after saving options), means read in the last six hours are judged
        again under the new settings rather than read again.
        """
        try:
            async with self._history_lock:
                await self.history.async_refresh(
                    self.data.devices, self.store, self.core_config, reuse=reuse
                )
        except Exception:
            _LOGGER.warning("Reading battery history from the recorder failed", exc_info=True)
            return
        self._history_loaded = True
        await self.async_refresh()

    async def async_catch_up_history(self, entity_ids: set[str]) -> None:
        """Read history for batteries that got a reading after the last full read.

        A cloud integration slow to start after a restart, a device paired
        today, a sensor that woke up late: without this they would wait up
        to six hours for the next full read. Only these batteries are read.
        """
        _LOGGER.debug("Reading history for batteries that appeared since: %s", entity_ids)
        try:
            async with self._history_lock:
                await self.history.async_refresh(
                    self.data.devices, self.store, self.core_config, only=entity_ids
                )
        except Exception:
            _LOGGER.warning("Reading battery history from the recorder failed", exc_info=True)
            return
        await self.async_refresh()

    @callback
    def _schedule_catch_up(self, devices: list[DeviceHealth]) -> None:
        """After a full read, read soon for any battery it did not cover.

        At most one catch-up waits at a time, so a restart bringing devices
        back one by one costs a read every few minutes, not one per device.
        """
        if (
            not self._history_loaded
            or self._catch_up_cancel is not None
            or not self.history.available
        ):
            return
        if not self._uncovered(devices):
            return
        self._catch_up_cancel = async_call_later(
            self.hass, HISTORY_CATCH_UP_DELAY, self._handle_catch_up
        )

    def _uncovered(self, devices: list[DeviceHealth]) -> set[str]:
        """Battery entities with a level that no history read has covered yet."""
        return {
            device.battery.entity_id
            for device in devices
            if device.battery is not None
            and device.battery.level is not None
            and device.battery.entity_id not in self.history.insights
        }

    @callback
    def _cancel_catch_up(self) -> None:
        if self._catch_up_cancel is not None:
            self._catch_up_cancel()
            self._catch_up_cancel = None

    @callback
    def _handle_catch_up(self, _now: datetime) -> None:
        self._catch_up_cancel = None
        uncovered = self._uncovered(self.data.devices)
        if uncovered:
            self.config_entry.async_create_background_task(
                self.hass, self.async_catch_up_history(uncovered), "pulse_check history catch-up"
            )

    async def _async_update_data(self) -> PulseCheckData:
        """Build a snapshot in the event loop, then analyse it in a worker thread.

        Registries must be read from the event loop. The analysis is pure
        Python over plain dicts, so it runs in the executor and never
        blocks Home Assistant, however many devices there are.
        """
        started = time.perf_counter()
        now = dt_util.utcnow()
        snapshot = build_snapshot(self.hass)
        if self._adopt_entity_settings(snapshot):
            self.rebuild_config()
        config = self.core_config
        snoozes = self.store.snoozes(now)
        heard = self.store.last_heard()
        # While Home Assistant starts, and for its grace period after, what
        # integrations write is mostly their cached values (see `analyse`).
        replayed_until: datetime | None = (
            self.hass.data.get(DATA_RUNTIME, {}).get("ready_at") if self.hass.is_running else now
        )
        devices = await self.hass.async_add_executor_job(
            _analyse, snapshot, config, now, snoozes, heard, replayed_until
        )
        answered = await self._ask_quiet_devices(devices)
        if answered:
            heard = {**heard, **dict.fromkeys(answered, now)}
            devices = await self.hass.async_add_executor_job(
                _analyse, snapshot, config, now, snoozes, heard, replayed_until
            )
        self.store.note_heard(((d.device_id, d.last_heard) for d in devices), now)
        self._watched = {entity_id for device in devices for entity_id in device.entity_ids}
        # The history's verdicts first: whether a battery gets charged
        # decides how a rise in its level is recorded.
        next_to_run_out = self._attach_drain_estimates(devices)
        self.replacements.observe(devices, now)
        for device in devices:
            self.replacements.annotate(device, now)
        if self.hass.is_running:
            registry = er.async_get(self.hass)
            self.store.prune(lambda device_id: _exists(snapshot, registry, device_id), now)
        self._schedule_catch_up(devices)
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
            by_id={device.device_id: device for device in devices},
        )

    async def _ask_quiet_devices(self, devices: list[DeviceHealth]) -> set[str]:
        """Ask each newly quiet device whether it is there; return those that answered.

        A device that answers counts as heard from now, so its timer starts
        again and it is asked again only when that runs out. One that stays
        silent is not asked again until it has been heard from. Nothing is
        asked while Home Assistant starts, when integrations are not ready
        to answer for their devices.
        """
        quiet = {device.device_id for device in devices if device.is_quiet}
        self._asked &= quiet
        if not self.hass.is_running or not self.config_entry.options.get(
            CONF_PING_QUIET, DEFAULT_PING_QUIET
        ):
            return set()
        to_ask = sorted(
            device_id
            for device_id in quiet - self._asked
            if not device_id.startswith(ORPHAN_PREFIX)
        )
        if not to_ask:
            return set()
        self._asked.update(to_ask)
        # A few at a time: after a long outage many devices can run out of
        # time together, and each ping can take a while to give up.
        limit = asyncio.Semaphore(MAX_CONCURRENT_PINGS)

        async def ask(device_id: str) -> bool:
            async with limit:
                return await async_ping_device(self.hass, device_id)

        results = await asyncio.gather(*(ask(device_id) for device_id in to_ask))
        answered = {device_id for device_id, ok in zip(to_ask, results, strict=True) if ok}
        self._asked -= answered
        if answered:
            _LOGGER.debug("Answered a ping, so not quiet: %s", sorted(answered))
        return answered

    def _adopt_entity_settings(self, snapshot: Snapshot) -> bool:
        """Move what was saved for a lone entity onto the device it now belongs to.

        An entity with no device is stored as `entity:<entity_id>`. When an
        integration later gives it a device (FoxESS did for its battery
        sensor), those settings, snooze and replacement history would never
        apply again. They move to the device, unless it has its own already.
        Returns True when anything moved.
        """
        moved = False
        data = self.store.data
        for key in [k for k in data["device_settings"] if k.startswith(ORPHAN_PREFIX)]:
            entity = snapshot["entities"].get(key.removeprefix(ORPHAN_PREFIX))
            device_id = entity.get("device_id") if entity is not None else None
            if device_id is None or device_id not in snapshot["devices"]:
                continue
            if device_id in data["device_settings"]:
                continue  # the device has settings of its own: leave both alone
            for section in ("device_settings", "snoozes", "history", "heard"):
                if key in data[section] and device_id not in data[section]:
                    data[section][device_id] = data[section].pop(key)
            _LOGGER.info("Moved the settings saved for %s to its device", key)
            moved = True
        if moved:
            self.store.async_save()
        return moved

    def _attach_drain_estimates(self, devices: list[DeviceHealth]) -> DeviceHealth | None:
        """Copy the battery insight onto each device; return the next to replace.

        That is the replaceable battery with the fewest days left, "more than
        a year" included, the lowest level breaking a tie. Batteries that get
        charged are left out: a phone needing a charge tonight is not news.
        """
        soonest: DeviceHealth | None = None
        soonest_key: tuple[float, float] | None = None
        for device in devices:
            battery = device.battery
            if battery is None:
                continue
            insight = self.history.insights.get(battery.entity_id)
            if insight is not None:
                device.battery_kind = insight.kind
                device.unusual = insight.unusual
                device.usual_low = insight.usual_low
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
                    key = (estimate.days_left, battery.level if battery.level is not None else 100)
                    if estimate.kind == "replace" and (soonest_key is None or key < soonest_key):
                        soonest, soonest_key = device, key
        return soonest


def _exists(snapshot: Snapshot, registry: er.EntityRegistry, device_id: str) -> bool:
    """Whether an id still names a device, or an entity with no device.

    Disabled devices are in the snapshot; disabled entities are not, so
    the entity registry is asked as well.
    """
    if device_id.startswith(ORPHAN_PREFIX):
        entity_id = device_id.removeprefix(ORPHAN_PREFIX)
        return (
            entity_id in snapshot["entities"]
            or entity_id in snapshot["states"]
            or registry.async_get(entity_id) is not None
        )
    return device_id in snapshot["devices"]


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


def looks_like_battery(state: State | None) -> bool:
    """Could this state be a battery reading? A cheap first look, not the rule."""
    if state is None:
        return False
    attributes = state.attributes
    return attributes.get("device_class") == "battery" or "battery_level" in attributes


def _analyse(
    snapshot: Snapshot,
    config: CoreConfig,
    now: datetime,
    snoozes: dict[str, datetime],
    heard: dict[str, datetime],
    replayed_until: datetime | None,
) -> list[DeviceHealth]:
    return analyse_devices(
        snapshot,
        config,
        now,
        enhancers=ENHANCERS,
        snoozes=snoozes,
        heard=heard,
        replayed_until=replayed_until,
    )


@callback
def _is_placeholder(state: State | None) -> bool:
    """Home Assistant's stand-in for a registered entity nobody has set up."""
    return (
        state is not None
        and state.state == STATE_UNAVAILABLE
        and state.attributes.get("restored") is True
    )


@callback
def _is_running(hass: HomeAssistant, entry: er.RegistryEntry, loaded: set[str]) -> bool:
    """Whether the integration that made the entity is running.

    For a config entry, that it is loaded. An entity set up from YAML has
    none: its platform is running when Home Assistant lists it among the
    loaded components ("template.sensor"), which it only does once the
    platform has set up without error. An integration that is its own
    domain (automation, script, input_boolean) is listed by its name alone.
    """
    if entry.config_entry_id is not None:
        return entry.config_entry_id in loaded
    components = hass.config.components
    if entry.platform == entry.domain:
        return entry.platform in components
    return f"{entry.platform}.{entry.domain}" in components


@callback
def _registry_devices(hass: HomeAssistant) -> dict[str, DeviceEntry]:
    """The device registry, child devices included, as the core reads it."""
    registry = dr.async_get(hass)
    devices: dict[str, DeviceEntry] = {}
    for device in registry.devices:
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
    # Child devices (Home Assistant 2026.10) are not among `devices`, yet an
    # entity's `device_id` can point at one. Each is a device of its own;
    # what it does not say for itself comes from its parent.
    for child in getattr(registry, "child_devices", ()):
        parent = devices.get(child.parent_device_id)
        child_disabled = child.disabled_by.value if child.disabled_by is not None else None
        devices[child.id] = {
            "id": child.id,
            "name": child.name,
            "name_by_user": child.name_by_user,
            # A child has no manufacturer or model of its own (asking for
            # them logs a deprecation warning): they are its parent's.
            "manufacturer": parent["manufacturer"] if parent else None,
            "model": parent["model"] if parent else None,
            "area_id": child.area_id or (parent["area_id"] if parent else None),
            "entry_type": parent["entry_type"] if parent else None,
            "disabled_by": child_disabled or (parent["disabled_by"] if parent else None),
        }
    return devices


def build_snapshot(hass: HomeAssistant) -> Snapshot:
    """Copy the parts of Home Assistant's state and registries the core reads.

    The copies are shallow: `attributes` is Home Assistant's own read-only
    mapping, so this costs one small dict per entity and nothing more.
    """
    entities: dict[str, EntityEntry] = {}
    # Integrations that are running. An entity of one of these that still
    # shows Home Assistant's restored placeholder is one the integration no
    # longer provides. For an integration that failed to start, the same
    # placeholder means the hardware may really be down, so it is not marked.
    loaded = {
        entry.entry_id
        for entry in hass.config_entries.async_entries()
        if entry.state is ConfigEntryState.LOADED
    }
    # A state with no registry entry is analysed as a device-less entity,
    # so a disabled entity's state, which lingers until its integration
    # reloads, must not be copied either.
    disabled: set[str] = set()
    for entry in er.async_get(hass).entities.values():
        if entry.disabled_by is not None:
            disabled.add(entry.entity_id)
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
        if _is_running(hass, entry, loaded) and _is_placeholder(hass.states.get(entry.entity_id)):
            entity["not_provided"] = True
        entities[entry.entity_id] = entity

    states: dict[str, EntityState] = {}
    for state in hass.states.async_all():
        if state.entity_id in disabled:
            continue
        states[state.entity_id] = {
            "entity_id": state.entity_id,
            "state": state.state,
            "attributes": state.attributes,
            "last_changed": state.last_changed,
            "last_updated": state.last_updated,
            "last_reported": state.last_reported,
        }

    devices = _registry_devices(hass)

    areas: dict[str, AreaEntry] = {
        area.id: {"area_id": area.id, "name": area.name}
        for area in ar.async_get(hass).areas.values()
    }

    return {"states": states, "entities": entities, "devices": devices, "areas": areas}
