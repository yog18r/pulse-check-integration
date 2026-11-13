"""Asking a device that is about to be quiet whether it is still there."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulse_check.const import CONF_PING_QUIET
from custom_components.pulse_check.coordinator import PulseCheckCoordinator
from custom_components.pulse_check.ping import async_ping_device, device_address

from .helpers import BATTERY

PING_ADDRESS = "custom_components.pulse_check.ping._ping_address"
ZWAVE_NODE = "custom_components.pulse_check.ping._zwave_node"


def _device(
    hass: HomeAssistant,
    owner: MockConfigEntry,
    key: str,
    *,
    url: str | None = None,
    via: dr.DeviceEntry | None = None,
) -> dr.DeviceEntry:
    """A device of `owner` with a battery sensor, `sensor.<key>_battery`."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={(owner.domain, key)},
        name=key.title(),
        configuration_url=url,
        via_device_id=via.id if via is not None else None,
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        owner.domain,
        f"{key}_battery",
        suggested_object_id=f"{key}_battery",
        device_id=device.id,
        config_entry=owner,
    )
    hass.states.async_set(f"sensor.{key}_battery", "80", BATTERY)
    return device


def _owner(hass: HomeAssistant, domain: str = "shelly", **data: str) -> MockConfigEntry:
    entry = MockConfigEntry(domain=domain, data=data)
    entry.add_to_hass(hass)
    return entry


# -- where the address comes from ---------------------------------------------


@pytest.mark.parametrize(
    ("url", "address"),
    [
        ("http://192.168.1.50", "192.168.1.50"),
        ("http://192.168.1.50:8080/settings", "192.168.1.50"),
        ("http://[fd00::50]/", "fd00::50"),
        # A cloud service's page, or a name: never taken for the device.
        ("https://www.ecovacs.com", None),
        ("http://8.8.8.8", None),
        ("http://shelly-ht.local", None),
        ("homeassistant://config/zwave_js", None),
    ],
)
async def test_the_configuration_link_gives_a_private_address(
    hass: HomeAssistant, url: str, address: str | None
) -> None:
    device = _device(hass, _owner(hass), "sensor", url=url)
    assert device_address(hass, device) == address


async def test_an_entity_of_the_device_can_report_its_address(hass: HomeAssistant) -> None:
    owner = _owner(hass, "esphome")
    device = _device(hass, owner, "plant")
    assert device_address(hass, device) is None
    er.async_get(hass).async_get_or_create(
        "sensor", "esphome", "plant_ip", suggested_object_id="plant_ip", device_id=device.id
    )
    hass.states.async_set("sensor.plant_ip", "10.0.0.7")
    assert device_address(hass, device) == "10.0.0.7"
    hass.states.async_set("sensor.plant_ip", "unknown", {"ip_address": "10.0.0.8"})
    assert device_address(hass, device) == "10.0.0.8"


async def test_the_entry_address_is_only_for_its_only_device(hass: HomeAssistant) -> None:
    """A hub's address belongs to the hub, never to a device behind it."""
    single = _owner(hass, "shelly", host="192.168.1.60")
    shelly = _device(hass, single, "shelly")
    assert device_address(hass, shelly) == "192.168.1.60"

    hub_entry = _owner(hass, "deconz", host="192.168.1.2")
    hub = _device(hass, hub_entry, "gateway")
    behind = _device(hass, hub_entry, "door", via=hub)
    assert device_address(hass, hub) == "192.168.1.2"
    assert device_address(hass, behind) is None

    shared = _owner(hass, "tuya_local", host="192.168.1.3")
    first = _device(hass, shared, "first")
    _device(hass, shared, "second")
    assert device_address(hass, first) is None


# -- asking -------------------------------------------------------------------


async def test_a_device_with_an_address_is_pinged(hass: HomeAssistant) -> None:
    device = _device(hass, _owner(hass), "sensor", url="http://192.168.1.50")
    with patch(PING_ADDRESS, AsyncMock(return_value=True)) as ping:
        assert await async_ping_device(hass, device.id)
    ping.assert_awaited_once_with("192.168.1.50")


