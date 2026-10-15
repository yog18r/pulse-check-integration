"""The Pulse Check integration.

Home Assistant concepts, briefly:

- A *config entry* is one configured instance of an integration, created
  through the UI (see `config_flow.py`) and stored by Home Assistant. It
  is passed to `async_setup_entry` on every start. Its `options` hold the
  user's settings from the Configure dialog.
- A *coordinator* (see `coordinator.py`) owns the data and decides when to
  refresh it. Entities subscribe to it instead of computing anything
  themselves.
- *Platforms* are the entity types an integration provides: `sensor`,
  `binary_sensor` and so on. Each has its own module with an
  `async_setup_entry` that creates the entities.
- *Services* (see `services.py`) are the actions automations and users
  can call, such as `pulse_check.snooze`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import PulseCheckCoordinator
from .notify import Notifier
from .services import async_setup_services

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

# Pulse Check is set up from the UI only; there is no YAML configuration.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The coordinator is attached to the entry as `runtime_data`, which is how
# Home Assistant recommends sharing per-entry objects with the platforms.
type PulseCheckConfigEntry = ConfigEntry[PulseCheckCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once, whether or not an entry exists yet."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PulseCheckConfigEntry) -> bool:
    """Set up Pulse Check from a config entry."""
    coordinator = PulseCheckCoordinator(hass, entry)
    await coordinator.store.async_load()
    coordinator.rebuild_config()
    # Compute once before the entities exist, so they never start empty.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Notifications react to every recompute from here on.
    notifier = Notifier(hass, entry, coordinator)
    notifier.async_setup()

    # Battery history is slower (database reads), so it loads in the
    # background after the entities exist and refreshes them when done.
    entry.async_create_background_task(
        hass, coordinator.async_refresh_history(), "pulse_check history"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PulseCheckConfigEntry) -> bool:
    """Unload a config entry.

    The coordinator's and notifier's listeners were registered with
    `entry.async_on_unload`, so Home Assistant removes them for us.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
