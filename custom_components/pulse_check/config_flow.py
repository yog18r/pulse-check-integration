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
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
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
from .core.group import ORPHAN_PREFIX
from .core.models import plain_number
from .messages import async_load_messages
from .options import levels_clash
from .storage import stored_rechargeable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from homeassistant.core import HomeAssistant

    from .coordinator import PulseCheckCoordinator
    from .messages import Catalog

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
# The form's fields that map one to one onto stored settings. Leaving one
# empty clears it. `battery_kind` and `ignore` are handled on their own.
DEVICE_FIELDS = (
    "name",
    "area",
    "battery_type",
    "battery_count",
    "battery_warning",
    "battery_critical",
    "quiet_threshold_hours",
    "notify_policy",
    "sparkline_days",
)
CONF_DEVICE = "device"
CONF_CLEAR = "clear"
CONF_IGNORE = "ignore"
# Charged or replaced: worked out from the history, or the user's say.
CONF_BATTERY_KIND = "battery_kind"
KIND_AUTO = "auto"
KIND_RECHARGEABLE = "rechargeable"
KIND_REPLACEABLE = "replaceable"
BATTERY_KINDS = (KIND_AUTO, KIND_RECHARGEABLE, KIND_REPLACEABLE)
# Marks settings saved for something that is no longer found.
NOT_FOUND = "⚠ "


def _bare_entity(device_id: str) -> str | None:
    return device_id.removeprefix(ORPHAN_PREFIX) if device_id.startswith(ORPHAN_PREFIX) else None


def _is_ignored(options: Mapping[str, Any], device_id: str) -> bool:
    """Whether the general options' ignore lists leave this device out."""
    devices = options.get(CONF_EXCLUDE_DEVICES) or []
    if device_id in devices:
        return True
    entity_id = _bare_entity(device_id)
    return entity_id is not None and (
        entity_id in devices or entity_id in (options.get(CONF_EXCLUDE_ENTITIES) or [])
    )


def _with_ignore(options: Mapping[str, Any], device_id: str, ignore: bool) -> dict[str, Any]:
    """The options with this device added to, or taken off, the ignore lists.

    A device goes on "Ignore these devices"; an entity with no device on
    "Ignore these entities", where the general options show it by name.
    """
    updated = dict(options)
    entity_id = _bare_entity(device_id)
    devices = [
        d for d in options.get(CONF_EXCLUDE_DEVICES) or [] if d not in (device_id, entity_id)
    ]
    entities = [e for e in options.get(CONF_EXCLUDE_ENTITIES) or [] if e != entity_id]
    if ignore and entity_id is not None:
        entities.append(entity_id)
    elif ignore:
        devices.append(device_id)
    for key, values in ((CONF_EXCLUDE_DEVICES, devices), (CONF_EXCLUDE_ENTITIES, entities)):
        if values:
            updated[key] = values
        else:
            updated.pop(key, None)
    return updated


def _ignored_ids(hass: HomeAssistant, options: Mapping[str, Any]) -> set[str]:
    """Devices, and entities with no device, that the ignore lists leave out.

    An ignored entity of a device is not one of them: it leaves out one
    reading, not the device.
    """
    entities = er.async_get(hass)
    ids: set[str] = set()
    for raw in options.get(CONF_EXCLUDE_DEVICES) or []:
        ids.add(ORPHAN_PREFIX + raw if "." in raw and not raw.startswith(ORPHAN_PREFIX) else raw)
    for entity_id in options.get(CONF_EXCLUDE_ENTITIES) or []:
        entry = entities.async_get(entity_id)
        if entry is None or entry.device_id is None:
            ids.add(ORPHAN_PREFIX + entity_id)
    return ids


def _registry_name(hass: HomeAssistant, device_id: str) -> str | None:
    """The name of a device or entity Pulse Check does not watch (ignored), if it exists."""
    entity_id = _bare_entity(device_id)
    if entity_id is None:
        device = dr.async_get(hass).async_get(device_id)
        return (device.name_by_user or device.name or device_id) if device else None
    state = hass.states.get(entity_id)
    if state is not None:
        return state.name
    entry = er.async_get(hass).async_get(entity_id)
    return (entry.name or entry.original_name or entity_id) if entry else None


