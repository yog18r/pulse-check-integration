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

# Battery history is re-read from the recorder this often. Drain rates move
# slowly, and the recorder's daily statistics only change once a day.
HISTORY_INTERVAL = timedelta(hours=6)
# Days of history the drain estimate is fitted over.
HISTORY_DAYS = 14

# Attributes on the attention sensor. Kept out of the recorder (see
# sensor.py): the device list is large and changes often.
ATTR_DEVICES = "devices"
ATTR_SUMMARY = "summary"
ATTR_ACTIONS = "actions"
ATTR_COMPUTED_AT = "computed_at"

# Options (Settings > Devices & services > Pulse Check > Configure).
# The keys match the card's YAML config so the two stay easy to compare.
CONF_BATTERY_WARNING = "battery_warning"
CONF_BATTERY_CRITICAL = "battery_critical"
CONF_QUIET_THRESHOLD_HOURS = "quiet_threshold_hours"
CONF_QUIET_SCOPE = "quiet_scope"
CONF_INTEGRATION_THRESHOLDS = "integration_thresholds"
CONF_INCLUDE_AREAS = "include_areas"
CONF_EXCLUDE_AREAS = "exclude_areas"
CONF_INCLUDE_INTEGRATIONS = "include_integrations"
CONF_EXCLUDE_INTEGRATIONS = "exclude_integrations"
CONF_EXCLUDE_DEVICES = "exclude_devices"
CONF_EXCLUDE_ENTITIES = "exclude_entities"

# Sub-keys of one integration threshold entry.
CONF_INTEGRATION = "integration"
CONF_HOURS = "hours"

DEFAULT_BATTERY_WARNING = 30
DEFAULT_BATTERY_CRITICAL = 15
DEFAULT_QUIET_THRESHOLD_HOURS = 24
DEFAULT_QUIET_SCOPE = "battery"
QUIET_SCOPES = ("battery", "all")

# Notifications (phase 3).
CONF_NOTIFY_TARGETS = "notify_targets"
CONF_NOTIFY_CRITICAL = "notify_critical"
CONF_NOTIFY_WARNING = "notify_warning"
CONF_REMINDER_DAYS = "reminder_days"
CONF_REMINDER_MAX = "reminder_max"
CONF_DIGEST_TIME = "digest_time"
CONF_DIGEST_WEEKDAY = "digest_weekday"
CONF_WEEKLY_ALL_CLEAR = "weekly_all_clear"

NOTIFY_POLICIES = ("instant", "daily", "weekly", "none")
DEFAULT_NOTIFY_CRITICAL = "instant"
DEFAULT_NOTIFY_WARNING = "weekly"
DEFAULT_REMINDER_DAYS = 3
DEFAULT_REMINDER_MAX = 3
DEFAULT_DIGEST_TIME = "09:00:00"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_DIGEST_WEEKDAY = "monday"

EVENT_TRANSITION = "pulse_check_transition"

# Entities (phase 4).
CONF_PER_DEVICE_SENSORS = "per_device_sensors"
