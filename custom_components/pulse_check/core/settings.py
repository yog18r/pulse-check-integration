"""Looking up a device's per-device settings.

Entries are keyed by device id. A battery sensor with no device behind it
(a template or cloud sensor) is identified by its entity id instead, so
`device_id: sensor.inverter_soc` and `device_id: entity:sensor.inverter_soc`
both match the synthetic group the core builds for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .group import ORPHAN_PREFIX

if TYPE_CHECKING:
    from .models import CoreConfig, DeviceHealth, DeviceSettings


def is_charged(device: DeviceHealth, rechargeable: bool | None) -> bool:
    """Whether a device's battery gets charged rather than replaced.

    The user's setting wins (`rechargeable` True or False). Without one,
    what the history showed (`battery_kind`), and before there is any
    history, what the device is: a companion-app phone or a robot vacuum.
    Every place that says "charge" or "replace" asks this, so the Actions
    tab, the notification buttons and the replacement tracker agree.
    """
    if rechargeable is not None:
        return rechargeable
    if device.battery_kind is not None:
        return device.battery_kind == "charged"
    return device.integration == "mobile_app" or device.device_type == "vacuum"


def settings_for_device(config: CoreConfig, device_id: str) -> DeviceSettings | None:
    """The settings entry for a device id, matching orphans by bare entity id too."""
    bare_entity = (
        device_id.removeprefix(ORPHAN_PREFIX) if device_id.startswith(ORPHAN_PREFIX) else None
    )
    for entry in config.device_settings:
        if entry.device_id == device_id or (
            bare_entity is not None and entry.device_id == bare_entity
        ):
            return entry
    return None
