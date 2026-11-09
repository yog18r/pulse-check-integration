"""Notifications: once per transition, with reminders and digests.

The rule that keeps this from being noisy: a device is notified about
when it *enters* a state (goes offline, goes quiet, drops to warning or
critical), never on every recompute. Which states each device is in is
remembered in the store, so a restart does not re-notify either.

Two guards keep restarts and hiccups quiet:

- Nothing is evaluated until Home Assistant has finished starting plus a
  grace period (integrations load one after another, and most entities
  are briefly `unavailable` meanwhile). The first evaluation after that is
  a *baseline*: whatever is wrong right then is recorded, not announced.
- An offline or quiet state must persist for a confirmation window before
  it counts as a transition. A missed poll or a Zigbee hiccup that heals
  within the window produces nothing at all. Battery levels do not
  flicker, so battery transitions count at once.
- Offline or quiet only counts for a device that has been seen online at
  least once since Home Assistant started. An integration that takes ten
  minutes to come up after a restart leaves its devices unavailable well
  past the confirmation window; those devices are "not loaded yet", not
  offline, until they have appeared once. What was already known about
  such a device before the restart is kept as it was: a device that was
  offline then is not "resolved" by a restart, and its reminders carry on.
- "Not loaded yet" has a limit, the restart timeout (30 minutes after the
  start by default). A device still not seen working by then counts as
  offline, worded "offline since the restart": it died while Home
  Assistant was off, or its integration never came up.

Per device, a *policy* decides how a notification is delivered:

  instant   straight away, then reminders while it stays unresolved
  daily     collected into the daily digest
  weekly    collected into the weekly digest
  none      never (the event still fires, so automations can act)

The policy comes from the device's settings, or else from the options'
default for that severity (critical -> instant, warning -> weekly).

Every confirmed transition also fires a `pulse_check_transition` event on
Home Assistant's event bus, whatever the policy, for people who prefer
their own automations (see the blueprint in `blueprints/`). Instant
messages and reminders to a companion-app phone carry buttons (mark
replaced, snooze) that act on the device; see `notify_actions.py`.

Digests go out at a fixed time. The store remembers when each kind was
last judged (sent, or found to have nothing to say), so a slot missed
because Home Assistant was off or still starting is caught up once, at
the end of the next startup grace period.

An outage outside Home Assistant (a network controller updating, a server
restarting) can knock dozens of devices over at once. Offline and quiet
messages are therefore limited per integration: a few go out as usual
(three an hour by default), and the rest of that integration's wait an
hour and go out as one message listing those still unresolved. A short
outage ends with nothing more to say. Each integration has its own
allowance, so a UniFi outage does not hold back an ESPHome alert, and
battery messages are never held: they come one device at a time.

Maintenance mode (`pulse_check.maintenance_mode`) silences everything for
a few hours while someone works on the house: migrating a Zigbee
coordinator would otherwise produce a burst of offline and quiet alerts.
Transitions are still tracked and the event still fires; only messages
are held back, and a digest slot inside the window counts as judged. When
the window ends nothing is replayed: one summary lists the instant
problems that appeared during it and are still there, and from then on
everything runs as usual.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CALLBACK_TYPE, CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_utc_time,
    async_track_time_change,
)
from homeassistant.loader import IntegrationNotLoaded, async_get_loaded_integration
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONFIRM_MINUTES,
    CONF_DIGEST_TIME,
    CONF_DIGEST_WEEKDAY,
    CONF_INTEGRATION_LIMIT,
    CONF_NOTIFY_CRITICAL,
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_MAX,
    CONF_RESTART_TIMEOUT_MINUTES,
    CONF_STARTUP_GRACE_MINUTES,
    CONF_WEEKLY_ALL_CLEAR,
    DEFAULT_CONFIRM_MINUTES,
    DEFAULT_DIGEST_TIME,
    DEFAULT_DIGEST_WEEKDAY,
    DEFAULT_INTEGRATION_LIMIT,
    DEFAULT_NOTIFY_CRITICAL,
    DEFAULT_NOTIFY_WARNING,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_REMINDER_MAX,
    DEFAULT_RESTART_TIMEOUT_MINUTES,
    DEFAULT_STARTUP_GRACE_MINUTES,
    DOMAIN,
    EVENT_TRANSITION,
    INTEGRATION_LIMIT_WINDOW,
    WEEKDAYS,
)
from .core.models import as_utc, to_iso
from .core.settings import is_charged
from .core.thresholds import battery_severity
from .messages import Catalog, Messages
from .notify_actions import (
    EVENT_NOTIFICATION_ACTION,
    MARK_CHARGED,
    MARK_REPLACED,
    REMIND_LATER,
    SNOOZE_DAY,
    async_handle_action,
    is_mobile_app_target,
    is_our_action,
    notification_actions,
)
from .storage import stored_rechargeable

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry

    from .coordinator import PulseCheckCoordinator, PulseCheckData
    from .core import CoreConfig, DeviceHealth

_LOGGER = logging.getLogger(__name__)

TITLE = "Pulse Check"

# Button verb -> message key of its label.
ACTION_TITLE_KEYS = {
    MARK_REPLACED: "action_mark_replaced",
    MARK_CHARGED: "action_mark_charged",
    REMIND_LATER: "action_remind_later",
    SNOOZE_DAY: "action_snooze_day",
}

type IssueKey = Literal["offline", "quiet", "not_provided", "battery_critical", "battery_warning"]
type Policy = Literal["instant", "daily", "weekly", "none"]
type DigestKind = Literal["daily", "weekly"]

DIGEST_KINDS: tuple[DigestKind, ...] = ("daily", "weekly")

ISSUE_SEVERITY: dict[str, str] = {
    "offline": "critical",
    "battery_critical": "critical",
    "quiet": "warning",
    "not_provided": "warning",
    "battery_warning": "warning",
}

# Issues that must persist for the confirmation window before they count.
CONFIRMED_ISSUES = frozenset({"offline", "quiet", "not_provided"})


@dataclass(frozen=True, slots=True)
class Issue:
    """One thing wrong with a device, in words."""

    key: IssueKey
    severity: str
    message: str


# Sending: how long one target may take, and how an undelivered message
# is retried before it counts as sent anyway (the repair issue says why).
SEND_TIMEOUT = 30  # seconds
SEND_RETRY = timedelta(minutes=15)
SEND_ATTEMPTS = 4
# What must outlive a reload of the entry (saving the options) but not a
# restart of Home Assistant: when it started, which devices have been seen
# working since, and the per-integration send times.
DATA_RUNTIME = f"{DOMAIN}_notify_runtime"
# Repair issue ids are one of these followed by the notify target.
REPAIR_PREFIXES = ("notify_target_missing_", "notify_failed_")


def _hours_since(moment: datetime | None, now: datetime) -> int:
    if moment is None:
        return 0
    return int((as_utc(now) - as_utc(moment)).total_seconds() // 3600)


def _at(iso: str) -> datetime:
    return as_utc(datetime.fromisoformat(iso))


def last_digest_slot(now: datetime, hour: int, minute: int, weekday: int | None = None) -> datetime:
    """The most recent scheduled digest time at or before `now`, in local time.

    `weekday` (0 = Monday) narrows the daily schedule to the weekly one.
    The arithmetic is on the local wall clock, so a slot is still 09:00
    on the far side of a daylight saving change.
    """
    local = dt_util.as_local(now)
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > local:
        slot -= timedelta(days=1)
    if weekday is not None:
        slot -= timedelta(days=(slot.weekday() - weekday) % 7)
    return slot


def wording(key: str, device: DeviceHealth) -> str:
    """The message key for an issue: a service or lone entity is unavailable, not offline.

    The issue key itself stays "offline", so events and the store keep one name.
    """
    if key == "offline" and device.source != "device":
        return "unavailable"
    return key


def device_issues(
    device: DeviceHealth,
    config: CoreConfig,
    now: datetime,
    text: Catalog,
    integration_name: Callable[[str], str] = str,
) -> dict[str, Issue]:
    """The issues a device currently has, worded by `text`. A snoozed device has none."""
    if device.snoozed_until is not None:
        return {}
    issues: dict[str, Issue] = {}
    name = device.name
    if device.is_offline:
        message = text(f"issue_{wording('offline', device)}", name=name)
        issues["offline"] = Issue("offline", "critical", message)
    elif device.is_quiet:
        hours = _hours_since(device.last_heard, now)
        issues["quiet"] = Issue("quiet", "warning", text("issue_quiet", name=name, hours=hours))
    elif device.is_not_provided:
        integration = integration_name(device.integration)
        message = text("issue_not_provided", name=name, integration=integration)
        issues["not_provided"] = Issue("not_provided", "warning", message)
    battery = device.battery
    if battery is not None:
        severity = battery_severity(battery, config, device.device_id)
        if battery.level is not None:
            level = text("level_percent", level=battery.level)
        else:
            level = text("level_low")
        if severity == "critical":
            message = text("issue_battery_critical", name=name, level=level)
            issues["battery_critical"] = Issue("battery_critical", "critical", message)
        elif severity == "warning":
            message = text("issue_battery_warning", name=name, level=level)
            issues["battery_warning"] = Issue("battery_warning", "warning", message)
    return issues


class Notifier:
    """Watches coordinator updates and sends what the policies allow."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: PulseCheckCoordinator,
        messages: Messages,
    ) -> None:
        """Keep references; nothing happens until `async_setup`."""
        self.hass = hass
        self.messages = messages
        self.entry = entry
        self.coordinator = coordinator
        self.store = coordinator.store
        # Targets whose last send failed or that do not exist, so each
        # failure is logged once rather than on every message.
        self._failing: set[str] = set()
        # One evaluation or digest at a time: each awaits slow notify calls
        # while it changes the stored records.
        self._lock = asyncio.Lock()
        # When evaluation may begin: Home Assistant started + the grace period.
        self.ready_at: datetime | None = None
        # When a device not yet seen working counts as offline after all.
        self.overdue_at: datetime | None = None
        # This run of Home Assistant, shared with the next load of the entry.
        self._runtime: dict[str, Any] = hass.data.setdefault(DATA_RUNTIME, {})
        # True until the first evaluation after `ready_at` has recorded the
        # baseline. A reload records one too, at once: new thresholds would
        # otherwise announce every battery that now falls below them.
        self.baseline_pending = True
        # Devices seen online (not offline) at least once in this run.
        self._seen_online: set[str] = self._runtime.setdefault("seen_online", set())
        # The timer that ends maintenance mode, and the end time it is set for.
        self._maintenance_timer: CALLBACK_TYPE | None = None
        self._maintenance_timer_at: datetime | None = None
        # When each integration's recent offline and quiet messages went out,
        # for the per-integration limit. Kept in memory: after a restart the
        # startup baseline starts afresh anyway.
        self._sent: dict[str, deque[datetime]] = self._runtime.setdefault("sent", {})

    # -- options -------------------------------------------------------------

    @property
    def text(self) -> Catalog:
        """Messages in Home Assistant's language, looked up as they are sent."""
        return self.messages.catalog(self.hass.config.language)

    @property
    def targets(self) -> list[str]:
        """The notify services or entities to send to."""
        return list(self.entry.options.get(CONF_NOTIFY_TARGETS) or [])

    def default_policy(self, severity: str) -> Policy:
        """The options' policy for a severity."""
        if severity == "critical":
            return self.entry.options.get(CONF_NOTIFY_CRITICAL, DEFAULT_NOTIFY_CRITICAL)  # type: ignore[no-any-return]
        return self.entry.options.get(CONF_NOTIFY_WARNING, DEFAULT_NOTIFY_WARNING)  # type: ignore[no-any-return]

    def policy_for(self, device_id: str, severity: str) -> Policy:
        """Per-device policy if set, else the default for the severity."""
        per_device = self.store.device_settings.get(device_id, {}).get("notify_policy")
        if per_device in ("instant", "daily", "weekly", "none"):
            return per_device  # type: ignore[no-any-return]
        return self.default_policy(severity)

    @property
    def reminder_interval(self) -> timedelta:
        """How long an instant issue may stay unresolved before a reminder."""
        days = float(self.entry.options.get(CONF_REMINDER_DAYS, DEFAULT_REMINDER_DAYS))
        return timedelta(days=days)

    @property
    def reminder_max(self) -> int:
        """How many reminders at most, per issue."""
        return int(self.entry.options.get(CONF_REMINDER_MAX, DEFAULT_REMINDER_MAX))

    @property
    def integration_limit(self) -> int:
        """Offline and quiet messages per integration per window; 0 means no limit."""
        return int(self.entry.options.get(CONF_INTEGRATION_LIMIT, DEFAULT_INTEGRATION_LIMIT))

    @property
    def startup_grace(self) -> timedelta:
        """How long after Home Assistant has started before anything is judged."""
        minutes = float(
            self.entry.options.get(CONF_STARTUP_GRACE_MINUTES, DEFAULT_STARTUP_GRACE_MINUTES)
        )
        return timedelta(minutes=minutes)

    @property
    def restart_timeout(self) -> timedelta | None:
        """How long after the start a device may take to come up; None waits forever."""
        minutes = float(
            self.entry.options.get(CONF_RESTART_TIMEOUT_MINUTES, DEFAULT_RESTART_TIMEOUT_MINUTES)
        )
        return timedelta(minutes=minutes) if minutes > 0 else None

    @property
    def confirm_window(self) -> timedelta:
        """How long offline or quiet must persist before it is a transition."""
        minutes = float(self.entry.options.get(CONF_CONFIRM_MINUTES, DEFAULT_CONFIRM_MINUTES))
        return timedelta(minutes=minutes)

    @property
    def digest_time(self) -> tuple[int, int]:
        """Hour and minute of the digests, local time."""
        digest_time = str(self.entry.options.get(CONF_DIGEST_TIME, DEFAULT_DIGEST_TIME))
        hour, minute = (int(part) for part in digest_time.split(":")[:2])
        return hour, minute

    @property
    def digest_weekday(self) -> str:
        """The day the weekly digest goes out, as in `WEEKDAYS`."""
        return str(self.entry.options.get(CONF_DIGEST_WEEKDAY, DEFAULT_DIGEST_WEEKDAY))

    # -- wiring --------------------------------------------------------------

    @callback
    def async_setup(self) -> None:
        """Listen to coordinator updates, the start of HA, and the digest time."""
        self.entry.async_on_unload(self.coordinator.async_add_listener(self._handle_update))
        self._clear_stale_repairs()

        hour, minute = self.digest_time
        self.entry.async_on_unload(
            async_track_time_change(
                self.hass, self._handle_digest_time, hour=hour, minute=minute, second=0
            )
        )
        self._start_digest_record()
        self._schedule_maintenance_end()
        self.entry.async_on_unload(self._cancel_maintenance_timer)
        self.entry.async_on_unload(
            self.hass.bus.async_listen(
                EVENT_NOTIFICATION_ACTION, self._handle_action, event_filter=is_our_action
            )
        )

        if self.hass.state is CoreState.running:
            self._mark_started()
        else:
            self.entry.async_on_unload(
                self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._handle_started)
            )

    @callback
    def _start_digest_record(self) -> None:
        """On the very first run, count the digests as judged up to now.

        Catching up compares the last record with the schedule. Without a
        record, a slot from before Pulse Check was installed would look
        missed and be sent at the end of the first grace period.
        """
        now = to_iso(dt_util.utcnow())
        missing = [kind for kind in DIGEST_KINDS if kind not in self.store.digests]
        for kind in missing:
            self.store.digests[kind] = now
        if missing:
            self.store.async_save()

    @callback
    def _handle_started(self, _event: Event[Any]) -> None:
        self._mark_started()

    @callback
    def _mark_started(self) -> None:
        """Start the grace period, and evaluate once when it ends.

        Timed from when Home Assistant started. A reload of the entry
        (saving the options) keeps that time: it does not wait out a new
        grace period or restart timeout, and devices seen working stay seen.
        Only a restart starts them again.
        """
        now = dt_util.utcnow()
        started: datetime = self._runtime.setdefault("started_at", now)
        # The grace period of this run, fixed when Home Assistant started:
        # raising it in the options afterwards does not start another one.
        first_ready: datetime = self._runtime.setdefault("ready_at", started + self.startup_grace)
        # After a reload the grace period is usually over: the baseline is
        # taken by the first evaluation, which this triggers straight away.
        self.ready_at = max(first_ready, now)
        self.entry.async_on_unload(
            async_call_later(
                self.hass, max(self.ready_at - now, timedelta(0)), self._handle_grace_over
            )
        )
        timeout = self.restart_timeout
        if timeout is not None:
            # Never at or before the baseline (after a start or a reload),
            # which would record the overdue as known instead of announcing them.
            self.overdue_at = max(started + timeout, self.ready_at + timedelta(minutes=1))
            if self.overdue_at > now:
                # Recompute when the time is up, so the overdue are judged then.
                self.entry.async_on_unload(
                    async_call_later(self.hass, self.overdue_at - now, self._handle_restart_timeout)
                )

    @callback
    def _handle_grace_over(self, _now: datetime) -> None:
        """The grace period is over: recompute now, which records the baseline."""
        self.entry.async_create_background_task(
            self.hass, self.coordinator.async_refresh(), "pulse_check baseline"
        )

    @callback
    def _handle_restart_timeout(self, _now: datetime) -> None:
        """Devices still not up count as offline from now: recompute."""
        self.entry.async_create_background_task(
            self.hass, self.coordinator.async_refresh(), "pulse_check restart timeout"
        )

    @callback
    def _handle_update(self) -> None:
        # The maintenance service changes the store, then recomputes.
        self._schedule_maintenance_end()
        self.entry.async_create_background_task(
            self.hass, self.async_process(), "pulse_check notifications"
        )

    @callback
    def _handle_action(self, event: Event[Any]) -> None:
        """A button on one of our phone notifications was pressed."""
        self.entry.async_create_background_task(
            self.hass, async_handle_action(self.hass, event), "pulse_check notification action"
        )

    @callback
    def _schedule_maintenance_end(self) -> None:
        """Keep one timer at the end of the maintenance window, if there is one.

        The timer only triggers a recompute; the summary is sent by the
        processing that follows, which also covers a window that ended while
        Home Assistant was off.
        """
        until = self.store.maintenance_until
        if until == self._maintenance_timer_at:
            return
        self._cancel_maintenance_timer()
        self._maintenance_timer_at = until
        if until is not None and until > dt_util.utcnow():
            self._maintenance_timer = async_track_point_in_utc_time(
                self.hass, self._handle_maintenance_over, until
            )

    @callback
    def _cancel_maintenance_timer(self) -> None:
        if self._maintenance_timer is not None:
            self._maintenance_timer()
            self._maintenance_timer = None
        self._maintenance_timer_at = None

    @callback
    def _handle_maintenance_over(self, _now: datetime) -> None:
        self._maintenance_timer = None
        self.entry.async_create_background_task(
            self.hass, self.coordinator.async_refresh(), "pulse_check maintenance over"
        )

    @callback
    def _handle_digest_time(self, now: datetime) -> None:
        self.entry.async_create_background_task(
            self.hass, self.async_send_due_digests(now), "pulse_check digest"
        )

    def _is_ready(self) -> bool:
        """True once Home Assistant has started and the grace period has passed."""
        return self.ready_at is not None and dt_util.utcnow() >= self.ready_at

    # -- transitions ---------------------------------------------------------

    async def async_process(self) -> None:
        """Compare the latest result with what was last seen; act on the difference.

        Runs after every recompute. Runs never overlap: a second one waits
        for the first, then judges the newest result.
        """
        async with self._lock:
            await self._process()

    async def _process(self) -> None:
        data: PulseCheckData = self.coordinator.data
        now = data.computed_at
        # Learn which devices are up, even during the grace period: a device
        # never seen online in this run cannot have "gone" offline.
        for device in data.devices:
            if not device.is_offline:
                self._seen_online.add(device.device_id)
        if not self._is_ready():
            return
        baseline = self.baseline_pending
        self.baseline_pending = False

        state = self.store.notify
        changed = False
        for device in data.devices:
            stored: dict[str, dict[str, Any]] = state.get(device.device_id, {})
            current = self._issues(device, data.config, now)
            frozen: set[str] = set()
            if device.device_id not in self._seen_online:
                current, frozen = self._not_up_yet(device, current, stored, now)
            changed |= await self._process_device(device, current, stored, now, baseline, frozen)
            if stored:
                state[device.device_id] = stored
            elif device.device_id in state:
                del state[device.device_id]
                changed = True

        seen = {device.device_id for device in data.devices}
        for device_id in list(state):
            if device_id not in seen:
                del state[device_id]
                changed = True

        if changed:
            self.store.async_save()

        await self._after_evaluation(now, baseline)

    async def _after_evaluation(self, now: datetime, baseline: bool) -> None:
        """Messages that do not come from one transition: summaries and catch-ups."""
        if self.store.maintenance and not self.store.in_maintenance(now):
            await self._end_maintenance(now)
        if not self.store.in_maintenance(now):
            await self._send_held(now)
        if baseline:
            await self._catch_up_digests(now)

    def _not_up_yet(
        self,
        device: DeviceHealth,
        current: dict[str, Issue],
        stored: dict[str, dict[str, Any]],
        now: datetime,
    ) -> tuple[dict[str, Issue], set[str]]:
        """The issues of a device not seen working since the start, and those to leave alone.

        Its battery can be judged at once. Offline, quiet and not provided
        mean nothing until it has come up, so new ones wait, while those
        confirmed before the restart stay as they were (still current, or
        frozen when they no longer apply). Past the restart timeout it has
        had its chance: it counts as offline, "since the restart".
        """
        if self.overdue_at is not None and as_utc(now) >= self.overdue_at:
            issue = current.get("offline")
            # Worded "since the restart" until announced; one already known
            # (from before the restart, or announced since) keeps the usual words.
            known = stored.get("offline", {}).get("confirmed", False)
            if issue is not None and not known:
                key = f"issue_{wording('offline', device)}_restart"
                message = self.text(key, name=device.name)
                current = {**current, "offline": Issue("offline", issue.severity, message)}
            return current, set()
        kept = {
            key for key in CONFIRMED_ISSUES if key in stored and stored[key].get("confirmed", True)
        }
        current = {k: v for k, v in current.items() if k not in CONFIRMED_ISSUES or k in kept}
        return current, kept - current.keys()

    async def _process_device(
        self,
        device: DeviceHealth,
        current: dict[str, Issue],
        stored: dict[str, dict[str, Any]],
        now: datetime,
        baseline: bool,
        frozen: set[str] | None = None,
    ) -> bool:
        """Update one device's records in place. Returns True when they changed.

        Records named in `frozen` are left exactly as they are.
        """
        changed = False
        for key, issue in current.items():
            record = stored.get(key)
            if record is None:
                # First sighting. On the baseline it is simply recorded;
                # otherwise it waits for confirmation (offline, quiet) or
                # counts straight away (battery).
                record = {"since": to_iso(now), "notified_at": None, "reminders": 0}
                stored[key] = record
                changed = True
                record["confirmed"] = baseline or key not in CONFIRMED_ISSUES
                if record["confirmed"] and not baseline:
                    await self._announce(device, issue, record, now)
            elif not record.get("confirmed", True):
                if as_utc(now) - _at(record["since"]) >= self.confirm_window:
                    record["confirmed"] = True
                    changed = True
                    await self._announce(device, issue, record, now)
            else:
                changed |= await self._maybe_remind(device, issue, record, now)

        for key in list(stored):
            if key in current or (frozen and key in frozen):
                continue
            record = stored.pop(key)
            changed = True
            if not record.get("confirmed", True):
                continue  # healed within the window: it never happened
            severity = ISSUE_SEVERITY.get(key, "warning")
            message = self.text(f"resolved_{wording(key, device)}", name=device.name)
            resolved = Issue(key, severity, message)  # type: ignore[arg-type]
            policy = self.policy_for(device.device_id, severity)
            self._fire(device, resolved, "resolved", policy)
        return changed

    async def _announce(
        self, device: DeviceHealth, issue: Issue, record: dict[str, Any], now: datetime
    ) -> None:
        """A confirmed transition: fire the event and notify per policy."""
        policy = self.policy_for(device.device_id, issue.severity)
        self._fire(device, issue, "entered", policy)
        # In maintenance mode `notified_at` stays empty: the summary at the
        # end of the window picks the issue up from there.
        if policy == "instant" and not self.store.in_maintenance(now):
            if self._hold_back(device, issue, record, now):
                return
            actions = self._actions(device, issue, reminders_sent=0)
            if await self._deliver(issue.message, actions, record, now):
                record["notified_at"] = to_iso(now)

    async def _maybe_remind(
        self, device: DeviceHealth, issue: Issue, record: dict[str, Any], now: datetime
    ) -> bool:
        """Send a reminder for an unresolved instant issue when it is due."""
        if self.policy_for(device.device_id, issue.severity) != "instant":
            return False
        if self.store.in_maintenance(now):
            return False  # due reminders wait for the end of the window
        if "held" in record:
            return False  # waiting to go out with its integration's others
        retry_at = record.get("retry_at")
        if retry_at is not None:
            if as_utc(now) < _at(retry_at):
                return False
            if record.get("notified_at") is None:
                # The first message never arrived: try it again.
                actions = self._actions(device, issue, reminders_sent=0)
                if await self._deliver(issue.message, actions, record, now):
                    record["notified_at"] = to_iso(now)
                return True
        if record.get("reminders", 0) >= self.reminder_max:
            return False
        last = record.get("notified_at") or record.get("since")
        last_at = _at(last) if last else now
        if as_utc(now) - last_at < self.reminder_interval:
            return False
        if self._hold_back(device, issue, record, now):
            return True  # the record now waits with its integration's others
        days = (as_utc(now) - _at(record["since"])).days
        reminders = record.get("reminders", 0) + 1
        delivered = await self._deliver(
            self.text("reminder", count=days, message=issue.message),
            self._actions(device, issue, reminders_sent=reminders),
            record,
            now,
        )
        if delivered:
            record["notified_at"] = to_iso(now)
            record["reminders"] = reminders
        return True

    def _actions(
        self, device: DeviceHealth, issue: Issue, reminders_sent: int
    ) -> list[dict[str, str]]:
        """Companion-app buttons for a message about one issue.

        "Remind me later" is offered only when a reminder will really
        follow: reminders are on and this message is not the last one.
        """
        settings = self.store.device_settings.get(device.device_id, {})
        text = self.text
        return notification_actions(
            issue.key,
            device.device_id,
            rechargeable=is_charged(device, stored_rechargeable(settings)),
            another_reminder=reminders_sent < self.reminder_max,
            titles={verb: text(key) for verb, key in ACTION_TITLE_KEYS.items()},
        )

    @callback
    def _fire(
        self, device: DeviceHealth, issue: Issue, kind: Literal["entered", "resolved"], policy: str
    ) -> None:
        """Announce a transition on the event bus."""
        self.hass.bus.async_fire(
            EVENT_TRANSITION,
            {
                "device_id": device.device_id,
                "name": device.name,
                "area": device.area,
                "integration": device.integration,
                "issue": issue.key,
                "kind": kind,
                "severity": issue.severity,
                "message": issue.message,
                "policy": policy,
                "level": device.battery.level if device.battery else None,
                "maintenance": self.store.in_maintenance(dt_util.utcnow()),
            },
        )

    def _issues(self, device: DeviceHealth, config: CoreConfig, now: datetime) -> dict[str, Issue]:
        """The device's current issues, worded in Home Assistant's language."""
        return device_issues(device, config, now, self.text, self._integration_name)

    # -- the per-integration limit -------------------------------------------

    def _hold_back(
        self, device: DeviceHealth, issue: Issue, record: dict[str, Any], now: datetime
    ) -> bool:
        """Apply the per-integration limit to one message. True means held, not sent.

        Only offline and quiet count. Within the window an integration may
        send `integration_limit` of them; after that, and while any of its
        messages are already waiting, the rest are marked `held` on their
        record and go out together from `_send_held`.
        """
        limit = self.integration_limit
        if limit <= 0 or issue.key not in CONFIRMED_ISSUES:
            return False
        integration = device.integration
        sent = self._sent.setdefault(integration, deque())
        while sent and as_utc(now) - sent[0] >= INTEGRATION_LIMIT_WINDOW:
            sent.popleft()
        if len(sent) < limit and not self._has_held(integration):
            sent.append(as_utc(now))
            return False
        record.setdefault("held", {"at": to_iso(now), "integration": integration})
        return True

    def _has_held(self, integration: str) -> bool:
        """True while any message of this integration waits to go out."""
        return any(
            record.get("held", {}).get("integration") == integration
            for records in self.store.notify.values()
            for record in records.values()
        )

    async def _send_held(self, now: datetime) -> None:
        """Send each integration's held messages as one, a window after the first.

        A held record disappears when its device recovers, so only what is
        still wrong is listed, and a short outage ends with no message at
        all. Each listed issue counts as notified from here, so its
        reminders run from this message; a held reminder counts as sent.
        """
        if not any(
            "held" in record
            for records in self.store.notify.values()
            for record in records.values()
        ):
            return
        data: PulseCheckData = self.coordinator.data
        groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for device in data.devices:
            stored = self.store.notify.get(device.device_id, {})
            if not any("held" in record for record in stored.values()):
                continue
            for key, issue in self._issues(device, data.config, now).items():
                record = stored.get(key)
                if record is not None and "held" in record:
                    integration = record["held"]["integration"]
                    groups.setdefault(integration, []).append((issue.message, record))

        changed = False
        for integration, items in sorted(groups.items()):
            changed |= await self._send_held_group(integration, items, now)
        if changed:
            self.store.async_save()

    async def _send_held_group(
        self, integration: str, items: list[tuple[str, dict[str, Any]]], now: datetime
    ) -> bool:
        """One integration's held messages as one, when due. True when records changed.

        A failed send is retried like any other message (`_deliver`): after
        `SEND_RETRY`, `SEND_ATTEMPTS` times in all, then counted as sent.
        """
        first = min(_at(record["held"]["at"]) for _, record in items)
        if as_utc(now) - first < INTEGRATION_LIMIT_WINDOW:
            return False
        retries = [
            record["held"]["retry_at"] for _, record in items if "retry_at" in record["held"]
        ]
        if retries and as_utc(now) < max(_at(at) for at in retries):
            return False  # the last attempt failed; wait before the next
        heading = self.text(
            "integration_held", count=len(items), integration=self._integration_name(integration)
        )
        body = "\n".join(f"- {message}" for message, _ in sorted(items, key=lambda i: i[0]))
        if not await self._send(f"{heading}\n{body}"):
            attempts = max(record["held"].get("attempts", 0) for _, record in items) + 1
            if attempts < SEND_ATTEMPTS:
                for _, record in items:
                    record["held"]["attempts"] = attempts
                    record["held"]["retry_at"] = to_iso(as_utc(now) + SEND_RETRY)
                return True  # still held, tried again later
            _LOGGER.warning("Giving up on a held message after %d attempts", attempts)
        for _, record in items:
            del record["held"]
            record.pop("retry_at", None)
            record.pop("attempts", None)
            if record.get("notified_at"):
                record["reminders"] = record.get("reminders", 0) + 1
            record["notified_at"] = to_iso(now)
        return True

    def _integration_name(self, domain: str) -> str:
        """The integration's own name ("UniFi Network"), or its domain."""
        try:
            return async_get_loaded_integration(self.hass, domain).name
        except IntegrationNotLoaded:
            return domain

    # -- maintenance mode ----------------------------------------------------

    async def _end_maintenance(self, now: datetime) -> None:
        """The window is over: one summary of what appeared during it and remains.

        Only instant problems are listed: a daily or weekly one goes into
        its next digest anyway, and `none` means never. An issue counts as
        new unless it was already confirmed when the window began and has
        been present ever since. Each listed issue counts as notified now,
        so its reminders run from the summary.
        """
        window = self.store.maintenance
        started_at = _at(window["started_at"])
        known: dict[str, list[str]] = window.get("known", {})
        data: PulseCheckData = self.coordinator.data
        lines: list[str] = []
        listed: list[dict[str, Any]] = []
        for device in data.devices:
            stored = self.store.notify.get(device.device_id, {})
            for key, issue in self._issues(device, data.config, now).items():
                record = stored.get(key)
                if record is None or not record.get("confirmed", True):
                    continue
                if record.get("notified_at") is not None:
                    continue  # already announced, after the window closed
                if key in known.get(device.device_id, []) and _at(record["since"]) <= started_at:
                    continue  # there before the work began
                if self.policy_for(device.device_id, issue.severity) != "instant":
                    continue
                lines.append(issue.message)
                listed.append(record)
                record.pop("held", None)  # announced here, not again later
        self.store.clear_maintenance()
        _LOGGER.debug("Maintenance mode over; %d new problems", len(lines))
        if lines:
            body = "\n".join(f"- {line}" for line in lines)
            if await self._send(f"{self.text('maintenance_summary')}\n{body}"):
                for record in listed:
                    record["notified_at"] = to_iso(now)
                    record.pop("retry_at", None)
                    record.pop("attempts", None)
            else:
                # Each problem is then retried on its own, like any message
                # that did not get through (see `_maybe_remind`).
                for record in listed:
                    record["attempts"] = 1
                    record["retry_at"] = to_iso(as_utc(now) + SEND_RETRY)
            # Written after the send: the save `clear_maintenance` scheduled
            # may already have run.
            self.store.async_save()

    # -- digests -------------------------------------------------------------

    async def async_send_due_digests(self, now: datetime) -> None:
        """At the digest time: the daily digest every day, the weekly one on its day."""
        async with self._lock:
            await self.async_send_digest("daily", now)
            if WEEKDAYS[dt_util.as_local(now).weekday()] == self.digest_weekday:
                await self.async_send_digest("weekly", now)

    def _last_slot(self, kind: DigestKind, now: datetime) -> datetime:
        """When this kind of digest was last due, by the current schedule."""
        hour, minute = self.digest_time
        weekday = WEEKDAYS.index(self.digest_weekday) if kind == "weekly" else None
        return last_digest_slot(now, hour, minute, weekday)

    async def _catch_up_digests(self, now: datetime) -> None:
        """Send, once, any digest whose slot passed while nobody judged it.

        Runs with the baseline at the end of the grace period: a slot that
        fell while Home Assistant was off, or still starting, has not been
        judged since. One message per kind with today's content, however
        many slots were missed.
        """
        for kind in DIGEST_KINDS:
            last = self.store.digests.get(kind)
            if last is not None and _at(last) < self._last_slot(kind, now):
                _LOGGER.debug("Catching up the %s digest last judged at %s", kind, last)
                await self.async_send_digest(kind, now)

    async def async_send_digest(self, kind: DigestKind, now: datetime) -> None:
        """One message listing every confirmed, unresolved issue on that policy.

        The slot counts as judged whether or not there was anything to say,
        so catching up after a restart never repeats it.
        """
        if not self._is_ready():
            return
        data: PulseCheckData = self.coordinator.data
        lines: list[str] = []
        for device in data.devices:
            stored = self.store.notify.get(device.device_id, {})
            for key, issue in self._issues(device, data.config, now).items():
                if not stored.get(key, {}).get("confirmed", False):
                    continue
                if self.policy_for(device.device_id, issue.severity) == kind:
                    lines.append(issue.message)
        all_clear = kind == "weekly" and bool(self.entry.options.get(CONF_WEEKLY_ALL_CLEAR, False))
        if self.store.in_maintenance(now):
            _LOGGER.debug("Skipping the %s digest: maintenance mode", kind)
        elif lines or all_clear:
            heading = self.text(f"digest_{kind}")
            body = (
                "\n".join(f"- {line}" for line in lines) if lines else self.text("digest_all_clear")
            )
            await self._send(f"{heading}\n{body}")
        self.store.digests[kind] = to_iso(now)
        self.store.async_save()

    # -- sending -------------------------------------------------------------

    async def _deliver(
        self,
        message: str,
        actions: list[dict[str, str]] | None,
        record: dict[str, Any],
        now: datetime,
    ) -> bool:
        """Send a message about one record. True when it counts as sent.

        When no target accepts it, the record gets a `retry_at` and the
        message is tried again then, `SEND_ATTEMPTS` times in all. After
        that it counts as sent anyway, so reminders follow their schedule;
        the repair issue raised by `_send` tells the user why nothing came.
        """
        if await self._send(message, actions):
            record.pop("retry_at", None)
            record.pop("attempts", None)
            return True
        attempts = record.get("attempts", 0) + 1
        if attempts >= SEND_ATTEMPTS:
            _LOGGER.warning("Giving up on a message after %d attempts: %s", attempts, message)
            record.pop("retry_at", None)
            record.pop("attempts", None)
            return True
        record["attempts"] = attempts
        record["retry_at"] = to_iso(as_utc(now) + SEND_RETRY)
        return False

    async def _send(self, message: str, actions: list[dict[str, str]] | None = None) -> bool:
        """Deliver to every target: a legacy `notify.<name>` service or a notify entity.

        `actions` become buttons for companion-app targets only; every
        other target gets the title and message alone, as it always has.
        True when at least one target accepted the message, or when there
        are no targets (notifications are off, nothing to retry). A target
        that does not exist or fails gets a repair issue, removed again
        once it works.
        """
        targets = self.targets
        if not targets:
            return True
        delivered = False
        for target in targets:
            domain, _, name = target.partition(".")
            try:
                async with asyncio.timeout(SEND_TIMEOUT):
                    if domain == "notify" and self.hass.services.has_service("notify", name):
                        data: dict[str, Any] = {"title": TITLE, "message": message}
                        if actions and is_mobile_app_target(target):
                            data["data"] = {"actions": actions}
                        await self.hass.services.async_call("notify", name, data, blocking=True)
                    elif domain == "notify" and self.hass.states.get(target) is not None:
                        await self.hass.services.async_call(
                            "notify",
                            "send_message",
                            {"entity_id": target, "title": TITLE, "message": message},
                            blocking=True,
                        )
                    else:
                        self._target_failed(target, "notify_target_missing", None)
                        continue
            except Exception as err:
                self._target_failed(target, "notify_failed", err)
                continue
            delivered = True
            self._target_works(target)
        return delivered

    @callback
    def _target_failed(self, target: str, issue: str, err: Exception | None) -> None:
        """Log a failing target once and raise a repair issue for it."""
        if target not in self._failing:
            self._failing.add(target)
            if err is None:
                _LOGGER.warning("Notify target %s does not exist; skipping it", target)
            else:
                _LOGGER.warning("Sending to %s failed", target, exc_info=err)
        other = "notify_failed" if issue == "notify_target_missing" else "notify_target_missing"
        ir.async_delete_issue(self.hass, DOMAIN, f"{other}_{target}")
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{issue}_{target}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=issue,
            translation_placeholders={
                "target": target,
                # A timeout has no message of its own; its name says enough.
                "error": (str(err) or type(err).__name__) if err is not None else "",
            },
        )

    @callback
    def _clear_stale_repairs(self) -> None:
        """Remove repair issues for targets no longer in the options.

        Taking a broken target out of the options is a fix too, and the
        issue says it goes away once resolved.
        """
        configured = set(self.targets)
        registry = ir.async_get(self.hass)
        for domain, issue_id in list(registry.issues):
            if domain != DOMAIN:
                continue
            for prefix in REPAIR_PREFIXES:
                if issue_id.startswith(prefix) and issue_id[len(prefix) :] not in configured:
                    ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @callback
    def _target_works(self, target: str) -> None:
        """A target accepted a message: clear what `_target_failed` raised."""
        if target in self._failing:
            self._failing.discard(target)
            _LOGGER.info("Notify target %s works again", target)
        for issue in ("notify_target_missing", "notify_failed"):
            ir.async_delete_issue(self.hass, DOMAIN, f"{issue}_{target}")
