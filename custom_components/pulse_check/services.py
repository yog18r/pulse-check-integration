"""The integration's services (actions in the UI).

A service is something a user or an automation can call:
`pulse_check.snooze`, `pulse_check.set_device_settings` and so on. They
are registered once, at integration setup, and look up the running
config entry when called. `services.yaml` describes their fields for the
UI; `strings.json` holds the human-readable names.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import probatio
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service import async_register_admin_service, verify_domain_control
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MAINTENANCE_HOURS,
    DATA_COORDINATOR,
    DEFAULT_MAINTENANCE_HOURS,
    DOMAIN,
    MAX_BATTERY_COUNT,
    MAX_MAINTENANCE_HOURS,
    MAX_QUIET_HOURS,
    MAX_SNOOZE_DAYS,
    NOTIFY_POLICIES,
)
from .core.charging import new_mark
from .core.group import ORPHAN_PREFIX
from .core.models import SNOOZED_INDEFINITELY
from .options import levels_clash
from .ping import async_ask_device

if TYPE_CHECKING:
    from .coordinator import PulseCheckCoordinator

SERVICE_SNOOZE = "snooze"
SERVICE_UNSNOOZE = "unsnooze"
SERVICE_SET_DEVICE_SETTINGS = "set_device_settings"
SERVICE_MARK_REPLACED = "mark_replaced"
SERVICE_MARK_CHARGED = "mark_charged"
SERVICE_UNDO_MARK = "undo_mark"
SERVICE_REFRESH = "refresh"
SERVICE_MAINTENANCE_MODE = "maintenance_mode"
SERVICE_PING = "ping"

ATTR_DEVICE_ID = "device_id"
ATTR_DAYS = "days"
ATTR_UNTIL = "until"
ATTR_BATTERY_TYPE = "battery_type"
ATTR_HOURS = "hours"
ATTR_INDEFINITELY = "indefinitely"

DEFAULT_SNOOZE_DAYS = 7


# Longest name, area or battery type a service call may set.
MAX_TEXT_LENGTH = 100


def _text_or_clear(value: object) -> str | None:
    """A text setting; empty text means "clear it".

    A number is taken as its text (YAML reads a battery type of 2032 as
    one); anything else, such as a list or a mapping, is refused.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise probatio.Invalid("expected text")
    text = str(value).strip()
    if len(text) > MAX_TEXT_LENGTH:
        raise probatio.Invalid(f"longer than {MAX_TEXT_LENGTH} characters")
    return text or ""


DEVICE_SCHEMA = {probatio.Required(ATTR_DEVICE_ID): cv.string}
SNOOZE_SCHEMA = probatio.Schema(
    {
        **DEVICE_SCHEMA,
        probatio.Optional(ATTR_DAYS): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0.01, max=MAX_SNOOZE_DAYS)
        ),
        probatio.Optional(ATTR_UNTIL): cv.datetime,
        probatio.Optional(ATTR_INDEFINITELY, default=False): cv.boolean,
    }
)
UNSNOOZE_SCHEMA = probatio.Schema(DEVICE_SCHEMA)
SET_DEVICE_SETTINGS_SCHEMA = probatio.Schema(
    {
        **DEVICE_SCHEMA,
        probatio.Optional("name"): _text_or_clear,
        probatio.Optional("area"): _text_or_clear,
        probatio.Optional("quiet_threshold_hours"): probatio.Any(
            None,
            "",
            probatio.All(probatio.Coerce(float), probatio.Range(min=0.01, max=MAX_QUIET_HOURS)),
        ),
        probatio.Optional("battery_type"): _text_or_clear,
        probatio.Optional("battery_count"): probatio.Any(
            None,
            "",
            probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=MAX_BATTERY_COUNT)),
        ),
        probatio.Optional("rechargeable"): probatio.Any(None, "", cv.boolean),
        probatio.Optional("notify_policy"): probatio.Any(None, "", probatio.In(NOTIFY_POLICIES)),
        probatio.Optional("sparkline_days"): probatio.Any(
            None, "", probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=365))
        ),
        probatio.Optional("battery_warning"): probatio.Any(
            None, "", probatio.All(probatio.Coerce(float), probatio.Range(min=0, max=100))
        ),
        probatio.Optional("battery_critical"): probatio.Any(
            None, "", probatio.All(probatio.Coerce(float), probatio.Range(min=0, max=100))
        ),
    }
)
MARK_SCHEMA = probatio.Schema(
    {**DEVICE_SCHEMA, probatio.Optional(ATTR_BATTERY_TYPE): _text_or_clear}
)
REFRESH_SCHEMA = probatio.Schema({})
DEVICE_ONLY_SCHEMA = probatio.Schema(DEVICE_SCHEMA)
MAINTENANCE_SCHEMA = probatio.Schema(
    {
        probatio.Optional(ATTR_HOURS): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0, max=MAX_MAINTENANCE_HOURS)
        )
    }
)


