"""The sensor platform.

Phase 1 provides one entity, `sensor.pulse_check_attention`: the number of
devices that need attention, with the full device list in its attributes
in the card's `DeviceHealth` shape. The plain count sensors arrive in
phase 2.

`CoordinatorEntity` ties an entity to the coordinator: whenever the
coordinator has new data, the entity's state is written again. The entity
itself holds no logic beyond picking fields out of `coordinator.data`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_ACTIONS, ATTR_COMPUTED_AT, ATTR_DEVICES, ATTR_SUMMARY, DOMAIN
from .coordinator import PulseCheckCoordinator
from .core.models import to_iso

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import PulseCheckConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulseCheckConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors for a config entry."""
    async_add_entities([AttentionSensor(entry.runtime_data, entry)])


class PulseCheckEntity(CoordinatorEntity[PulseCheckCoordinator]):
    """Base class: one "Pulse Check" service device holds every entity.

    `_attr_has_entity_name` makes Home Assistant compose the friendly name
    from the device name and the entity's translated name, so the entity
    below becomes "Pulse Check Attention" / `sensor.pulse_check_attention`.
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


class AttentionSensor(PulseCheckEntity, SensorEntity):
    """How many devices need attention, with the device list as attributes."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:heart-pulse"
    # The recorder would otherwise store the whole device list in the
    # database on every change. Only the count is worth keeping as history.
    _unrecorded_attributes = frozenset({ATTR_DEVICES, ATTR_SUMMARY, ATTR_ACTIONS, ATTR_COMPUTED_AT})

    def __init__(self, coordinator: PulseCheckCoordinator, entry: PulseCheckConfigEntry) -> None:
        """Create the attention sensor."""
        super().__init__(coordinator, entry, "attention")

    @property
    def native_value(self) -> int:
        """Devices that are warning or critical (snoozed ones excluded)."""
        return self.coordinator.data.summary.attention

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The full picture for cards and automations."""
        data = self.coordinator.data
        return {
            ATTR_DEVICES: [device.to_dict() for device in data.devices],
            ATTR_SUMMARY: data.summary.to_dict(),
            ATTR_ACTIONS: data.actions.to_dict(),
            ATTR_COMPUTED_AT: to_iso(data.computed_at),
        }
