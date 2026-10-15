"""Enhancer registry.

The universal rules only use data every integration provides. An enhancer
adds integration-specific detail when, and only when, the data exists. It
must never raise and never make a device disappear: returning an empty
result is always a valid answer.

To add support for a new integration, implement `Enhancer` in a new file
and add it to `ENHANCERS`. Nothing else changes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import Enhancer, EnhancerResult
from .zha import ZhaEnhancer
from .zigbee2mqtt import Zigbee2MqttEnhancer
from .zwave_js import ZwaveJsEnhancer

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..group import DeviceGroup
    from ..models import Snapshot

_LOGGER = logging.getLogger(__name__)

# Add new enhancers here. Order only affects the order of extras on a device.
ENHANCERS: tuple[Enhancer, ...] = (ZwaveJsEnhancer(), Zigbee2MqttEnhancer(), ZhaEnhancer())

__all__ = ["ENHANCERS", "Enhancer", "EnhancerResult", "apply_enhancers"]


def apply_enhancers(
    enhancers: Iterable[Enhancer], integration: str, group: DeviceGroup, snapshot: Snapshot
) -> EnhancerResult:
    """Merge the results of every enhancer that matches the device's integration.

    Each call is wrapped so a bug in one enhancer can never break the
    whole analysis: it is logged and the device is analysed without it.
    """
    merged = EnhancerResult()
    for enhancer in enhancers:
        if enhancer.platform != integration:
            continue
        try:
            result = enhancer.enhance(group, snapshot)
        except Exception:
            _LOGGER.warning(
                "Enhancer %s failed for %s", enhancer.id, group.device_id, exc_info=True
            )
            continue
        merged.extras.extend(result.extras)
        if result.offline:
            merged.offline = True
        if result.last_heard is not None and (
            merged.last_heard is None or result.last_heard > merged.last_heard
        ):
            merged.last_heard = result.last_heard
    return merged
