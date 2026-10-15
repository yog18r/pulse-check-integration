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
    from .models import CoreConfig, DeviceSettings


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
