"""Z-Wave JS enhancer.

Z-Wave JS gives every node a diagnostic "Node status" sensor with one of
the states: alive, awake, asleep, dead, unknown. That is a far better
liveness signal than timestamps:

  dead    the controller has given up on the node    -> offline, critical
  asleep  normal for battery devices between wakeups -> informational
  alive / awake                                      -> informational
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import EnhancerExtra, Severity
from .base import Enhancer, EnhancerResult, find_by_suffix

if TYPE_CHECKING:
    from ..group import DeviceGroup
    from ..models import Snapshot

_KNOWN_STATUSES = frozenset({"alive", "awake", "asleep", "dead", "unknown"})


class ZwaveJsEnhancer(Enhancer):
    """Reads the Z-Wave JS node status sensor."""

    id = "zwave-js"
    platform = "zwave_js"

    def enhance(self, group: DeviceGroup, snapshot: Snapshot) -> EnhancerResult:
        """A Node extra, and offline when the node is dead."""
        status = find_by_suffix(group, "_node_status")
        if status is None or status["state"] not in _KNOWN_STATUSES:
            return EnhancerResult()
        dead = status["state"] == "dead"
        severity: Severity = "critical" if dead else "ok"
        extra = EnhancerExtra(label="Node", value=status["state"], severity=severity)
        return EnhancerResult(extras=[extra], offline=dead)
