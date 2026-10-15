"""The binary sensor platform.

- `binary_sensor.pulse_check_problem`: on when any device needs
  attention. The simplest thing to put in an automation or on a
  dashboard tile.
- `binary_sensor.pulse_check_maintenance_mode`: on while maintenance mode
  holds notifications back, with the end time as an attribute.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.util import dt as dt_util

from .core.models import to_iso
from .entity import PulseCheckEntity

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
    """Create the binary sensor for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [ProblemBinarySensor(coordinator, entry), MaintenanceBinarySensor(coordinator, entry)]
    )


class ProblemBinarySensor(PulseCheckEntity, BinarySensorEntity):
    """On when at least one device is warning or critical."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: PulseCheckCoordinator, entry: PulseCheckConfigEntry) -> None:
        """Create the problem sensor."""
        super().__init__(coordinator, entry, "problem")

    @property
    def is_on(self) -> bool:
        """True when anything needs attention."""
        return self.coordinator.data.summary.attention > 0


class MaintenanceBinarySensor(PulseCheckEntity, BinarySensorEntity):
    """On while maintenance mode is active.

    It changes only when the window starts or ends. The service and the
    end-of-window timer both recompute, which writes the new state.
    """

    def __init__(self, coordinator: PulseCheckCoordinator, entry: PulseCheckConfigEntry) -> None:
        """Create the maintenance mode sensor."""
        super().__init__(coordinator, entry, "maintenance_mode")

    @property
    def is_on(self) -> bool:
        """True while the window is open."""
        return self.coordinator.store.in_maintenance(dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """When the window ends, while it is open."""
        until = self.coordinator.store.maintenance_until
        return {"until": to_iso(until)} if self.is_on and until is not None else {}
