"""The switch platform: `switch.pulse_check_maintenance_mode`.

The same maintenance mode as the `pulse_check.maintenance_mode` service,
as a toggle on the Pulse Check device page and for dashboards. Turning it
on starts a window of the default length from the options; turning it off
ends the window now, which sends the end-of-window summary. For a window of
another length, call the service with `hours`.

The state is read from the store, so the switch follows the service, an
extension, a restart, and the window running out on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.util import dt as dt_util

from .const import CONF_MAINTENANCE_HOURS, DEFAULT_MAINTENANCE_HOURS
from .core.models import to_iso
from .entity import PulseCheckEntity
from .services import async_set_maintenance

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import PulseCheckConfigEntry
    from .coordinator import PulseCheckCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulseCheckConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the maintenance mode switch for a config entry."""
    async_add_entities([MaintenanceSwitch(entry.runtime_data, entry)])


class MaintenanceSwitch(PulseCheckEntity, SwitchEntity):
    """On while maintenance mode holds notifications back."""

    def __init__(self, coordinator: PulseCheckCoordinator, entry: PulseCheckConfigEntry) -> None:
        """Create the maintenance mode switch."""
        super().__init__(coordinator, entry, "maintenance_mode")
        self._entry = entry

    @property
    def is_on(self) -> bool:
        """True while the window is open."""
        return self.coordinator.store.in_maintenance(dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """When the window ends, while it is open."""
        until = self.coordinator.store.maintenance_until
        return {"until": to_iso(until)} if self.is_on and until is not None else {}

    async def async_turn_on(self, **kwargs: object) -> None:
        """Start a window of the default length, or restart the clock on one."""
        hours = float(self._entry.options.get(CONF_MAINTENANCE_HOURS, DEFAULT_MAINTENANCE_HOURS))
        await async_set_maintenance(self.coordinator, hours)

    async def async_turn_off(self, **kwargs: object) -> None:
        """End the window now."""
        await async_set_maintenance(self.coordinator, 0)
