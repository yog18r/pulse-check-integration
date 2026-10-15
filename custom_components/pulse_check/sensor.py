"""The sensor platform.

- `sensor.pulse_check_attention`: devices needing attention, with the full
  device list in its attributes in the card's `DeviceHealth` shape.
- `sensor.pulse_check_low_batteries`, `_critical_batteries`, `_offline`,
  `_quiet`: plain counts for automations that only care about one kind.
- `sensor.pulse_check_next_to_run_out`: the battery device with the fewest
  days left according to its drain estimate.

The entities hold no logic beyond picking fields out of `coordinator.data`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)

from .const import ATTR_ACTIONS, ATTR_COMPUTED_AT, ATTR_DEVICES, ATTR_SUMMARY
from .core.models import to_iso
from .entity import PulseCheckEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import PulseCheckConfigEntry
    from .coordinator import PulseCheckCoordinator, PulseCheckData


@dataclass(frozen=True, kw_only=True)
class PulseCheckCountDescription(SensorEntityDescription):
    """Describes one count sensor: which number to show."""

    value_fn: Callable[[PulseCheckData], int]


COUNT_SENSORS: tuple[PulseCheckCountDescription, ...] = (
    PulseCheckCountDescription(
        key="low_batteries",
        translation_key="low_batteries",
        icon="mdi:battery-30",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.summary.low_batteries,
    ),
    PulseCheckCountDescription(
        key="critical_batteries",
        translation_key="critical_batteries",
        icon="mdi:battery-alert",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.summary.critical_batteries,
    ),
    PulseCheckCountDescription(
        key="offline",
        translation_key="offline",
        icon="mdi:lan-disconnect",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.summary.offline,
    ),
    PulseCheckCountDescription(
        key="quiet",
        translation_key="quiet",
        icon="mdi:sleep",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.summary.quiet,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulseCheckConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            AttentionSensor(coordinator, entry),
            NextToRunOutSensor(coordinator, entry),
            *(CountSensor(coordinator, entry, description) for description in COUNT_SENSORS),
        ]
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


class CountSensor(PulseCheckEntity, SensorEntity):
    """One plain count."""

    entity_description: PulseCheckCountDescription

    def __init__(
        self,
        coordinator: PulseCheckCoordinator,
        entry: PulseCheckConfigEntry,
        description: PulseCheckCountDescription,
    ) -> None:
        """Create a count sensor from its description."""
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int:
        """The count this sensor describes."""
        return self.entity_description.value_fn(self.coordinator.data)


class NextToRunOutSensor(PulseCheckEntity, SensorEntity):
    """The device whose battery will run out soonest, by drain estimate."""

    _attr_icon = "mdi:battery-clock"

    def __init__(self, coordinator: PulseCheckCoordinator, entry: PulseCheckConfigEntry) -> None:
        """Create the sensor."""
        super().__init__(coordinator, entry, "next_to_run_out")

    @property
    def native_value(self) -> str | None:
        """The device name, or unknown when no battery has an estimate yet."""
        device = self.coordinator.data.next_to_run_out
        return device.name if device is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Days left and which device it is."""
        device = self.coordinator.data.next_to_run_out
        if device is None or device.battery is None or device.days_left is None:
            return {}
        return {
            "days_left": round(device.days_left, 1),
            "device_id": device.device_id,
            "entity_id": device.battery.entity_id,
            "level": device.battery.level,
        }
