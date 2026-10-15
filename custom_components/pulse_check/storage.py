"""Persistent state: per-device settings, snoozes, notification state, history.

Home Assistant's `Store` writes a JSON file under `.storage/` and loads it
back on start. Everything the user tells Pulse Check (snooze this, that
device takes two AAs, notify me weekly about blinds) lives here, shared
by every browser and every card, and survives restarts.

The file holds one dict with a few top-level sections. Writes are
delayed by a couple of seconds so a burst of changes costs one save.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .core.models import as_utc, to_iso

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.data"
SAVE_DELAY_SECONDS = 2.0

# Per-device settings the core understands, plus the notification policy.
DEVICE_SETTING_KEYS = (
    "name",
    "area",
    "quiet_threshold_hours",
    "battery_type",
    "battery_count",
    "rechargeable",
    "notify_policy",
    # Only the card uses this one: its sparkline window for the device.
    "sparkline_days",
)


def _empty() -> dict[str, Any]:
    return {
        "device_settings": {},  # device id -> settings dict
        "snoozes": {},  # device id -> ISO timestamp the snooze ends
        "notify": {},  # device id -> issue key -> notification state
        "digests": {},  # "daily" / "weekly" -> ISO timestamp last judged
        "history": {},  # device id -> replacement history (phase 4)
        "levels": {},  # device id -> last observed battery level (phase 4)
    }


class PulseCheckStore:
    """The integration's saved state, with small typed accessors."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Create the store; nothing is read until `async_load`."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, Any] = _empty()

    async def async_load(self) -> None:
        """Read the file, keeping defaults for any section it lacks."""
        loaded = await self._store.async_load()
        if loaded:
            self.data = {**_empty(), **loaded}

    def async_save(self) -> None:
        """Write soon (delayed and coalesced)."""
        self._store.async_delay_save(lambda: self.data, SAVE_DELAY_SECONDS)

    # -- per-device settings -------------------------------------------------

    @property
    def device_settings(self) -> dict[str, dict[str, Any]]:
        """Every device's settings, keyed by device id."""
        return self.data["device_settings"]  # type: ignore[no-any-return]

    def update_device_settings(self, device_id: str, updates: Mapping[str, Any]) -> None:
        """Merge new values in. A `None` or empty value removes that setting."""
        current = dict(self.device_settings.get(device_id, {}))
        for key, value in updates.items():
            if key not in DEVICE_SETTING_KEYS:
                continue
            if value is None or value == "":
                current.pop(key, None)
            else:
                current[key] = value
        if current:
            self.device_settings[device_id] = current
        else:
            self.device_settings.pop(device_id, None)
        self.async_save()

    # -- snoozes -------------------------------------------------------------

    def snoozes(self, now: datetime) -> dict[str, datetime]:
        """Active snoozes as device id -> end time. Expired ones are dropped."""
        active: dict[str, datetime] = {}
        expired: list[str] = []
        for device_id, iso in self.data["snoozes"].items():
            until = as_utc(datetime.fromisoformat(iso))
            if until > as_utc(now):
                active[device_id] = until
            else:
                expired.append(device_id)
        for device_id in expired:
            del self.data["snoozes"][device_id]
        if expired:
            self.async_save()
        return active

    def snooze(self, device_id: str, until: datetime) -> None:
        """Mute a device until the given time."""
        self.data["snoozes"][device_id] = to_iso(until)
        self.async_save()

    def unsnooze(self, device_id: str) -> bool:
        """Lift a snooze. Returns False if there was none."""
        removed = self.data["snoozes"].pop(device_id, None) is not None
        if removed:
            self.async_save()
        return removed

    # -- other sections, used by the notifier and history tracking -----------

    @property
    def notify(self) -> dict[str, dict[str, Any]]:
        """Notification state per device (see notify.py)."""
        return self.data["notify"]  # type: ignore[no-any-return]

    @property
    def digests(self) -> dict[str, str]:
        """When each digest was last judged: sent, or found to have nothing to say."""
        return self.data["digests"]  # type: ignore[no-any-return]

    @property
    def history(self) -> dict[str, dict[str, Any]]:
        """Replacement and charge history per device (see replacements.py)."""
        return self.data["history"]  # type: ignore[no-any-return]

    @property
    def levels(self) -> dict[str, Any]:
        """Last observed battery level per device, for auto-detection."""
        return self.data["levels"]  # type: ignore[no-any-return]
