"""ZHA enhancer.

ZHA can expose two diagnostic sensors per device (disabled by default,
users enable them in the entity settings):

  lqi    0-255 link quality, same scale as Zigbee2MQTT
  rssi   signal strength in dBm, typically -40 (great) to -90 (poor)

We show whichever exist and warn on a weak LQI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import EnhancerExtra, js_round
from .base import Enhancer, EnhancerResult, find_by_suffix, numeric_state
from .zigbee2mqtt import WEAK_LQI

if TYPE_CHECKING:
    from ..group import DeviceGroup
    from ..models import Snapshot


class ZhaEnhancer(Enhancer):
    """Reads ZHA's lqi and rssi diagnostic sensors."""

    id = "zha"
    platform = "zha"

    def enhance(self, group: DeviceGroup, snapshot: Snapshot) -> EnhancerResult:
        """LQI and RSSI extras when the sensors exist."""
        extras: list[EnhancerExtra] = []

        lqi = numeric_state(find_by_suffix(group, "_lqi"))
        if lqi is not None:
            extras.append(
                EnhancerExtra(
                    label="LQI",
                    value=str(js_round(lqi)),
                    severity="warning" if lqi <= WEAK_LQI else "ok",
                )
            )

        rssi = numeric_state(find_by_suffix(group, "_rssi"))
        if rssi is not None:
            extras.append(EnhancerExtra(label="RSSI", value=f"{js_round(rssi)} dBm"))

        return EnhancerResult(extras=extras) if extras else EnhancerResult()
