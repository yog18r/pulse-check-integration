"""The websocket API the card talks to.

Home Assistant's frontend keeps one websocket open to the server; cards
can send commands over it and subscribe to events. Two commands live
here:

- `pulse_check/subscribe`: sends the full computed snapshot at once and
  again after every recompute. The card renders exactly this, nothing
  more; it never analyses anything itself.
- `pulse_check/history`: battery history points for one entity over a
  window of days, for the card's sparklines, read from the recorder on
  the server so the browser never queries the recorder.

The snapshot is the same data the sensors are built from, serialised in
the card's `DeviceHealth` shape. Keeping it off the sensor's attributes
means the state machine and the recorder are not carrying a large,
frequently changing payload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import async_response, websocket_command
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .core.models import to_iso

if TYPE_CHECKING:
    from .coordinator import PulseCheckCoordinator, PulseCheckData

ERR_NOT_LOADED = "not_loaded"
ERR_UNKNOWN_ENTITY = "unknown_entity"
MAX_HISTORY_DAYS = 365


@callback
def _coordinator(hass: HomeAssistant) -> PulseCheckCoordinator | None:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: PulseCheckCoordinator = entry.runtime_data
        return coordinator
    return None


def snapshot_payload(coordinator: PulseCheckCoordinator) -> dict[str, Any]:
    """Everything the card needs, JSON-ready."""
    data: PulseCheckData = coordinator.data
    return {
        "devices": [device.to_dict() for device in data.devices],
        "summary": data.summary.to_dict(),
        "actions": data.actions.to_dict(),
        "config": data.config.to_dict(),
        # The raw per-device settings, including notify_policy, which the
        # core does not use but the card's editor shows.
        "device_settings": coordinator.store.device_settings,
        "computed_at": to_iso(data.computed_at),
    }


@websocket_command({probatio.Required("type"): "pulse_check/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the snapshot now and after every recompute until unsubscribed."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "Pulse Check is not set up")
        return

    @callback
    def send() -> None:
        connection.send_message(event_message(msg["id"], snapshot_payload(coordinator)))

    connection.subscriptions[msg["id"]] = coordinator.async_add_listener(send)
    connection.send_result(msg["id"])
    send()


@websocket_command(
    {
        probatio.Required("type"): "pulse_check/history",
        probatio.Required("entity_id"): str,
        probatio.Optional("days", default=14): probatio.All(
            int, probatio.Range(min=1, max=MAX_HISTORY_DAYS)
        ),
    }
)
@async_response
async def ws_history(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Battery history points for one of the watched battery entities."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "Pulse Check is not set up")
        return
    entity_id: str = msg["entity_id"]
    battery = next(
        (
            device.battery
            for device in coordinator.data.devices
            if device.battery is not None and device.battery.entity_id == entity_id
        ),
        None,
    )
    if battery is None:
        connection.send_error(
            msg["id"], ERR_UNKNOWN_ENTITY, f"{entity_id} is not a watched battery"
        )
        return
    history = await coordinator.history.async_points(
        entity_id, msg["days"], attribute=battery.source == "attribute"
    )
    estimate = coordinator.history.estimates.get(entity_id)
    connection.send_result(
        msg["id"],
        {
            "entity_id": entity_id,
            "days": msg["days"],
            "points": [
                {"time": int(point.time.timestamp() * 1000), "level": point.level}
                for point in history
            ],
            "estimate": (
                {
                    "ratePerDay": estimate.rate_per_day,
                    "daysLeft": estimate.days_left,
                    "samples": estimate.samples,
                }
                if estimate is not None
                else None
            ),
        },
    )


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the commands. Called once from `async_setup`."""
    async_register_command(hass, ws_subscribe)
    async_register_command(hass, ws_history)
