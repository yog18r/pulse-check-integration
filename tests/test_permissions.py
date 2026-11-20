"""Who may call what, and who sees what.

Home Assistant's own user groups: administrators, users and read-only
users. A user may also be given a policy that limits which entities they
may read; the websocket answers within it, as Home Assistant's states and
history do.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import probatio
import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.pulse_check.const import DOMAIN
from custom_components.pulse_check.services import SET_DEVICE_SETTINGS_SCHEMA
from tests.helpers import load_fixture_into_hass, start_integration


async def _user(hass: HomeAssistant) -> MockUser:
    """An ordinary, non-administrator user."""
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    return MockUser(groups=[group]).add_to_hass(hass)


async def _call(hass: HomeAssistant, user: MockUser, service: str, data: dict[str, Any]) -> None:
    await hass.services.async_call(
        DOMAIN, service, data, blocking=True, context=Context(user_id=user.id)
    )


# -- services -----------------------------------------------------------------


@pytest.mark.usefixtures("local_auth")
async def test_a_user_may_snooze_but_not_change_settings_or_ping(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The card offers snoozing to everyone; the rest is an administrator's."""
    _, device_ids = await start_integration(hass, fixture_snapshot, freezer, fixed_now)
    lock = device_ids["dev_zwave_lock"]
    user = await _user(hass)

    await _call(hass, user, "snooze", {"device_id": lock, "days": 1})
    await _call(hass, user, "unsnooze", {"device_id": lock})
    await _call(hass, user, "maintenance_mode", {"hours": 0})

    for service, data in (
        ("set_device_settings", {"device_id": lock, "notify_policy": "none"}),
        ("refresh", {}),
        ("ping", {"device_id": lock}),
    ):
        with pytest.raises(Unauthorized):
            await _call(hass, user, service, data)


async def test_a_read_only_user_may_not_snooze(
    hass: HomeAssistant,
    hass_read_only_user: MockUser,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    _, device_ids = await start_integration(hass, fixture_snapshot, freezer, fixed_now)
    lock = device_ids["dev_zwave_lock"]
    for service, data in (
        ("snooze", {"device_id": lock, "days": 1}),
        ("mark_replaced", {"device_id": lock}),
        ("maintenance_mode", {"hours": 2}),
    ):
        with pytest.raises(Unauthorized):
            await _call(hass, hass_read_only_user, service, data)


async def test_an_administrator_may_change_settings(
    hass: HomeAssistant,
    hass_admin_user: MockUser,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    entry, device_ids = await start_integration(hass, fixture_snapshot, freezer, fixed_now)
    lock = device_ids["dev_zwave_lock"]
    await _call(
        hass, hass_admin_user, "set_device_settings", {"device_id": lock, "battery_count": 2}
    )
    assert entry.runtime_data.store.device_settings[lock]["battery_count"] == 2


def test_a_battery_count_beyond_twenty_is_refused() -> None:
    """The settings form stops at 20; the service does too."""
    assert SET_DEVICE_SETTINGS_SCHEMA({"device_id": "dev_a", "battery_count": 20})
    with pytest.raises(probatio.Invalid):
        SET_DEVICE_SETTINGS_SCHEMA({"device_id": "dev_a", "battery_count": 21})


# -- the websocket ------------------------------------------------------------

# A watched battery of a device the limited user may not read.
OTHER_BATTERY = "sensor.living_room_motion_battery"


async def test_a_user_limited_to_some_entities_sees_only_those_devices(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    client = await hass_ws_client(hass)
    freezer.move_to(fixed_now)
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = config_entry.runtime_data
    kitchen = device_ids["dev_shelly_ht"]
    lock = device_ids["dev_zwave_lock"]
    watched = {d.battery.entity_id for d in coordinator.data.devices if d.battery is not None}
    assert {"sensor.kitchen_ht_battery", OTHER_BATTERY} <= watched
    coordinator.store.update_device_settings(kitchen, {"battery_type": "AAA"})
    coordinator.store.update_device_settings(lock, {"battery_type": "CR123A"})
    readable = set(coordinator.data.by_id[kitchen].entity_ids)
    readable.add("lock.front_door_lock")  # one of the lock's entities, not all
    hass_admin_user.mock_policy({"entities": {"entity_ids": dict.fromkeys(readable, True)}})

    await client.send_json({"id": 1, "type": "pulse_check/subscribe"})
    assert (await client.receive_json())["success"] is True
    payload = (await client.receive_json())["event"]
    assert [d["deviceId"] for d in payload["devices"]] == [kitchen]
    assert list(payload["device_settings"]) == [kitchen]
    # The counts are this user's: the offline lock is not among them.
    assert payload["summary"]["offline"] == 0
    assert payload["summary"]["attention"] == sum(d["severity"] != "ok" for d in payload["devices"])

    # History only for a battery they may read; another reads as not watched.
    await client.send_json(
        {"id": 2, "type": "pulse_check/history", "entity_id": "sensor.kitchen_ht_battery"}
    )
    assert (await client.receive_json())["success"] is True
    await client.send_json({"id": 3, "type": "pulse_check/history", "entity_id": OTHER_BATTERY})
    refused = await client.receive_json()
    assert refused["success"] is False
    assert refused["error"]["code"] == "unknown_entity"

    await client.send_json(
        {
            "id": 4,
            "type": "pulse_check/histories",
            "requests": [{"entity_id": "sensor.kitchen_ht_battery"}, {"entity_id": OTHER_BATTERY}],
        }
    )
    results = (await client.receive_json())["result"]["results"]
    assert "error" not in results[0]
    assert results[1]["error"] == "unknown_entity"
