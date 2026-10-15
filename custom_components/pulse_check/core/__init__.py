"""The pure Python core of Pulse Check.

Nothing in this package imports Home Assistant. It takes a plain snapshot
of states and registries (see `models.Snapshot`), applies the detection
rules, and returns one `DeviceHealth` per physical device. That makes it
testable with a JSON fixture. It began as a line-for-line port of the
card's original TypeScript rules (see the history of `frontend/src/core`)
and is checked against the golden output they produced.
"""

from .actions import ActionItem, ActionList, ShoppingLine, action_list
from .analyse import analyse_devices
from .drain import DrainEstimate, DrainPoint, estimate_drain
from .models import (
    BatteryReading,
    CoreConfig,
    DeviceHealth,
    DeviceSettings,
    EnhancerExtra,
    Severity,
    Snapshot,
)
from .summarise import Summary, summarise

__all__ = [
    "ActionItem",
    "ActionList",
    "BatteryReading",
    "CoreConfig",
    "DeviceHealth",
    "DeviceSettings",
    "DrainEstimate",
    "DrainPoint",
    "EnhancerExtra",
    "Severity",
    "ShoppingLine",
    "Snapshot",
    "Summary",
    "action_list",
    "analyse_devices",
    "estimate_drain",
    "summarise",
]
