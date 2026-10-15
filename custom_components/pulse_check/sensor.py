"""The sensor platform.

- `sensor.pulse_check_attention`: devices needing attention, with the
  summary counts as attributes. The full device list goes over the
  websocket (see websocket.py), not through state attributes.
- `sensor.pulse_check_low_batteries`, `_critical_batteries`, `_offline`,
  `_quiet`: plain counts for automations that only care about one kind.
- `sensor.pulse_check_next_to_run_out`: the battery device with the fewest
  days left according to its drain estimate.
- Optionally, on every battery device itself (diagnostic category):
  "Battery days left" and "Battery last replaced". These are attached to
  the device's own registry entry, so they appear on its device page.

The entities hold no logic beyond picking fields out of `coordinator.data`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_COMPUTED_AT, ATTR_SUMMARY, CONF_PER_DEVICE_SENSORS
from .coordinator import PulseCheckCoordinator
from .core.models import to_iso
from .entity import PulseCheckEntity

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import PulseCheckConfigEntry
    from .coordinator import PulseCheckData
    from .core import DeviceHealth


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

    if not entry.options.get(CONF_PER_DEVICE_SENSORS, False):
        return

    # Per-device sensors: one pair per battery device that has a registry
    # entry. Devices can appear later (a new sensor paired tomorrow), so
    # every coordinator update checks for ones we have not seen.
    known: set[str] = set()
    registry = dr.async_get(hass)

    @callback
    def _add_new_devices() -> None:
        new: list[SensorEntity] = []
        for device in coordinator.data.devices:
            if device.device_id in known or device.battery is None:
                continue
            entry_in_registry = registry.async_get(device.device_id)
            if not isinstance(entry_in_registry, dr.DeviceEntry):
                continue  # an entity:<id> orphan has no device page
            known.add(device.device_id)
            target = entry_in_registry
            new.append(DeviceDaysLeftSensor(coordinator, entry, device.device_id, target))
            new.append(DeviceLastReplacedSensor(coordinator, entry, device.device_id, target))
        if new:
            async_add_entities(new)

    _add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))


class AttentionSensor(PulseCheckEntity, SensorEntity):
    """How many devices need attention, with the summary counts as attributes."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:heart-pulse"
    # Only the count is worth keeping as history.
    _unrecorded_attributes = frozenset({ATTR_SUMMARY, ATTR_COMPUTED_AT})

    def __init__(self, coordinator: PulseCheckCoordinator, entry: PulseCheckConfigEntry) -> None:
        """Create the attention sensor."""
        super().__init__(coordinator, entry, "attention")

    @property
    def native_value(self) -> int:
        """Devices that are warning or critical (snoozed ones excluded)."""
        return self.coordinator.data.summary.attention

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The summary counts, for automations that want more than the state."""
        data = self.coordinator.data
        return {
            ATTR_SUMMARY: data.summary.to_dict(),
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


class PerDeviceSensor(CoordinatorEntity[PulseCheckCoordinator], SensorEntity):
    """A diagnostic sensor that lives on the watched device, not on Pulse Check."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: PulseCheckCoordinator,
        entry: PulseCheckConfigEntry,
        device_id: str,
        target: dr.DeviceEntry,
        key: str,
    ) -> None:
        """Attach to the watched device.

        Setting `device_entry` links the entity to a device that belongs to
        another integration without taking that device over (passing the
        device's identifiers as `device_info` would do that, and is
        deprecated for exactly this reason).
        """
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_{key}"
        self._attr_translation_key = f"device_{key}"
        self.device_entry = target

    @property
    def device(self) -> DeviceHealth | None:
        """This device's latest analysis, if it is still watched."""
        for device in self.coordinator.data.devices:
            if device.device_id == self.device_id:
                return device
        return None

    @property
    def available(self) -> bool:
        """Unavailable once the device is filtered out or gone."""
        return super().available and self.device is not None


class DeviceDaysLeftSensor(PerDeviceSensor):
    """Days until the battery is empty at its current drain rate."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:battery-clock"

    def __init__(
        self,
        coordinator: PulseCheckCoordinator,
        entry: PulseCheckConfigEntry,
        device_id: str,
        target: dr.DeviceEntry,
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, entry, device_id, target, "days_left")

    @property
    def native_value(self) -> float | None:
        """Days left, or unknown without enough history."""
        device = self.device
        return round(device.days_left, 1) if device and device.days_left is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The level the estimate is based on, and any unusual-behaviour note."""
        device = self.device
        if device is None or device.battery is None:
            return {}
        return {"level": device.battery.level, "unusual": device.unusual}


class DeviceLastReplacedSensor(PerDeviceSensor):
    """When the battery was last replaced or charged, with cycle statistics."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:battery-sync"

    def __init__(
        self,
        coordinator: PulseCheckCoordinator,
        entry: PulseCheckConfigEntry,
        device_id: str,
        target: dr.DeviceEntry,
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, entry, device_id, target, "last_replaced")

    @property
    def native_value(self) -> datetime | None:
        """The last replacement or charge, or unknown if never recorded."""
        device = self.device
        return device.last_replaced if device else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """How many cycles are on record and how they went."""
        tracker = self.coordinator.replacements
        last = tracker.last_event(self.device_id) or {}
        return {
            "kind": last.get("kind"),
            "battery_type": last.get("battery_type"),
            "auto_detected": last.get("auto"),
            **tracker.cycle_stats(self.device_id),
        }