class _Devices:
    """What the per-device steps need to know about every device, read once per screen."""

    def __init__(self, hass: HomeAssistant, coordinator: PulseCheckCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.saved = coordinator.store.device_settings
        self.options = coordinator.config_entry.options
        self.ignored = _ignored_ids(hass, self.options)

    def label(self, device_id: str) -> str:
        """Name with area and integration; ⚠ and the id when it is gone."""
        device = self.coordinator.data.by_id.get(device_id)
        if device is None:
            name = _registry_name(self.hass, device_id)
            return name if name is not None else NOT_FOUND + device_id
        context = " · ".join(part for part in (device.area, device.integration) if part)
        return f"{device.name} ({context})" if context else device.name

    def gone(self, device_id: str) -> bool:
        """Neither watched nor in Home Assistant's registries any more."""
        return (
            device_id not in self.coordinator.data.by_id
            and _registry_name(self.hass, device_id) is None
        )

    def choices(self, ids: Iterable[str]) -> list[SelectOptionDict]:
        """Dropdown options for these ids, sorted by label."""
        labelled = [(self.label(device_id), device_id) for device_id in ids]
        return [
            {"value": device_id, "label": label}
            for label, device_id in sorted(labelled, key=lambda pair: pair[0].lower())
        ]

    def editable(self) -> set[str]:
        """Devices with saved settings or ignored, those no longer found included."""
        return set(self.saved) | self.ignored

    def addable(self) -> list[str]:
        """Every watched device, service and lone entity with nothing saved yet."""
        return [d.device_id for d in self.coordinator.data.devices if d.device_id not in self.saved]


def _setting_parts(settings: Mapping[str, Any], text: Catalog) -> list[str]:
    """One device's saved settings in a few words each."""
    parts: list[str] = []
    if settings.get("name"):
        parts.append(text("settings_shown_as", value=settings["name"]))
    if settings.get("area"):
        parts.append(text("settings_area", value=settings["area"]))
    battery_type = settings.get("battery_type")
    count = settings.get("battery_count")
    if battery_type and count:
        parts.append(f"{count} × {battery_type}")
    elif battery_type:
        parts.append(str(battery_type))
    elif count:
        parts.append(text("settings_battery_count", count=int(count)))
    rechargeable = stored_rechargeable(settings)
    if rechargeable is not None:
        parts.append(text("settings_rechargeable" if rechargeable else "settings_replaceable"))
    if settings.get("battery_warning") is not None:
        parts.append(text("settings_warning", level=plain_number(settings["battery_warning"])))
    if settings.get("battery_critical") is not None:
        parts.append(text("settings_critical", level=plain_number(settings["battery_critical"])))
    if settings.get("quiet_threshold_hours") is not None:
        hours = plain_number(float(settings["quiet_threshold_hours"]))
        parts.append(text("settings_quiet", hours=hours))
    if settings.get("notify_policy") in NOTIFY_POLICIES:
        parts.append(text(f"settings_policy_{settings['notify_policy']}"))
    if settings.get("sparkline_days"):
        parts.append(text("settings_trend", days=settings["sparkline_days"]))
    return parts


def _saved_summary(devices: _Devices, text: Catalog) -> str:
    """Every device with saved settings or ignored, as a Markdown list for the menu."""
    ids = devices.editable()
    if not ids:
        return text("settings_none")
    lines = []
    for label, device_id in sorted(
        ((devices.label(device_id), device_id) for device_id in ids),
        key=lambda pair: pair[0].lower(),
    ):
        parts = _setting_parts(devices.saved.get(device_id, {}), text)
        if device_id in devices.ignored:
            parts.append(text("settings_ignored"))
        if devices.gone(device_id):
            parts.append(text("settings_not_found"))
        lines.append(f"- **{label}**: {' · '.join(parts)}")
    return "\n".join(lines)


def _status(devices: _Devices, device_id: str, text: Catalog) -> str:
    """What Pulse Check sees for the device now, and what an empty field falls back to."""
    if devices.gone(device_id):
        return text("settings_not_found")
    device = devices.coordinator.data.by_id.get(device_id)
    if device is None:
        return text("status_ignored")
    config = devices.coordinator.core_config
    parts: list[str] = []
    battery = device.battery
    if battery is not None:
        if battery.level is not None:
            parts.append(text("status_battery", level=plain_number(battery.level)))
        elif battery.is_low:
            parts.append(text("status_battery_low"))
        kind = (
            device.battery_kind if device.battery_kind in ("charged", "replaceable") else "unknown"
        )
        parts.append(text(f"status_kind_{kind}"))
    now = " · ".join(parts)
    defaults: list[str] = []
    if battery is not None:
        defaults.append(
            text(
                "status_default_levels",
                warning=plain_number(config.battery_warning),
                critical=plain_number(config.battery_critical),
            )
        )
    if device.source == "device" and (battery is not None or config.quiet_scope == "all"):
        hours = config.integration_thresholds.get(device.integration, config.quiet_threshold_hours)
        defaults.append(text("status_default_quiet", hours=plain_number(hours)))
    if defaults:
        fallback = text("status_defaults", defaults=", ".join(defaults))
        return f"{now}\n\n{fallback}" if now else fallback
    return now


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
            probatio.Required(CONF_BATTERY_KIND, default=KIND_AUTO): SelectSelector(
                SelectSelectorConfig(
                    options=list(BATTERY_KINDS),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_BATTERY_KIND,
                )
            ),
            probatio.Optional("battery_warning"): _percent(),
            probatio.Optional("battery_critical"): _percent(),
            probatio.Optional("quiet_threshold_hours"): _hours(),
            probatio.Optional("notify_policy"): _policy(),
            probatio.Optional("sparkline_days"): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=365, step=1, unit_of_measurement="d", mode=NumberSelectorMode.BOX
                )
            ),
            probatio.Optional(CONF_IGNORE, default=False): BooleanSelector(),
            probatio.Optional(CONF_CLEAR, default=False): BooleanSelector(),
        }
    )


