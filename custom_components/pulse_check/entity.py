"""The base entity every platform shares."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PulseCheckCoordinator

if TYPE_CHECKING:
    from . import PulseCheckConfigEntry


class PulseCheckEntity(CoordinatorEntity[PulseCheckCoordinator]):
    """Base class: one "Pulse Check" service device holds every entity.

    `CoordinatorEntity` ties an entity to the coordinator: whenever the
    coordinator has new data, the entity's state is written again.
    `_attr_has_entity_name` makes Home Assistant compose the friendly name
    from the device name and the entity's translated name, so a key of
    "attention" becomes "Pulse Check Attention" / `sensor.pulse_check_attention`.
    """

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PulseCheckCoordinator, entry: PulseCheckConfigEntry, key: str
    ) -> None:
        """Set the unique id, translation key and device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Pulse Check",
            entry_type=DeviceEntryType.SERVICE,
        )