async def test_a_device_with_no_way_to_ask_is_not_there(hass: HomeAssistant) -> None:
    device = _device(hass, _owner(hass, "ecovacs"), "robot", url="https://www.ecovacs.com")
    with patch(PING_ADDRESS, AsyncMock(return_value=True)) as ping:
        assert not await async_ping_device(hass, device.id)
    ping.assert_not_awaited()


@pytest.mark.parametrize("answers", [True, False])
async def test_a_zwave_node_gets_zwave_js_s_ping(hass: HomeAssistant, answers: bool) -> None:
    device = _device(hass, _owner(hass, "zwave_js"), "lock", url="http://192.168.1.9")
    node = MagicMock()
    node.async_ping = AsyncMock(return_value=answers)
    with (
        patch(ZWAVE_NODE, return_value=node),
        patch(PING_ADDRESS, AsyncMock(return_value=True)) as ping,
    ):
        assert await async_ping_device(hass, device.id) is answers
    ping.assert_not_awaited()


async def test_a_ping_that_fails_is_no_answer(hass: HomeAssistant) -> None:
    device = _device(hass, _owner(hass), "sensor", url="http://192.168.1.50")
    with patch(PING_ADDRESS, AsyncMock(side_effect=RuntimeError("boom"))):
        assert not await async_ping_device(hass, device.id)


# -- in the coordinator -------------------------------------------------------


async def _set_up(
    hass: HomeAssistant, config_entry: MockConfigEntry, **options: object
) -> tuple[PulseCheckCoordinator, dr.DeviceEntry]:
    device = _device(hass, _owner(hass), "sensor", url="http://192.168.1.50")
    hass.config_entries.async_update_entry(config_entry, options=options)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator: PulseCheckCoordinator = config_entry.runtime_data
    return coordinator, device


async def _later(
    hass: HomeAssistant,
    coordinator: PulseCheckCoordinator,
    freezer: FrozenDateTimeFactory,
    hours: float,
) -> None:
    freezer.tick(timedelta(hours=hours))
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_a_device_that_answers_is_not_quiet(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    coordinator, device = await _set_up(hass, config_entry)
    with patch(PING_ADDRESS, AsyncMock(return_value=True)) as ping:
        await _later(hass, coordinator, freezer, 23)
        ping.assert_not_awaited()  # only when the timer runs out

        await _later(hass, coordinator, freezer, 2)
        health = coordinator.data.by_id[device.id]
        assert not health.is_quiet
        # Heard from at the ping (to the millisecond, as the core keeps time).
        assert health.last_heard is not None
        assert abs(health.last_heard - coordinator.data.computed_at) < timedelta(milliseconds=1)
        assert ping.await_count == 1

        # Its timer started again: asked again a day later, not before.
        await _later(hass, coordinator, freezer, 23)
        assert ping.await_count == 1
        await _later(hass, coordinator, freezer, 2)
        assert ping.await_count == 2
        assert not coordinator.data.by_id[device.id].is_quiet


async def test_a_device_that_stays_silent_is_quiet_and_asked_once(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    coordinator, device = await _set_up(hass, config_entry)
    with patch(PING_ADDRESS, AsyncMock(return_value=False)) as ping:
        await _later(hass, coordinator, freezer, 25)
        assert coordinator.data.by_id[device.id].is_quiet
        for _ in range(3):
            await _later(hass, coordinator, freezer, 1)
        assert ping.await_count == 1

        # Heard from again, then silent for another day: asked again.
        hass.states.async_set("sensor.sensor_battery", "79", BATTERY)
        await _later(hass, coordinator, freezer, 0.1)
        assert not coordinator.data.by_id[device.id].is_quiet
        await _later(hass, coordinator, freezer, 25)
        assert coordinator.data.by_id[device.id].is_quiet
        assert ping.await_count == 2


async def test_nothing_is_asked_when_turned_off(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    coordinator, device = await _set_up(hass, config_entry, **{CONF_PING_QUIET: False})
    with patch(PING_ADDRESS, AsyncMock(return_value=True)) as ping:
        await _later(hass, coordinator, freezer, 25)
    assert coordinator.data.by_id[device.id].is_quiet
    ping.assert_not_awaited()