def _coordinator(hass: HomeAssistant) -> PulseCheckCoordinator:
    """The one running coordinator, or a user-facing error."""
    coordinator = hass.data.get(DATA_COORDINATOR)
    if coordinator is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return coordinator


def resolve_device_id(coordinator: PulseCheckCoordinator, raw: str) -> str:
    """Accept a registry id, `entity:<id>` or a bare entity id of a device-less battery."""
    known = {device.device_id for device in coordinator.data.devices}
    candidates = [raw]
    if "." in raw and not raw.startswith(ORPHAN_PREFIX):
        candidates.append(ORPHAN_PREFIX + raw)
    for candidate in candidates:
        if candidate in known:
            return candidate
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_device",
        translation_placeholders={"device_id": raw},
    )


async def _snooze(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    # Indefinitely wins over an end time: it is the one that says "no end".
    until: datetime
    if call.data[ATTR_INDEFINITELY]:
        until = SNOOZED_INDEFINITELY
    elif (given := call.data.get(ATTR_UNTIL)) is not None:
        until = dt_util.as_utc(given)
    else:
        until = dt_util.utcnow() + timedelta(days=call.data.get(ATTR_DAYS, DEFAULT_SNOOZE_DAYS))
    coordinator.store.snooze(device_id, until)
    await coordinator.async_refresh()


async def _unsnooze(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    coordinator.store.unsnooze(device_id)
    await coordinator.async_refresh()


def _settings_id(coordinator: PulseCheckCoordinator, raw: str) -> str:
    """The id to store settings under: a watched device, or one that already has settings.

    Settings saved for an id that no longer matches anything watched (a
    removed device, or an entity that has since been given a device) can
    still be changed, so they can be cleared.
    """
    try:
        return resolve_device_id(coordinator, raw)
    except ServiceValidationError:
        stored = coordinator.store.device_settings
        for candidate in (raw, ORPHAN_PREFIX + raw):
            if candidate in stored:
                return candidate
        raise


async def _set_device_settings(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = _settings_id(coordinator, call.data[ATTR_DEVICE_ID])
    updates = {key: value for key, value in call.data.items() if key != ATTR_DEVICE_ID}
    merged = {**coordinator.store.device_settings.get(device_id, {}), **updates}
    if levels_clash(coordinator.core_config, {k: v for k, v in merged.items() if v != ""}):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="critical_above_warning"
        )
    coordinator.store.update_device_settings(device_id, updates)
    coordinator.rebuild_config()
    await coordinator.async_refresh()


async def _mark_replaced(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    coordinator.replacements.record(
        device_id, "replaced", dt_util.utcnow(), call.data.get(ATTR_BATTERY_TYPE) or None
    )
    await coordinator.async_refresh()


async def _mark_charged(call: ServiceCall) -> None:
    # "I am charging it": recorded as a charge, and the battery counts as
    # charging until it has climbed out of the warning range (core/charging.py).
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    now = dt_util.utcnow()
    battery = coordinator.data.by_id[device_id].battery
    coordinator.replacements.record(device_id, "charged", now, None)
    coordinator.store.mark_charging(
        device_id, new_mark(battery.level if battery is not None else None, now)
    )
    await coordinator.async_refresh()


async def _undo_mark(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    last = coordinator.replacements.last_event(device_id)
    if not coordinator.replacements.undo_last(device_id):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="nothing_to_undo",
            translation_placeholders={"device_id": call.data[ATTR_DEVICE_ID]},
        )
    # Taking back a charge marked by hand takes back its "charging now" too.
    if last is not None and last.get("kind") == "charged" and not last.get("auto"):
        coordinator.store.end_charging(device_id)
    await coordinator.async_refresh()


async def _refresh(call: ServiceCall) -> None:
    # Re-reads battery history from the recorder (logging the insight
    # count), then recomputes: the slow path, on demand.
    coordinator = _coordinator(call.hass)
    await coordinator.async_refresh_history()


async def _ping(call: ServiceCall) -> ServiceResponse:
    """Ask one device whether it is there, the way it is asked before it is marked quiet.

    One that answers counts as heard from now, as it would then. Works with
    "Ping before marking quiet" turned off: that option only stops the
    automatic asking.
    """
    coordinator = _coordinator(call.hass)
    raw = call.data[ATTR_DEVICE_ID]
    if dr.async_get(call.hass).async_get(raw) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_pingable",
            translation_placeholders={"device_id": raw},
        )
    result = await async_ask_device(call.hass, raw)
    if result.answered and raw in coordinator.data.by_id:
        await coordinator.async_note_answer(raw)
    return {
        "answered": result.answered,
        "outcome": result.outcome,
        "method": result.method,
        "address": result.address,
    }


async def async_set_maintenance(coordinator: PulseCheckCoordinator, hours: float) -> None:
    """Start (or move the end of) a maintenance window `hours` from now; 0 ends it.

    Shared by the service and the switch. The recompute that follows lets
    the notifier reschedule its end-of-window timer, or send the summary
    when the window has just been ended.
    """
    now = dt_util.utcnow()
    if hours > 0:
        coordinator.store.start_maintenance(now, now + timedelta(hours=hours))
    elif not coordinator.store.end_maintenance(now):
        return
    await coordinator.async_refresh()


async def _maintenance_mode(call: ServiceCall) -> None:
    # Hours from now, the options' default when left out; 0 ends it now.
    coordinator = _coordinator(call.hass)
    hours = call.data.get(
        ATTR_HOURS,
        coordinator.config_entry.options.get(CONF_MAINTENANCE_HOURS, DEFAULT_MAINTENANCE_HOURS),
    )
    await async_set_maintenance(coordinator, float(hours))


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register every service. Called once from `async_setup`.

    Who may call what, when a person calls it (an automation or the
    integration itself always may):

    - Everyday actions (snooze, mark replaced, maintenance mode), which the
      card and the phone buttons offer to the household: anyone who may
      control Pulse Check's entities. A read-only user may not, any more
      than they may turn on the maintenance switch.
    - Changing a device's settings, re-reading history and pinging a
      device: administrators only, like the integration's options.
    """
    control = verify_domain_control(DOMAIN)
    for name, handler, schema in (
        (SERVICE_SNOOZE, _snooze, SNOOZE_SCHEMA),
        (SERVICE_UNSNOOZE, _unsnooze, UNSNOOZE_SCHEMA),
        (SERVICE_MARK_REPLACED, _mark_replaced, MARK_SCHEMA),
        (SERVICE_MARK_CHARGED, _mark_charged, MARK_SCHEMA),
        (SERVICE_UNDO_MARK, _undo_mark, DEVICE_ONLY_SCHEMA),
        (SERVICE_MAINTENANCE_MODE, _maintenance_mode, MAINTENANCE_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, control(handler), schema=schema)
    for name, handler, schema in (
        (SERVICE_SET_DEVICE_SETTINGS, _set_device_settings, SET_DEVICE_SETTINGS_SCHEMA),
        (SERVICE_REFRESH, _refresh, REFRESH_SCHEMA),
    ):
        async_register_admin_service(hass, DOMAIN, name, handler, schema=schema)
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_PING,
        _ping,
        schema=DEVICE_ONLY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
