"""Constants shared across the integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "pulse_check"

# How long to wait after a state change before recomputing, so a burst of
# changes (a Zigbee device reporting five sensors at once) costs one run.
DEBOUNCE_SECONDS = 2.0

# Recompute on a timer too, so time-based transitions (a device going
# quiet, a snooze expiring) happen without waiting for a state change.
UPDATE_INTERVAL = timedelta(minutes=5)

# Attributes on the attention sensor. Kept out of the recorder (see
# sensor.py): the device list is large and changes often.
ATTR_DEVICES = "devices"
ATTR_SUMMARY = "summary"
ATTR_ACTIONS = "actions"
ATTR_COMPUTED_AT = "computed_at"
