"""The websocket API: the subscription and the history command."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.pulse_check.const import DEBOUNCE_SECONDS, DOMAIN, SIGNAL_SNAPSHOT
from tests.conftest import load_fixture_into_hass

BATTERY = {"device_class": "battery", "unit_of_measurement": "%"}


async def test_subscribe_sends_the_snapshot_now_and_after_each_recompute(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    golden: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    # The websocket client authenticates against real time; connect before freezing it.
    client = await hass_ws_client(hass)
    freezer.move_to(fixed_now)
    device_ids = await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await client.send_json({"id": 1, "type": "pulse_check/subscribe"})
    result = await client.receive_json()
    assert result["success"] is True

    first = await client.receive_json()
    assert first["type"] == "event"
    payload = first["event"]
    expected = golden["cases"][0]
    names = {d["name"] for d in payload["devices"]}
    assert names == {d["name"] for d in expected["devices"]}
    assert {k: payload["summary"][k] for k in expected["summary"]} == expected["summary"]
    assert payload["actions"]["shopping"] == expected["actions"]["shopping"]
    assert payload["config"]["battery_warning"] == 30
    assert payload["config"]["battery_critical"] == 15
    assert payload["device_settings"] == {}
    assert payload["computed_at"] == "2026-10-15T10:00:00.000Z"
    assert device_ids["dev_zwave_lock"] in {d["deviceId"] for d in payload["devices"]}

    # A state change: one more event after the debounce, with the new level.
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    freezer.tick(timedelta(seconds=DEBOUNCE_SECONDS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    second = await client.receive_json()
    kitchen = next(d for d in second["event"]["devices"] if d["name"] == "Kitchen H&T")
    assert kitchen["battery"]["level"] == 5
    assert kitchen["severity"] == "critical"

    # Settings changed through the service reach the snapshot too.
    await hass.services.async_call(
        DOMAIN,
        "set_device_settings",
        {
            "device_id": device_ids["dev_shelly_ht"],
            "battery_type": "AAA",
            "notify_policy": "none",
            "sparkline_days": 3,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    third = await client.receive_json()
    assert third["event"]["device_settings"] == {
        device_ids["dev_shelly_ht"]: {
            "battery_type": "AAA",
            "notify_policy": "none",
            "sparkline_days": 3,
        }
    }

    await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": 1})
    assert (await client.receive_json())["success"] is True
    await client.close()


async def test_a_subscription_survives_saving_options(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Saving options reloads the entry; subscribers must get the new snapshot."""
    client = await hass_ws_client(hass)
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await client.send_json({"id": 1, "type": "pulse_check/subscribe"})
    assert (await client.receive_json())["success"] is True
    first = await client.receive_json()
    assert "Pixel 9" in {d["name"] for d in first["event"]["devices"]}

    # Other recomputes send snapshots too, at moments no test controls: the
    # battery history refresh finishes in the background. Send one here, so
    # the test proves it finds the snapshot from after the save regardless.
    async_dispatcher_send(hass, SIGNAL_SNAPSHOT)
    await hass.async_block_till_done()

    # The Configure dialog excludes phones. OptionsFlowWithReload reloads the entry.
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"filters": {"exclude_integrations": ["mobile_app"]}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # Snapshots arrive in order; the reload's comes after any sent before it.
    for _ in range(5):
        names = {d["name"] for d in (await client.receive_json())["event"]["devices"]}
        if "Pixel 9" not in names:
            break
    assert "Pixel 9" not in names
    assert "Front Door Lock" in names
    # And the sensors moved with it, without a restart.
    attention = hass.states.get("sensor.pulse_check_attention")
    assert attention is not None
    assert attention.attributes["summary"]["batteryDevices"] == 11
    await client.close()


async def test_subscribe_without_a_loaded_entry_is_an_error(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, config_entry: MockConfigEntry
) -> None:
    """The commands exist once the integration is set up, even with its entry unloaded."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "pulse_check/subscribe"})
    result = await client.receive_json()
    assert result["success"] is False
    assert result["error"]["code"] == "not_loaded"
    await client.close()


async def test_history_rejects_entities_that_are_not_batteries(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    client = await hass_ws_client(hass)
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await client.send_json(
        {"id": 1, "type": "pulse_check/history", "entity_id": "light.garage_lights", "days": 7}
    )
    result = await client.receive_json()
    assert result["success"] is False
    assert result["error"]["code"] == "unknown_entity"

    # Without a recorder there is simply no history.
    await client.send_json(
        {"id": 2, "type": "pulse_check/history", "entity_id": "sensor.kitchen_ht_battery"}
    )
    result = await client.receive_json()
    assert result["success"] is True
    assert result["result"] == {
        "entity_id": "sensor.kitchen_ht_battery",
        "days": 14,
        "points": [],
        "estimate": None,
    }
    await client.close()


async def _loaded(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    freezer.move_to(fixed_now)
    await load_fixture_into_hass(hass, fixture_snapshot)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_the_snapshot_carries_the_installed_version(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """The card compares it with its own to tell when the page needs a refresh."""
    client = await hass_ws_client(hass)
    await _loaded(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    integration = await async_get_integration(hass, DOMAIN)
    await client.send_json({"id": 1, "type": "pulse_check/subscribe"})
    assert (await client.receive_json())["success"] is True
    event = (await client.receive_json())["event"]
    assert event["version"] == str(integration.version)
    await client.close()


async def test_histories_answer_many_batteries_in_one_request(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    client = await hass_ws_client(hass)
    await _loaded(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    await client.send_json(
        {
            "id": 1,
            "type": "pulse_check/histories",
            "requests": [
                {"entity_id": "sensor.kitchen_ht_battery"},
                {"entity_id": "light.garage_lights", "days": 7},
                {"entity_id": "sensor.front_door_battery", "days": 30},
            ],
        }
    )
    result = await client.receive_json()
    assert result["success"] is True
    # In the order asked; a non-battery gets an error, not a failed request.
    assert result["result"]["results"] == [
        {"entity_id": "sensor.kitchen_ht_battery", "days": 14, "points": [], "estimate": None},
        {"entity_id": "light.garage_lights", "days": 7, "error": "unknown_entity"},
        {"entity_id": "sensor.front_door_battery", "days": 30, "points": [], "estimate": None},
    ]
    await client.close()


async def test_histories_ask_the_recorder_once_per_window(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    config_entry: MockConfigEntry,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Three batteries over two window lengths: two recorder queries, not three."""
    client = await hass_ws_client(hass)
    await _loaded(hass, config_entry, fixture_snapshot, freezer, fixed_now)
    tracker = type(config_entry.runtime_data.history)
    means = AsyncMock(return_value={})
    with (
        patch.object(tracker, "available", new_callable=PropertyMock, return_value=True),
        patch.object(tracker, "_means", means),
    ):
        await client.send_json(
            {
                "id": 1,
                "type": "pulse_check/histories",
                "requests": [
                    {"entity_id": "sensor.kitchen_ht_battery", "days": 14},
                    {"entity_id": "sensor.front_door_battery", "days": 14},
                    {"entity_id": "sensor.window_sensor_battery", "days": 30},
                ],
            }
        )
        assert (await client.receive_json())["success"] is True
    asked = sorted((call.args[2], sorted(call.args[0])) for call in means.await_args_list)
    assert asked == [
        (14, ["sensor.front_door_battery", "sensor.kitchen_ht_battery"]),
        (30, ["sensor.window_sensor_battery"]),
    ]
    await client.close()
