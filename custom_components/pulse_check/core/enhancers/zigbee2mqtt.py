"""Zigbee2MQTT enhancer.

Zigbee2MQTT devices arrive through the `mqtt` integration. Two optional
sensors make them recognisable and tell us more than timestamps can:

  linkquality   0-255 LQI, present on every Z2M device. Below ~30 is a
                weak link worth a warning.
  last_seen     an ISO timestamp sensor, only present when the user turns
                on `advanced.last_seen` in Z2M. When it exists it is the
                true "last heard from", so we hand it to the core.

Plain MQTT devices without these sensors get nothing, which is correct.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..availability import parse_timestamp
from ..models import EnhancerExtra, js_round
from .base import (
    Enhancer,
    EnhancerResult,
    find_by_attribute,
    find_by_suffix,
    numeric_state,
)

if TYPE_CHECKING:
    from ..group import DeviceGroup
    from ..models import Snapshot

# LQI at or below this is flagged as a weak link.
WEAK_LQI = 30


class Zigbee2MqttEnhancer(Enhancer):
    """Reads Zigbee2MQTT's linkquality and last_seen sensors."""

    id = "zigbee2mqtt"
    platform = "mqtt"

    def enhance(self, group: DeviceGroup, snapshot: Snapshot) -> EnhancerResult:
        """An LQI extra and, when present, a last_seen timestamp."""
        result = EnhancerResult()

        lqi = numeric_state(
            find_by_suffix(group, "_linkquality")
            or find_by_attribute(group, "unit_of_measurement", "lqi")
        )
        if lqi is not None:
            result.extras.append(
                EnhancerExtra(
                    label="LQI",
                    value=str(js_round(lqi)),
                    severity="warning" if lqi <= WEAK_LQI else "ok",
                )
            )

        last_seen = find_by_suffix(group, "_last_seen")
        seen_at = parse_timestamp(last_seen["state"]) if last_seen is not None else None
        if seen_at is not None:
            result.last_heard = seen_at

        if not result.extras and result.last_heard is None:
            return EnhancerResult()
        return result
