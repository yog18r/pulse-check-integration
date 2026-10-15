"""The config flow: how Pulse Check is added from the UI.

A config flow is the dialog behind Settings > Devices & services > Add
integration. Each `async_step_*` method is one screen. Pulse Check needs
no credentials or addresses, so the only screen is a confirmation; the
options flow (thresholds, filters, notifications) arrives in phase 2.

Only one instance makes sense (it watches the whole house), which the
manifest enforces with `single_config_entry`. The unique id below is a
second guard so an old Home Assistant without that flag behaves the same.
"""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class PulseCheckConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the one-step setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm and create the entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Pulse Check", data={})
        return self.async_show_form(step_id="user", data_schema=probatio.Schema({}))
