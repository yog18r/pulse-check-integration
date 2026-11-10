"""The per-integration limit on offline and quiet messages.

An outage outside Home Assistant knocks many devices of one integration
over at once. A few messages go out as usual; the rest of that
integration's wait an hour and go out as one, listing only what is still
wrong. The fixture has two Shelly devices (a plug and an H&T sensor) and
an MQTT light, so a limit of 1 shows the behaviour with few devices.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.pulse_check.const import (
    CONF_INTEGRATION_LIMIT,
    DEBOUNCE_SECONDS,
)
from tests.helpers import (
    BATTERY,
    NOTIFY_OPTIONS,
    advance,
    confirm_offline,
    ht_offline,
    past_grace,
    plug_offline,
    sent_messages,
    set_up_notify,
)

HELD = "shelly: 1 more device offline or not heard from:"


async def _limited(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
    limit: int = 1,
) -> list[Any]:
    options = {**NOTIFY_OPTIONS, CONF_INTEGRATION_LIMIT: limit}
    _, _, calls = await set_up_notify(hass, fixture_snapshot, freezer, fixed_now, options)
    await past_grace(hass, freezer)
    return calls


async def test_the_rest_wait_an_hour_and_go_out_as_one(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    calls = await _limited(hass, fixture_snapshot, freezer, fixed_now)
    await plug_offline(hass, freezer)
    await ht_offline(hass, freezer)
    assert sent_messages(calls) == ["Office Plug: offline"]

    await advance(hass, freezer, timedelta(minutes=50))
    assert len(calls) == 1
    await advance(hass, freezer, timedelta(minutes=15))
    assert sent_messages(calls)[1:] == [f"{HELD}\n- Kitchen H&T: offline"]

    # Sent once: the next hours bring nothing more.
    await advance(hass, freezer, timedelta(hours=2))
    assert len(calls) == 2


async def test_a_short_outage_ends_with_nothing_more_to_say(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    calls = await _limited(hass, fixture_snapshot, freezer, fixed_now)
    await plug_offline(hass, freezer)
    await ht_offline(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_temperature", "21.5")
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))

    await advance(hass, freezer, timedelta(hours=2))
    assert sent_messages(calls) == ["Office Plug: offline"]


async def test_each_integration_has_its_own_allowance(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    calls = await _limited(hass, fixture_snapshot, freezer, fixed_now)
    await plug_offline(hass, freezer)
    hass.states.async_set("light.garage_lights", "unavailable")
    await confirm_offline(hass, freezer)
    assert sent_messages(calls) == ["Office Plug: offline", "Garage Lights: offline"]


async def test_battery_messages_are_never_held(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    calls = await _limited(hass, fixture_snapshot, freezer, fixed_now)
    await plug_offline(hass, freezer)
    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await advance(hass, freezer, timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert sent_messages(calls) == [
        "Office Plug: offline",
        "Kitchen H&T: battery critical (5 %)",
    ]


async def test_zero_means_no_limit(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    calls = await _limited(hass, fixture_snapshot, freezer, fixed_now, limit=0)
    await plug_offline(hass, freezer)
    await ht_offline(hass, freezer)
    assert sent_messages(calls) == ["Office Plug: offline", "Kitchen H&T: offline"]


async def test_the_allowance_comes_back_after_an_hour(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    calls = await _limited(hass, fixture_snapshot, freezer, fixed_now)
    await plug_offline(hass, freezer)
    await advance(hass, freezer, timedelta(hours=1))
    await ht_offline(hass, freezer)
    assert sent_messages(calls) == ["Office Plug: offline", "Kitchen H&T: offline"]
