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
  offline, until they have appeared once.

Per device, a *policy* decides how a notification is delivered:

  instant   straight away, then reminders while it stays unresolved
  daily     collected into the daily digest
  weekly    collected into the weekly digest
  none      never (the event still fires, so automations can act)

The policy comes from the device's settings, or else from the options'
default for that severity (critical -> instant, warning -> weekly).

Every confirmed transition also fires a `pulse_check_transition` event on
Home Assistant's event bus, whatever the policy, for people who prefer
their own automations (see the blueprint in `blueprints/`).

Digests go out at a fixed time. The store remembers when each kind was
last judged (sent, or found to have nothing to say), so a slot missed
because Home Assistant was off or still starting is caught up once, at
the end of the next startup grace period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONFIRM_MINUTES,
    CONF_DIGEST_TIME,
    CONF_DIGEST_WEEKDAY,
    CONF_NOTIFY_CRITICAL,
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_MAX,
    CONF_STARTUP_GRACE_MINUTES,
    CONF_WEEKLY_ALL_CLEAR,
    DEFAULT_CONFIRM_MINUTES,
    DEFAULT_DIGEST_TIME,
    DEFAULT_DIGEST_WEEKDAY,
    DEFAULT_NOTIFY_CRITICAL,
    DEFAULT_NOTIFY_WARNING,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_REMINDER_MAX,
    DEFAULT_STARTUP_GRACE_MINUTES,
    EVENT_TRANSITION,
    WEEKDAYS,
)
from .core.models import as_utc, to_iso
from .core.thresholds import battery_severity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import PulseCheckCoordinator, PulseCheckData
    from .core import CoreConfig, DeviceHealth

_LOGGER = logging.getLogger(__name__)

TITLE = "Pulse Check"

type IssueKey = Literal["offline", "quiet", "battery_critical", "battery_warning"]
type Policy = Literal["instant", "daily", "weekly", "none"]
type DigestKind = Literal["daily", "weekly"]

DIGEST_KINDS: tuple[DigestKind, ...] = ("daily", "weekly")

ISSUE_SEVERITY: dict[str, str] = {
    "offline": "critical",
    "battery_critical": "critical",
    "quiet": "warning",
    "battery_warning": "warning",
}

# Issues that must persist for the confirmation window before they count.
CONFIRMED_ISSUES = frozenset({"offline", "quiet"})


@dataclass(frozen=True, slots=True)
class Issue:
    """One thing wrong with a device, in words."""

    key: IssueKey
    severity: str
    message: str


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


def device_issues(device: DeviceHealth, config: CoreConfig, now: datetime) -> dict[str, Issue]:
    """The issues a device currently has. A snoozed device has none."""
    if device.snoozed_until is not None:
        return {}
    issues: dict[str, Issue] = {}
    name = device.name
    if device.is_offline:
        issues["offline"] = Issue("offline", "critical", f"{name}: offline")
    elif device.is_quiet:
        hours = _hours_since(device.last_heard, now)
        issues["quiet"] = Issue("quiet", "warning", f"{name}: not heard from for {hours} h")
    battery = device.battery
    if battery is not None:
        severity = battery_severity(battery, config)
        level = f"{battery.level} %" if battery.level is not None else "reports low"
        if severity == "critical":
            issues["battery_critical"] = Issue(
                "battery_critical", "critical", f"{name}: battery critical ({level})"
            )
        elif severity == "warning":
            issues["battery_warning"] = Issue(
                "battery_warning", "warning", f"{name}: battery low ({level})"
            )
    return issues


