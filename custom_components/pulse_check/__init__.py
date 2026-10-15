"""The Pulse Check integration.

Home Assistant concepts, briefly:

- A *config entry* is one configured instance of an integration, created
  through the UI (see `config_flow.py`) and stored by Home Assistant. It
  is passed to `async_setup_entry` on every start.
- A *coordinator* (see `coordinator.py`) owns the data and decides when to
  refresh it. Entities subscribe to it instead of computing anything
  themselves.
- *Platforms* are the entity types an integration provides: `sensor`,
  `binary_sensor` and so on. Each has its own module with an
  `async_setup_entry` that creates the entities.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import PulseCheckCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

# The coordinator is attached to the entry as `runtime_data`, which is how
# Home Assistant recommends sharing per-entry objects with the platforms.
type PulseCheckConfigEntry = ConfigEntry[PulseCheckCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PulseCheckConfigEntry) -> bool:
    """Set up Pulse Check from a config entry."""
    coordinator = PulseCheckCoordinator(hass, entry)
    # Compute once before the entities exist, so they never start empty.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PulseCheckConfigEntry) -> bool:
    """Unload a config entry.

    The coordinator's event listeners were registered with
    `entry.async_on_unload`, so Home Assistant removes them for us.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
