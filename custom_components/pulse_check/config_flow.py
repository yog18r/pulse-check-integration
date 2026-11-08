"""The config flow and the options flow.

A *config flow* is the dialog behind Settings > Devices & services > Add
integration. Each `async_step_*` method is one screen. Pulse Check needs
no credentials or addresses, so the only screen is a confirmation.

An *options flow* is the "Configure" dialog on an integration that is
already set up. Its result is stored in `entry.options`; `OptionsFlowWithReload`
reloads the integration when the dialog is saved, so the new thresholds
and filters take effect immediately.

Only one instance makes sense (it watches the whole house), which the
manifest enforces with `single_config_entry`. The unique id below is a
second guard so an old Home Assistant without that flag behaves the same.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    ObjectSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from .const import (
    CONF_BATTERY_CRITICAL,
    CONF_BATTERY_WARNING,
    CONF_CONFIRM_MINUTES,
    CONF_DIGEST_TIME,
    CONF_DIGEST_WEEKDAY,
    CONF_EXCLUDE_AREAS,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_HOURS,
    CONF_INCLUDE_AREAS,
    CONF_INCLUDE_INTEGRATIONS,
    CONF_INTEGRATION,
    CONF_INTEGRATION_LIMIT,
    CONF_INTEGRATION_THRESHOLDS,
    CONF_MAINTENANCE_HOURS,
    CONF_NOTIFY_CRITICAL,
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_WARNING,
    CONF_PER_DEVICE_SENSORS,
    CONF_QUIET_SCOPE,
    CONF_QUIET_THRESHOLD_HOURS,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_MAX,
    CONF_RESTART_TIMEOUT_MINUTES,
    CONF_STARTUP_GRACE_MINUTES,
    CONF_WATCH_NON_DEVICES,
    CONF_WEEKLY_ALL_CLEAR,
    DATA_COORDINATOR,
    DEFAULT_BATTERY_CRITICAL,
    DEFAULT_BATTERY_WARNING,
    DEFAULT_CONFIRM_MINUTES,
    DEFAULT_DIGEST_TIME,
    DEFAULT_DIGEST_WEEKDAY,
    DEFAULT_INTEGRATION_LIMIT,
    DEFAULT_MAINTENANCE_HOURS,
    DEFAULT_NOTIFY_CRITICAL,
    DEFAULT_NOTIFY_WARNING,
    DEFAULT_QUIET_SCOPE,
    DEFAULT_QUIET_THRESHOLD_HOURS,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_REMINDER_MAX,
    DEFAULT_RESTART_TIMEOUT_MINUTES,
    DEFAULT_STARTUP_GRACE_MINUTES,
    DEFAULT_WATCH_NON_DEVICES,
    DOMAIN,
    MAX_MAINTENANCE_HOURS,
    NOTIFY_POLICIES,
    QUIET_SCOPES,
    WEEKDAYS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant

    from .coordinator import PulseCheckCoordinator

# The options form is split into two collapsible sections. The form
# submits them nested (`{"thresholds": {...}, "filters": {...}}`); the
# options are stored flat so the rest of the integration reads one dict.
SECTION_THRESHOLDS = "thresholds"
SECTION_FILTERS = "filters"
SECTION_NOTIFICATIONS = "notifications"
SECTION_ENTITIES = "entities"
THRESHOLD_KEYS = (
    CONF_BATTERY_WARNING,
    CONF_BATTERY_CRITICAL,
    CONF_QUIET_THRESHOLD_HOURS,
    CONF_QUIET_SCOPE,
    CONF_INTEGRATION_THRESHOLDS,
)
FILTER_KEYS = (
    CONF_WATCH_NON_DEVICES,
    CONF_INCLUDE_AREAS,
    CONF_EXCLUDE_AREAS,
    CONF_INCLUDE_INTEGRATIONS,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
)
NOTIFICATION_KEYS = (
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_CRITICAL,
    CONF_NOTIFY_WARNING,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_MAX,
    CONF_INTEGRATION_LIMIT,
    CONF_DIGEST_TIME,
    CONF_DIGEST_WEEKDAY,
    CONF_WEEKLY_ALL_CLEAR,
    CONF_STARTUP_GRACE_MINUTES,
    CONF_CONFIRM_MINUTES,
    CONF_RESTART_TIMEOUT_MINUTES,
    CONF_MAINTENANCE_HOURS,
)
ENTITY_KEYS = (CONF_PER_DEVICE_SENSORS,)
SECTIONS = {
    SECTION_THRESHOLDS: THRESHOLD_KEYS,
    SECTION_FILTERS: FILTER_KEYS,
    SECTION_NOTIFICATIONS: NOTIFICATION_KEYS,
    SECTION_ENTITIES: ENTITY_KEYS,
}

MAX_QUIET_HOURS = 24 * 365


class PulseCheckConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the one-step setup."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PulseCheckOptionsFlow:
        """Tell Home Assistant which class handles the Configure dialog."""
        return PulseCheckOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm and create the entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Pulse Check", data={})
        return self.async_show_form(step_id="user", data_schema=probatio.Schema({}))


def _known_platforms(hass: HomeAssistant) -> list[str]:
    """Every integration that provides at least one entity, for the dropdowns."""
    platforms = {entry.platform for entry in er.async_get(hass).entities.values() if entry.platform}
    return sorted(platforms)


def _notify_targets(hass: HomeAssistant) -> list[str]:
    """Every way to send a notification: legacy notify services and notify entities."""
    services = {
        f"notify.{name}"
        for name in hass.services.async_services_for_domain("notify")
        if name not in ("send_message", "persistent_notification")
    }
    entities = {state.entity_id for state in hass.states.async_all("notify")}
    return sorted(services | entities)


def _policy() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=list(NOTIFY_POLICIES),
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="notify_policy",
        )
    )


def _percent() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=100, step=1, unit_of_measurement="%", mode=NumberSelectorMode.BOX
        )
    )


def _hours() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0.25,
            max=MAX_QUIET_HOURS,
            step=0.25,
            unit_of_measurement="h",
            mode=NumberSelectorMode.BOX,
        )
    )


def _minutes() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=1440, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX
        )
    )


def _integrations(platforms: list[str]) -> SelectSelector:
    """A multi-select of integrations; unknown ones can still be typed in."""
    return SelectSelector(
        SelectSelectorConfig(
            options=platforms, multiple=True, custom_value=True, mode=SelectSelectorMode.DROPDOWN
        )
    )


def _options_schema(platforms: list[str], notify_targets: list[str]) -> probatio.Schema:
    thresholds = probatio.Schema(
        {
            probatio.Required(CONF_BATTERY_WARNING, default=DEFAULT_BATTERY_WARNING): _percent(),
            probatio.Required(CONF_BATTERY_CRITICAL, default=DEFAULT_BATTERY_CRITICAL): _percent(),
            probatio.Required(
                CONF_QUIET_THRESHOLD_HOURS, default=DEFAULT_QUIET_THRESHOLD_HOURS
            ): _hours(),
            probatio.Required(CONF_QUIET_SCOPE, default=DEFAULT_QUIET_SCOPE): SelectSelector(
                SelectSelectorConfig(
                    options=list(QUIET_SCOPES),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_QUIET_SCOPE,
                )
            ),
            probatio.Optional(CONF_INTEGRATION_THRESHOLDS): ObjectSelector(
                ObjectSelectorConfig(
                    multiple=True,
                    label_field=CONF_INTEGRATION,
                    description_field=CONF_HOURS,
                    translation_key=CONF_INTEGRATION_THRESHOLDS,
                    fields={
                        CONF_INTEGRATION: {
                            "required": True,
                            "selector": SelectSelector(
                                SelectSelectorConfig(
                                    options=platforms,
                                    custom_value=True,
                                    mode=SelectSelectorMode.DROPDOWN,
                                )
                            ),
                        },
                        CONF_HOURS: {"required": True, "selector": _hours()},
                    },
                )
            ),
        }
    )
    filters = probatio.Schema(
        {
            probatio.Required(
                CONF_WATCH_NON_DEVICES, default=DEFAULT_WATCH_NON_DEVICES
            ): BooleanSelector(),
            probatio.Optional(CONF_INCLUDE_AREAS): AreaSelector(AreaSelectorConfig(multiple=True)),
            probatio.Optional(CONF_EXCLUDE_AREAS): AreaSelector(AreaSelectorConfig(multiple=True)),
            probatio.Optional(CONF_INCLUDE_INTEGRATIONS): _integrations(platforms),
            probatio.Optional(CONF_EXCLUDE_INTEGRATIONS): _integrations(platforms),
            probatio.Optional(CONF_EXCLUDE_DEVICES): DeviceSelector(
                DeviceSelectorConfig(multiple=True)
            ),
            probatio.Optional(CONF_EXCLUDE_ENTITIES): EntitySelector(
                EntitySelectorConfig(multiple=True)
            ),
        }
    )
    notifications = probatio.Schema(
        {
            probatio.Optional(CONF_NOTIFY_TARGETS): SelectSelector(
                SelectSelectorConfig(
                    options=notify_targets,
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            probatio.Required(CONF_NOTIFY_CRITICAL, default=DEFAULT_NOTIFY_CRITICAL): _policy(),
            probatio.Required(CONF_NOTIFY_WARNING, default=DEFAULT_NOTIFY_WARNING): _policy(),
            probatio.Required(CONF_REMINDER_DAYS, default=DEFAULT_REMINDER_DAYS): NumberSelector(
                NumberSelectorConfig(
                    min=0.5, max=365, step=0.5, unit_of_measurement="d", mode=NumberSelectorMode.BOX
                )
            ),
            probatio.Required(CONF_REMINDER_MAX, default=DEFAULT_REMINDER_MAX): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)
            ),
            probatio.Required(
                CONF_INTEGRATION_LIMIT, default=DEFAULT_INTEGRATION_LIMIT
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)
            ),
            probatio.Required(CONF_DIGEST_TIME, default=DEFAULT_DIGEST_TIME): TimeSelector(),
            probatio.Required(CONF_DIGEST_WEEKDAY, default=DEFAULT_DIGEST_WEEKDAY): SelectSelector(
                SelectSelectorConfig(
                    options=list(WEEKDAYS),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_DIGEST_WEEKDAY,
                )
            ),
            probatio.Required(CONF_WEEKLY_ALL_CLEAR, default=False): BooleanSelector(),
            probatio.Required(
                CONF_STARTUP_GRACE_MINUTES, default=DEFAULT_STARTUP_GRACE_MINUTES
            ): _minutes(),
            probatio.Required(CONF_CONFIRM_MINUTES, default=DEFAULT_CONFIRM_MINUTES): _minutes(),
            probatio.Required(
                CONF_RESTART_TIMEOUT_MINUTES, default=DEFAULT_RESTART_TIMEOUT_MINUTES
            ): _minutes(),
            probatio.Required(
                CONF_MAINTENANCE_HOURS, default=DEFAULT_MAINTENANCE_HOURS
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.25,
                    max=MAX_MAINTENANCE_HOURS,
                    step=0.25,
                    unit_of_measurement="h",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )
    entities = probatio.Schema(
        {probatio.Required(CONF_PER_DEVICE_SENSORS, default=False): BooleanSelector()}
    )
    return probatio.Schema(
        {
            probatio.Optional(SECTION_THRESHOLDS): section(thresholds, {"collapsed": False}),
            probatio.Optional(SECTION_FILTERS): section(filters, {"collapsed": False}),
            probatio.Optional(SECTION_NOTIFICATIONS): section(notifications, {"collapsed": True}),
            probatio.Optional(SECTION_ENTITIES): section(entities, {"collapsed": True}),
        }
    )


def nest_options(options: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Flat stored options -> the form's sections (for suggested values)."""
    return {
        section_key: {k: options[k] for k in keys if k in options}
        for section_key, keys in SECTIONS.items()
    }