class Notifier:
    """Watches coordinator updates and sends what the policies allow."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator: PulseCheckCoordinator
    ) -> None:
        """Keep references; nothing happens until `async_setup`."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.store = coordinator.store
        self._missing_targets: set[str] = set()
        # When evaluation may begin: Home Assistant started + the grace period.
        self.ready_at: datetime | None = None
        # True until the first evaluation after `ready_at` has recorded the baseline.
        self.baseline_pending = True
        # Devices seen online (not offline) at least once in this run.
        self._seen_online: set[str] = set()

    # -- options -------------------------------------------------------------

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
    def startup_grace(self) -> timedelta:
        """How long after Home Assistant has started before anything is judged."""
        minutes = float(
            self.entry.options.get(CONF_STARTUP_GRACE_MINUTES, DEFAULT_STARTUP_GRACE_MINUTES)
        )
        return timedelta(minutes=minutes)

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

        hour, minute = self.digest_time
        self.entry.async_on_unload(
            async_track_time_change(
                self.hass, self._handle_digest_time, hour=hour, minute=minute, second=0
            )
        )
        self._start_digest_record()

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
        """Start the grace period, and evaluate once when it ends."""
        self.ready_at = dt_util.utcnow() + self.startup_grace
        self.entry.async_on_unload(
            async_call_later(self.hass, self.startup_grace, self._handle_grace_over)
        )

    @callback
    def _handle_grace_over(self, _now: datetime) -> None:
        """The grace period is over: recompute now, which records the baseline."""
        self.entry.async_create_background_task(
            self.hass, self.coordinator.async_refresh(), "pulse_check baseline"
        )

    @callback
    def _handle_update(self) -> None:
        self.entry.async_create_background_task(
            self.hass, self.async_process(), "pulse_check notifications"
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
        """Compare the latest result with what was last seen; act on the difference."""
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
            current = device_issues(device, data.config, now)
            if device.device_id not in self._seen_online:
                # Not loaded yet: its battery can still be judged, but
                # offline and quiet mean nothing until it has come up once.
                current = {k: v for k, v in current.items() if k not in CONFIRMED_ISSUES}
            changed |= await self._process_device(device, current, stored, now, baseline)
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

        if baseline:
            await self._catch_up_digests(now)

    async def _process_device(
        self,
        device: DeviceHealth,
        current: dict[str, Issue],
        stored: dict[str, dict[str, Any]],
        now: datetime,
        baseline: bool,
    ) -> bool:
        """Update one device's records in place. Returns True when they changed."""
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
            if key in current:
                continue
            record = stored.pop(key)
            changed = True
            if not record.get("confirmed", True):
                continue  # healed within the window: it never happened
            severity = ISSUE_SEVERITY.get(key, "warning")
            label = key.replace("_", " ")
            resolved = Issue(key, severity, f"{device.name}: {label} resolved")  # type: ignore[arg-type]
            policy = self.policy_for(device.device_id, severity)
            self._fire(device, resolved, "resolved", policy)
        return changed

    async def _announce(
        self, device: DeviceHealth, issue: Issue, record: dict[str, Any], now: datetime
    ) -> None:
        """A confirmed transition: fire the event and notify per policy."""
        policy = self.policy_for(device.device_id, issue.severity)
        self._fire(device, issue, "entered", policy)
        if policy == "instant":
            await self._send(issue.message)
            record["notified_at"] = to_iso(now)

    async def _maybe_remind(
        self, device: DeviceHealth, issue: Issue, record: dict[str, Any], now: datetime
    ) -> bool:
        """Send a reminder for an unresolved instant issue when it is due."""
        if self.policy_for(device.device_id, issue.severity) != "instant":
            return False
        if record.get("reminders", 0) >= self.reminder_max:
            return False
        last = record.get("notified_at") or record.get("since")
        last_at = _at(last) if last else now
        if as_utc(now) - last_at < self.reminder_interval:
            return False
        days = (as_utc(now) - _at(record["since"])).days
        await self._send(f"Still unresolved after {days} days. {issue.message}")
        record["notified_at"] = to_iso(now)
        record["reminders"] = record.get("reminders", 0) + 1
        return True

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
            },
        )

    # -- digests -------------------------------------------------------------

    async def async_send_due_digests(self, now: datetime) -> None:
        """At the digest time: the daily digest every day, the weekly one on its day."""
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
            for key, issue in device_issues(device, data.config, now).items():
                if not stored.get(key, {}).get("confirmed", False):
                    continue
                if self.policy_for(device.device_id, issue.severity) == kind:
                    lines.append(issue.message)
        all_clear = kind == "weekly" and bool(self.entry.options.get(CONF_WEEKLY_ALL_CLEAR, False))
        if lines or all_clear:
            heading = f"{TITLE} {kind} digest"
            body = "\n".join(f"- {line}" for line in lines) if lines else "All devices OK."
            await self._send(f"{heading}\n{body}")
        self.store.digests[kind] = to_iso(now)
        self.store.async_save()

    # -- sending -------------------------------------------------------------

    async def _send(self, message: str) -> None:
        """Deliver to every target: a legacy `notify.<name>` service or a notify entity."""
        for target in self.targets:
            domain, _, name = target.partition(".")
            try:
                if domain == "notify" and self.hass.services.has_service("notify", name):
                    await self.hass.services.async_call(
                        "notify", name, {"title": TITLE, "message": message}, blocking=True
                    )
                elif domain == "notify" and self.hass.states.get(target) is not None:
                    await self.hass.services.async_call(
                        "notify",
                        "send_message",
                        {"entity_id": target, "title": TITLE, "message": message},
                        blocking=True,
                    )
                elif target not in self._missing_targets:
                    self._missing_targets.add(target)
                    _LOGGER.warning("Notify target %s does not exist; skipping it", target)
            except Exception:
                _LOGGER.warning("Sending to %s failed", target, exc_info=True)
