"""The integration's services (actions in the UI).

A service is something a user or an automation can call:
`pulse_check.snooze`, `pulse_check.set_device_settings` and so on. They
are registered once, at integration setup, and look up the running
config entry when called. `services.yaml` describes their fields for the
UI; `strings.json` holds the human-readable names.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import probatio
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN, NOTIFY_POLICIES
from .core.group import ORPHAN_PREFIX

if TYPE_CHECKING:
    from .coordinator import PulseCheckCoordinator

SERVICE_SNOOZE = "snooze"
SERVICE_UNSNOOZE = "unsnooze"
SERVICE_SET_DEVICE_SETTINGS = "set_device_settings"
SERVICE_MARK_REPLACED = "mark_replaced"
SERVICE_MARK_CHARGED = "mark_charged"
SERVICE_REFRESH = "refresh"

ATTR_DEVICE_ID = "device_id"
ATTR_DAYS = "days"
ATTR_UNTIL = "until"
ATTR_BATTERY_TYPE = "battery_type"

DEFAULT_SNOOZE_DAYS = 7


def _text_or_clear(value: object) -> str | None:
    """A text setting; empty text means "clear it"."""
    if value is None:
        return None
    text = str(value).strip()
    return text or ""


DEVICE_SCHEMA = {probatio.Required(ATTR_DEVICE_ID): cv.string}
SNOOZE_SCHEMA = probatio.Schema(
    {
        **DEVICE_SCHEMA,
        probatio.Optional(ATTR_DAYS): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0.01)
        ),
        probatio.Optional(ATTR_UNTIL): cv.datetime,
    }
)
UNSNOOZE_SCHEMA = probatio.Schema(DEVICE_SCHEMA)
SET_DEVICE_SETTINGS_SCHEMA = probatio.Schema(
    {
        **DEVICE_SCHEMA,
        probatio.Optional("name"): _text_or_clear,
        probatio.Optional("area"): _text_or_clear,
        probatio.Optional("quiet_threshold_hours"): probatio.Any(
            None, "", probatio.All(probatio.Coerce(float), probatio.Range(min=0.01))
        ),
        probatio.Optional("battery_type"): _text_or_clear,
        probatio.Optional("battery_count"): probatio.Any(
            None, "", probatio.All(probatio.Coerce(int), probatio.Range(min=1))
        ),
        probatio.Optional("rechargeable"): probatio.Any(None, "", cv.boolean),
        probatio.Optional("notify_policy"): probatio.Any(None, "", probatio.In(NOTIFY_POLICIES)),
        probatio.Optional("sparkline_days"): probatio.Any(
            None, "", probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=365))
        ),
    }
)
MARK_SCHEMA = probatio.Schema({**DEVICE_SCHEMA, probatio.Optional(ATTR_BATTERY_TYPE): cv.string})
REFRESH_SCHEMA = probatio.Schema({})


def _coordinator(hass: HomeAssistant) -> PulseCheckCoordinator:
    """The one running coordinator, or a user-facing error."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: PulseCheckCoordinator = entry.runtime_data
        return coordinator
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


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
    if (until := call.data.get(ATTR_UNTIL)) is not None:
        until = dt_util.as_utc(until)
    else:
        until = dt_util.utcnow() + timedelta(days=call.data.get(ATTR_DAYS, DEFAULT_SNOOZE_DAYS))
    coordinator.store.snooze(device_id, until)
    await coordinator.async_refresh()


async def _unsnooze(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    coordinator.store.unsnooze(device_id)
    await coordinator.async_refresh()


async def _set_device_settings(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    updates = {key: value for key, value in call.data.items() if key != ATTR_DEVICE_ID}
    coordinator.store.update_device_settings(device_id, updates)
    coordinator.rebuild_config()
    await coordinator.async_refresh()


async def _mark_replaced(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    coordinator.replacements.record(
        device_id, "replaced", dt_util.utcnow(), call.data.get(ATTR_BATTERY_TYPE)
    )
    await coordinator.async_refresh()


async def _mark_charged(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass)
    device_id = resolve_device_id(coordinator, call.data[ATTR_DEVICE_ID])
    coordinator.replacements.record(device_id, "charged", dt_util.utcnow(), None)
    await coordinator.async_refresh()


async def _refresh(call: ServiceCall) -> None:
    # Re-reads battery history from the recorder (logging the insight
    # count), then recomputes: the slow path, on demand.
    coordinator = _coordinator(call.hass)
    await coordinator.async_refresh_history()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register every service. Called once from `async_setup`."""
    for name, handler, schema in (
        (SERVICE_SNOOZE, _snooze, SNOOZE_SCHEMA),
        (SERVICE_UNSNOOZE, _unsnooze, UNSNOOZE_SCHEMA),
        (SERVICE_SET_DEVICE_SETTINGS, _set_device_settings, SET_DEVICE_SETTINGS_SCHEMA),
        (SERVICE_MARK_REPLACED, _mark_replaced, MARK_SCHEMA),
        (SERVICE_MARK_CHARGED, _mark_charged, MARK_SCHEMA),
        (SERVICE_REFRESH, _refresh, REFRESH_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)