def flatten_options(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """The form's sections -> flat options, dropping empty lists."""
    flat: dict[str, Any] = {}
    for section_key in SECTIONS:
        for key, value in (user_input.get(section_key) or {}).items():
            if value in ([], None, ""):
                continue
            flat[key] = value
    return flat


# Battery sizes offered in the per-device form; any other can be typed in.
COMMON_BATTERY_TYPES = [
    "AA",
    "AAA",
    "CR2032",
    "CR2450",
    "CR2477",
    "CR2016",
    "CR2025",
    "CR123A",
    "CR2",
    "9V",
    "LR44",
    "ER14250",
    "ER14505",
]
# The form's fields, in the store's names. Leaving one empty clears it.
DEVICE_FIELDS = (
    "name",
    "area",
    "battery_type",
    "battery_count",
    "rechargeable",
    "quiet_threshold_hours",
    "notify_policy",
    "sparkline_days",
)
CONF_DEVICE = "device"
CONF_CLEAR = "clear"
# Marks in the device list: a device with saved settings, and settings
# saved for something that is no longer watched (so they can be cleared).
HAS_SETTINGS = "\u2699 "
NOT_FOUND = "\u26a0 "


def _device_options(coordinator: PulseCheckCoordinator) -> list[SelectOptionDict]:
    """Every watched device, service and lone entity, those with settings first."""
    saved = coordinator.store.device_settings
    options: list[tuple[int, str, SelectOptionDict]] = []
    for device in coordinator.data.devices:
        context = " · ".join(part for part in (device.area, device.integration) if part)
        label = f"{device.name} ({context})" if context else device.name
        has = device.device_id in saved
        shown = (HAS_SETTINGS if has else "") + label
        options.append(
            (0 if has else 1, label.lower(), {"value": device.device_id, "label": shown})
        )
    watched = {device.device_id for device in coordinator.data.devices}
    for device_id in saved:
        if device_id not in watched:
            label = NOT_FOUND + device_id
            options.append((0, label.lower(), {"value": device_id, "label": label}))
    return [option for _, _, option in sorted(options, key=lambda o: (o[0], o[1]))]


def _device_schema(hass: HomeAssistant) -> probatio.Schema:
    areas = sorted(area.name for area in ar.async_get(hass).areas.values())
    return probatio.Schema(
        {
            probatio.Optional("name"): TextSelector(),
            probatio.Optional("area"): SelectSelector(
                SelectSelectorConfig(
                    options=areas, custom_value=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            probatio.Optional("battery_type"): SelectSelector(
                SelectSelectorConfig(
                    options=COMMON_BATTERY_TYPES,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            probatio.Optional("battery_count"): NumberSelector(
                NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.BOX)
            ),
            probatio.Optional("rechargeable"): BooleanSelector(),
            probatio.Optional("quiet_threshold_hours"): _hours(),
            probatio.Optional("notify_policy"): _policy(),
            probatio.Optional("sparkline_days"): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=365, step=1, unit_of_measurement="d", mode=NumberSelectorMode.BOX
                )
            ),
            probatio.Optional(CONF_CLEAR, default=False): BooleanSelector(),
        }
    )


def _device_updates(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """The form's answer as store updates: an empty field, or unticked rechargeable, clears."""
    if user_input.get(CONF_CLEAR):
        return dict.fromkeys(DEVICE_FIELDS, "")
    updates: dict[str, Any] = {}
    for key in DEVICE_FIELDS:
        value = user_input.get(key)
        if value in (None, "", False):
            updates[key] = ""
        elif key in ("battery_count", "sparkline_days"):
            updates[key] = int(value)
        elif key == "quiet_threshold_hours":
            updates[key] = float(value)
        elif isinstance(value, str):
            updates[key] = value.strip()
        else:
            updates[key] = value
    return updates


class PulseCheckOptionsFlow(OptionsFlowWithReload):
    """The Configure dialog: general options, or one device's settings.

    Per-device settings live in the integration's store, not in the
    options: every card and every notification reads them. Saving them
    leaves the options as they are, so nothing reloads.
    """

    _device_id: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose what to configure."""
        return self.async_show_menu(step_id="init", menu_options=["general", "device"])

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Thresholds, filters, notifications and entities: show the form, validate, save."""
        errors: dict[str, str] = {}
        if user_input is not None:
            flat = flatten_options(user_input)
            if flat.get(CONF_BATTERY_CRITICAL, 0) > flat.get(CONF_BATTERY_WARNING, 100):
                errors["base"] = "critical_above_warning"
            else:
                return self.async_create_entry(data=flat)

        schema = _options_schema(_known_platforms(self.hass), _notify_targets(self.hass))
        current = user_input if user_input is not None else nest_options(self.config_entry.options)
        return self.async_show_form(
            step_id="general",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the device, service or entity to edit."""
        coordinator = self.hass.data.get(DATA_COORDINATOR)
        if coordinator is None or coordinator.data is None:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            self._device_id = user_input[CONF_DEVICE]
            return await self.async_step_device_settings()
        schema = probatio.Schema(
            {
                probatio.Required(CONF_DEVICE): SelectSelector(
                    SelectSelectorConfig(
                        options=_device_options(coordinator), mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(step_id="device", data_schema=schema)

    async def async_step_device_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One device's settings, saved to the integration's store."""
        coordinator = self.hass.data.get(DATA_COORDINATOR)
        device_id = self._device_id
        if coordinator is None or device_id is None:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            coordinator.store.update_device_settings(device_id, _device_updates(user_input))
            coordinator.rebuild_config()
            await coordinator.async_refresh()
            # The options are unchanged, so Home Assistant does not reload.
            return self.async_create_entry(data=dict(self.config_entry.options))

        device = coordinator.data.by_id.get(device_id)
        name = device.name if device is not None else device_id
        return self.async_show_form(
            step_id="device_settings",
            data_schema=self.add_suggested_values_to_schema(
                _device_schema(self.hass), coordinator.store.device_settings.get(device_id, {})
            ),
            description_placeholders={"device": name},
        )
