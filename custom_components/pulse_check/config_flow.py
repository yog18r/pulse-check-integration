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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    ObjectSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_BATTERY_CRITICAL,
    CONF_BATTERY_WARNING,
    CONF_EXCLUDE_AREAS,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_HOURS,
    CONF_INCLUDE_AREAS,
    CONF_INCLUDE_INTEGRATIONS,
    CONF_INTEGRATION,
    CONF_INTEGRATION_THRESHOLDS,
    CONF_QUIET_SCOPE,
    CONF_QUIET_THRESHOLD_HOURS,
    DEFAULT_BATTERY_CRITICAL,
    DEFAULT_BATTERY_WARNING,
    DEFAULT_QUIET_SCOPE,
    DEFAULT_QUIET_THRESHOLD_HOURS,
    DOMAIN,
    QUIET_SCOPES,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant

# The options form is split into two collapsible sections. The form
# submits them nested (`{"thresholds": {...}, "filters": {...}}`); the
# options are stored flat so the rest of the integration reads one dict.
SECTION_THRESHOLDS = "thresholds"
SECTION_FILTERS = "filters"
THRESHOLD_KEYS = (
    CONF_BATTERY_WARNING,
    CONF_BATTERY_CRITICAL,
    CONF_QUIET_THRESHOLD_HOURS,
    CONF_QUIET_SCOPE,
    CONF_INTEGRATION_THRESHOLDS,
)
FILTER_KEYS = (
    CONF_INCLUDE_AREAS,
    CONF_EXCLUDE_AREAS,
    CONF_INCLUDE_INTEGRATIONS,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
)

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


def _integrations(platforms: list[str]) -> SelectSelector:
    """A multi-select of integrations; unknown ones can still be typed in."""
    return SelectSelector(
        SelectSelectorConfig(
            options=platforms, multiple=True, custom_value=True, mode=SelectSelectorMode.DROPDOWN
        )
    )


def _options_schema(platforms: list[str]) -> probatio.Schema:
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
    return probatio.Schema(
        {
            probatio.Required(SECTION_THRESHOLDS): section(thresholds, {"collapsed": False}),
            probatio.Required(SECTION_FILTERS): section(filters, {"collapsed": False}),
        }
    )


def nest_options(options: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Flat stored options -> the form's two sections (for suggested values)."""
    return {
        SECTION_THRESHOLDS: {k: options[k] for k in THRESHOLD_KEYS if k in options},
        SECTION_FILTERS: {k: options[k] for k in FILTER_KEYS if k in options},
    }


def flatten_options(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """The form's two sections -> flat options, dropping empty lists."""
    flat: dict[str, Any] = {}
    for section_key in (SECTION_THRESHOLDS, SECTION_FILTERS):
        for key, value in (user_input.get(section_key) or {}).items():
            if value in ([], None, ""):
                continue
            flat[key] = value
    return flat


class PulseCheckOptionsFlow(OptionsFlowWithReload):
    """The Configure dialog: thresholds and filters."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the form, validate, and save."""
        errors: dict[str, str] = {}
        if user_input is not None:
            flat = flatten_options(user_input)
            if flat.get(CONF_BATTERY_CRITICAL, 0) > flat.get(CONF_BATTERY_WARNING, 100):
                errors["base"] = "critical_above_warning"
            else:
                return self.async_create_entry(data=flat)

        schema = _options_schema(_known_platforms(self.hass))
        current = user_input if user_input is not None else nest_options(self.config_entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
        )
