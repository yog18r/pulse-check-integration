"""The binary sensor platform: `binary_sensor.pulse_check_problem`.

On when any device needs attention. The simplest thing to put in an
automation or on a dashboard tile. Maintenance mode is a switch (see
`switch.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass

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
    async_add_entities([ProblemBinarySensor(entry.runtime_data, entry)])


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
