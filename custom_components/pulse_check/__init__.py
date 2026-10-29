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
- The dashboard card ships inside the integration (see `card.py`), which
  serves it and adds it to the dashboards' resources.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .card import async_remove_card_resource, async_serve_card, async_setup_card
from .const import DOMAIN, SIGNAL_SNAPSHOT
from .coordinator import PulseCheckCoordinator
from .messages import async_load_messages
from .notify import Notifier
from .services import async_setup_services
from .websocket import async_setup_websocket

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

# Pulse Check is set up from the UI only; there is no YAML configuration.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The coordinator is attached to the entry as `runtime_data`, which is how
# Home Assistant recommends sharing per-entry objects with the platforms.
type PulseCheckConfigEntry = ConfigEntry[PulseCheckCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once, whether or not an entry exists yet."""
    async_setup_services(hass)
    async_setup_websocket(hass)
    # Serve the card file now, not at the end of entry setup: a dashboard
    # opened while Home Assistant starts can then load the card at all.
    await async_serve_card(hass)
    return True


@callback
def _remove_maintenance_binary_sensor(hass: HomeAssistant, entry: PulseCheckConfigEntry) -> None:
    """0.2.0 had maintenance mode as a binary sensor; it is a switch since 0.2.1.

    Without this the old entity would linger in the registry as
    "no longer provided" next to the new switch.
    """
    registry = er.async_get(hass)
    old = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_maintenance_mode"
    )
    if old is not None:
        registry.async_remove(old)


async def async_setup_entry(hass: HomeAssistant, entry: PulseCheckConfigEntry) -> bool:
    """Set up Pulse Check from a config entry."""
    coordinator = PulseCheckCoordinator(hass, entry)
    await coordinator.store.async_load()
    coordinator.rebuild_config()
    # Compute once before the entities exist, so they never start empty.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # The websocket commands find the current coordinator here, so a reload
    # (which is how saved options take effect) swaps it under them.
    hass.data[DOMAIN] = coordinator
    _remove_maintenance_binary_sensor(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Notifications react to every recompute from here on.
    notifier = Notifier(hass, entry, coordinator, await async_load_messages(hass))
    notifier.async_setup()

    # Tell websocket subscribers about every recompute, and about this one.
    entry.async_on_unload(
        coordinator.async_add_listener(lambda: async_dispatcher_send(hass, SIGNAL_SNAPSHOT))
    )
    async_dispatcher_send(hass, SIGNAL_SNAPSHOT)

    # Serve the card and keep its dashboard resource current. This runs on
    # every setup, so an update to a new version refreshes the resource.
    await async_setup_card(hass)

    # Battery history is slower (database reads), so it loads in the
    # background after the entities exist and refreshes them when done.
    # At boot it waits for Home Assistant to finish starting: before that
    # the recorder may not have its statistics ready and restored states
    # are still settling, which once gave one answer at startup and
    # another at the next refresh.

    @callback
    def _start_history(_event: Event | None = None) -> None:
        entry.async_create_background_task(
            hass, coordinator.async_refresh_history(), "pulse_check history"
        )

    if hass.is_running:
        _start_history()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start_history)
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PulseCheckConfigEntry) -> bool:
    """Unload a config entry.

    The coordinator's and notifier's listeners were registered with
    `entry.async_on_unload`, so Home Assistant removes them for us. Saving
    options in the Configure dialog unloads and sets up the entry again
    (`OptionsFlowWithReload`), which is how new thresholds and filters take
    effect; the notifier then starts from a fresh baseline.
    """
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.pop(DOMAIN, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: PulseCheckConfigEntry) -> None:
    """Clean up when the integration is deleted (not on reload or restart)."""
    await async_remove_card_resource(hass)
