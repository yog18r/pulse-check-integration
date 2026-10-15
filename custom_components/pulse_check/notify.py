"""Notifications: once per transition, with reminders and digests.

The rule that keeps this from being noisy: a device is notified about
when it *enters* a state (goes offline, goes quiet, drops to warning or
critical), never on every recompute. Which states each device is in is
remembered in the store, so a restart does not re-notify either.

Per device, a *policy* decides how the notification is delivered:

  instant   straight away, then reminders while it stays unresolved
  daily     collected into the daily digest
  weekly    collected into the weekly digest
  none      never (the event still fires, so automations can act)

The policy comes from the device's settings, or else from the options'
default for that severity (critical -> instant, warning -> weekly).

Every transition also fires a `pulse_check_transition` event on Home
Assistant's event bus, whatever the policy, for people who prefer their
own automations (see the blueprint in `blueprints/`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DIGEST_TIME,
    CONF_DIGEST_WEEKDAY,
    CONF_NOTIFY_CRITICAL,
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_MAX,
    CONF_WEEKLY_ALL_CLEAR,
    DEFAULT_DIGEST_TIME,
    DEFAULT_DIGEST_WEEKDAY,
    DEFAULT_NOTIFY_CRITICAL,
    DEFAULT_NOTIFY_WARNING,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_REMINDER_MAX,
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

ISSUE_SEVERITY: dict[str, str] = {
    "offline": "critical",
    "battery_critical": "critical",
    "quiet": "warning",
    "battery_warning": "warning",
}


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
        return timedelta(
            days=float(self.entry.options.get(CONF_REMINDER_DAYS, DEFAULT_REMINDER_DAYS))
        )

    @property
    def reminder_max(self) -> int:
        """How many reminders at most, per issue."""
        return int(self.entry.options.get(CONF_REMINDER_MAX, DEFAULT_REMINDER_MAX))

    # -- wiring --------------------------------------------------------------

    @callback
    def async_setup(self) -> None:
        """Listen to coordinator updates and schedule the digest time."""
        self.entry.async_on_unload(self.coordinator.async_add_listener(self._handle_update))
        hour, minute, _ = (
            int(part)
            for part in str(self.entry.options.get(CONF_DIGEST_TIME, DEFAULT_DIGEST_TIME)).split(
                ":"
            )
        )
        self.entry.async_on_unload(
            async_track_time_change(
                self.hass, self._handle_digest_time, hour=hour, minute=minute, second=0
            )
        )
        # The first update already happened before we subscribed.
        self._handle_update()

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

    # -- transitions ---------------------------------------------------------

    async def async_process(self) -> None:
        """Compare the latest result with what was last seen; act on the difference."""
        data: PulseCheckData = self.coordinator.data
        now = data.computed_at
        state = self.store.notify
        changed = False
        seen_devices: set[str] = set()

        for device in data.devices:
            seen_devices.add(device.device_id)
            current = device_issues(device, data.config, now)
            stored: dict[str, dict[str, Any]] = state.get(device.device_id, {})

            for key, issue in current.items():
                if key in stored:
                    changed |= await self._maybe_remind(device, issue, stored[key], now)
                    continue
                policy = self.policy_for(device.device_id, issue.severity)
                self._fire(device, issue, "entered", policy)
                record: dict[str, Any] = {"since": to_iso(now), "notified_at": None, "reminders": 0}
                if policy == "instant":
                    await self._send(issue.message)
                    record["notified_at"] = to_iso(now)
                stored[key] = record
                changed = True

            for key in list(stored):
                if key in current:
                    continue
                severity = ISSUE_SEVERITY.get(key, "warning")
                resolved = Issue(key, severity, f"{device.name}: {key.replace('_', ' ')} resolved")  # type: ignore[arg-type]
                self._fire(
                    device, resolved, "resolved", self.policy_for(device.device_id, severity)
                )
                del stored[key]
                changed = True

            if stored:
                state[device.device_id] = stored
            elif device.device_id in state:
                del state[device.device_id]
                changed = True

        for device_id in list(state):
            if device_id not in seen_devices:
                del state[device_id]
                changed = True

        if changed:
            self.store.async_save()

    async def _maybe_remind(
        self, device: DeviceHealth, issue: Issue, record: dict[str, Any], now: datetime
    ) -> bool:
        """Send a reminder for an unresolved instant issue when it is due."""
        if self.policy_for(device.device_id, issue.severity) != "instant":
            return False
        if record.get("reminders", 0) >= self.reminder_max:
            return False
        last = record.get("notified_at") or record.get("since")
        last_at = as_utc(datetime.fromisoformat(last)) if last else now
        if as_utc(now) - last_at < self.reminder_interval:
            return False
        days = (as_utc(now) - as_utc(datetime.fromisoformat(record["since"]))).days
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
        weekday = str(self.entry.options.get(CONF_DIGEST_WEEKDAY, DEFAULT_DIGEST_WEEKDAY))
        if WEEKDAYS[dt_util.as_local(now).weekday()] == weekday:
            await self.async_send_digest("weekly", now)

    async def async_send_digest(self, kind: DigestKind, now: datetime) -> None:
        """One message listing every unresolved issue on that policy."""
        data: PulseCheckData = self.coordinator.data
        lines: list[str] = []
        for device in data.devices:
            for issue in device_issues(device, data.config, now).values():
                if self.policy_for(device.device_id, issue.severity) == kind:
                    lines.append(issue.message)
        all_clear = kind == "weekly" and bool(self.entry.options.get(CONF_WEEKLY_ALL_CLEAR, False))
        if not lines and not all_clear:
            return
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