def _form_values(settings: Mapping[str, Any], ignored: bool) -> dict[str, Any]:
    """Stored settings -> the form's suggested values."""
    values = {key: settings[key] for key in DEVICE_FIELDS if key in settings}
    rechargeable = stored_rechargeable(settings)
    if rechargeable is None:
        values[CONF_BATTERY_KIND] = KIND_AUTO
    else:
        values[CONF_BATTERY_KIND] = KIND_RECHARGEABLE if rechargeable else KIND_REPLACEABLE
    values[CONF_IGNORE] = ignored
    return values


def _device_updates(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """The form's answer as store updates: an empty field clears that setting."""
    if user_input.get(CONF_CLEAR):
        return dict.fromkeys((*DEVICE_FIELDS, "rechargeable"), "")
    updates: dict[str, Any] = {}
    for key in DEVICE_FIELDS:
        value = user_input.get(key)
        if value in (None, ""):
            updates[key] = ""
        elif key in ("battery_count", "sparkline_days"):
            updates[key] = int(value)
        elif key in ("quiet_threshold_hours", "battery_warning", "battery_critical"):
            updates[key] = float(value)
        elif isinstance(value, str):
            updates[key] = value.strip()
        else:
            updates[key] = value
    kind = user_input.get(CONF_BATTERY_KIND, KIND_AUTO)
    updates["rechargeable"] = "" if kind == KIND_AUTO else kind == KIND_RECHARGEABLE
    return updates


class PulseCheckOptionsFlow(OptionsFlowWithReload):
    """The Configure dialog: general options, or one device's settings.

    Per-device settings live in the integration's store, not in the
    options: every card and every notification reads them. Each device's
    settings are saved as its form is submitted, and the dialog returns to
    the list for the next one; nothing reloads. Ignoring a device changes
    the options' ignore lists straight away, without a reload either.
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

    def _devices(self) -> _Devices | None:
        coordinator = self.hass.data.get(DATA_COORDINATOR)
        if coordinator is None or coordinator.data is None:
            return None
        return _Devices(self.hass, coordinator)

    async def _text(self) -> Catalog:
        return (await async_load_messages(self.hass)).catalog(self.hass.config.language)

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What is saved or ignored for which device, then edit one, add another, or finish."""
        devices = self._devices()
        if devices is None:
            return self.async_abort(reason="not_loaded")
        menu = ["device_done"]
        if devices.addable():
            menu.insert(0, "device_add")
        if devices.editable():
            menu.insert(0, "device_edit")
        return self.async_show_menu(
            step_id="device",
            menu_options=menu,
            description_placeholders={"saved": _saved_summary(devices, await self._text())},
        )

    async def async_step_device_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Close the dialog. Everything was saved as it was submitted."""
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def async_step_device_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose one of the devices that have saved settings or are ignored."""
        return await self._choose_device("device_edit", lambda d: d.editable(), user_input)

    async def async_step_device_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a device, service or entity that has no settings yet."""
        return await self._choose_device("device_add", lambda d: d.addable(), user_input)

    async def _choose_device(
        self,
        step_id: str,
        ids: Callable[[_Devices], Iterable[str]],
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        devices = self._devices()
        if devices is None:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            self._device_id = user_input[CONF_DEVICE]
            return await self.async_step_device_settings()
        schema = probatio.Schema(
            {
                probatio.Required(CONF_DEVICE): SelectSelector(
                    SelectSelectorConfig(
                        options=devices.choices(ids(devices)), mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema)

    async def async_step_device_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One device's settings, saved to the integration's store, then back to the list."""
        devices = self._devices()
        device_id = self._device_id
        if devices is None or device_id is None:
            return self.async_abort(reason="not_loaded")
        coordinator = devices.coordinator
        errors: dict[str, str] = {}
        if user_input is not None:
            updates = _device_updates(user_input)
            kept = {key: value for key, value in updates.items() if value != ""}
            if levels_clash(coordinator.core_config, kept):
                errors["base"] = "critical_above_warning"
            else:
                coordinator.store.update_device_settings(device_id, updates)
                ignore = bool(user_input.get(CONF_IGNORE))
                if ignore != _is_ignored(devices.options, device_id):
                    # Straight into the options, so the analysis drops (or
                    # takes back) the device now. The dialog's own result
                    # then matches them, so Home Assistant does not reload.
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        options=_with_ignore(devices.options, device_id, ignore),
                    )
                coordinator.rebuild_config()
                await coordinator.async_refresh()
                self._device_id = None
                return await self.async_step_device()

        stored = devices.saved.get(device_id, {})
        current = (
            user_input
            if user_input is not None
            else _form_values(stored, _is_ignored(devices.options, device_id))
        )
        return self.async_show_form(
            step_id="device_settings",
            data_schema=self.add_suggested_values_to_schema(_device_schema(self.hass), current),
            errors=errors,
            description_placeholders={
                "device": devices.label(device_id).removeprefix(NOT_FOUND),
                "status": _status(devices, device_id, await self._text()),
            },
        )
