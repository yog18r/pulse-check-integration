"""Buttons on phone notifications, and what pressing them does.

The Home Assistant companion app (iOS and Android) shows buttons on a
notification sent through a `notify.mobile_app_<phone>` service when the
call's `data` carries an `actions` list. Each button has an `action`
identifier and a `title`. Pressing one fires `mobile_app_notification_action`
on Home Assistant's event bus with that identifier as `action`; the app
does not need to be opened.

Which device a button is about travels in the identifier itself:
`PULSE_CHECK_SNOOZE_DAY:<device id>`. iOS can echo extra `action_data`
and Android echoes the notification's data fields, but each only on its
own platform; the identifier comes back on both, and the companion app
documents no length limit for it. Encoding the device keeps every button
distinct across notifications too, which the app's documentation asks
for because buttons are shared between notifications.

Only instant notifications and reminders about one device get buttons.
Digests and the maintenance summary cover many devices and get none.
Targets that are not companion-app services (notify entities, e-mail,
Telegram) receive the plain message as before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOGGER = logging.getLogger(__name__)

EVENT_NOTIFICATION_ACTION: Final = "mobile_app_notification_action"
MOBILE_APP_PREFIX: Final = "mobile_app_"
ACTION_PREFIX: Final = "PULSE_CHECK_"

# The buttons. The identifier is ACTION_PREFIX + verb + ":" + device id.
MARK_REPLACED: Final = "MARK_REPLACED"
MARK_CHARGED: Final = "MARK_CHARGED"
REMIND_LATER: Final = "REMIND_LATER"
SNOOZE_DAY: Final = "SNOOZE_DAY"

# The service each button calls, with its extra data. "Remind me later"
# calls nothing: reminders already repeat on their own schedule, and
# leaving the record alone keeps that schedule as it was.
SERVICES: Final[dict[str, tuple[str, dict[str, Any]] | None]] = {
    MARK_REPLACED: ("mark_replaced", {}),
    MARK_CHARGED: ("mark_charged", {}),
    SNOOZE_DAY: ("snooze", {"days": 1}),
    REMIND_LATER: None,
}

BATTERY_ISSUES: Final = frozenset({"battery_warning", "battery_critical"})


def is_mobile_app_target(target: str) -> bool:
    """A legacy `notify.mobile_app_<phone>` service, the kind that shows buttons."""
    domain, _, name = target.partition(".")
    return domain == "notify" and name.startswith(MOBILE_APP_PREFIX)


def action_id(verb: str, device_id: str) -> str:
    """The identifier for one button about one device."""
    return f"{ACTION_PREFIX}{verb}:{device_id}"


def parse_action_id(action: str) -> tuple[str, str] | None:
    """`(verb, device id)` from one of our identifiers, or None for anyone else's.

    Device ids may contain a colon themselves (`entity:sensor.remote`),
    so only the first colon separates the verb.
    """
    if not action.startswith(ACTION_PREFIX):
        return None
    verb, _, device_id = action.removeprefix(ACTION_PREFIX).partition(":")
    if verb not in SERVICES or not device_id:
        return None
    return verb, device_id


def notification_actions(
    issue_key: str,
    device_id: str,
    *,
    rechargeable: bool,
    another_reminder: bool,
    titles: Mapping[str, str],
) -> list[dict[str, str]]:
    """The buttons for a message about one issue of one device.

    A low battery offers "Mark replaced" ("Mark charged" for a device set
    as rechargeable) and, when a reminder will follow, "Remind me later".
    Offline and quiet offer "Snooze 1 day". `titles` maps each verb to
    its label in the user's language.
    """
    if issue_key in BATTERY_ISSUES:
        verbs = [MARK_CHARGED if rechargeable else MARK_REPLACED]
        if another_reminder:
            verbs.append(REMIND_LATER)
    else:
        verbs = [SNOOZE_DAY]
    return [{"action": action_id(verb, device_id), "title": titles[verb]} for verb in verbs]


@callback
def is_our_action(event_data: Mapping[str, Any]) -> bool:
    """Event filter: only buttons Pulse Check made, before any task is created."""
    return str(event_data.get("action", "")).startswith(ACTION_PREFIX)


async def async_handle_action(hass: HomeAssistant, event: Event[Any]) -> None:
    """Run the service a pressed button stands for.

    The call goes through the service itself, so a button does exactly
    what the same action in an automation would, and carries the event's
    context (who pressed it) into the logbook.
    """
    parsed = parse_action_id(str(event.data.get("action", "")))
    if parsed is None:
        return
    verb, device_id = parsed
    target = SERVICES[verb]
    if target is None:
        _LOGGER.debug("Remind me later for %s: the reminder schedule stays as it is", device_id)
        return
    service, extra = target
    try:
        await hass.services.async_call(
            DOMAIN,
            service,
            {"device_id": device_id, **extra},
            blocking=True,
            context=event.context,
        )
    except HomeAssistantError as err:
        # Most likely the device was removed after the notification was sent.
        _LOGGER.warning("Notification button %s failed: %s", event.data.get("action"), err)
