"""The shared golden test: the Python core must match the card's output.

`tests/fixtures/hass.json` and `tests/fixtures/golden.json` are copied
from the card repo, where `test/core/golden.test.ts` generates them and
asserts the card still matches them. Here the Python port is run over the
same fixture with the same configurations and must produce identical
JSON. CI additionally checks the copies are byte-identical to the card's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from custom_components.pulse_check.core import (
    CoreConfig,
    Snapshot,
    action_list,
    analyse_devices,
    summarise,
)
from custom_components.pulse_check.core.enhancers import ENHANCERS


def _cases(golden: dict[str, Any]) -> list[dict[str, Any]]:
    return golden["cases"]  # type: ignore[no-any-return]


def _by_id(devices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["deviceId"]: d for d in devices}


def _run(
    snapshot: dict[str, Any], case: dict[str, Any], now: datetime
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    config = CoreConfig.from_dict(case["config"])
    snoozes = {
        device_id: datetime.fromisoformat(iso)
        for device_id, iso in (case.get("snoozes") or {}).items()
    }
    typed: Snapshot = snapshot  # type: ignore[assignment]
    devices = analyse_devices(typed, config, now, enhancers=ENHANCERS, snoozes=snoozes)
    actions = action_list(devices, config).to_dict()
    summary = summarise(devices, config).to_dict()
    return [_comparable(d.to_dict()) for d in devices], actions, summary


def _comparable(device: dict[str, Any]) -> dict[str, Any]:
    """Drop fields the card's golden file does not carry yet."""
    return {k: v for k, v in device.items() if k not in CARD_LACKS}


# Added on the Python side first; the card gains them in phase 5, after
# which the golden file is regenerated and this set shrinks to nothing.
CARD_LACKS = frozenset({"deviceType"})


@pytest.fixture(scope="module")
def case_names(golden: dict[str, Any]) -> list[str]:
    return [case["name"] for case in _cases(golden)]


def test_golden_has_cases(golden: dict[str, Any]) -> None:
    assert len(_cases(golden)) >= 5


@pytest.mark.parametrize("index", range(7))
def test_devices_match_card(
    fixture_snapshot: dict[str, Any], golden: dict[str, Any], fixed_now: datetime, index: int
) -> None:
    case = _cases(golden)[index]
    devices, _, _ = _run(fixture_snapshot, case, fixed_now)
    expected = case["devices"]

    # Compare device by device first, so a failure names the device and field.
    ours, theirs = _by_id(devices), _by_id(expected)
    assert set(ours) == set(theirs), f"{case['name']}: different device sets"
    for device_id, expected_device in theirs.items():
        assert ours[device_id] == expected_device, f"{case['name']}: {device_id}"
    # Then the whole list, which also checks the order.
    assert devices == expected, case["name"]


@pytest.mark.parametrize("index", range(7))
def test_actions_match_card(
    fixture_snapshot: dict[str, Any], golden: dict[str, Any], fixed_now: datetime, index: int
) -> None:
    case = _cases(golden)[index]
    _, actions, _ = _run(fixture_snapshot, case, fixed_now)
    assert actions == case["actions"], case["name"]


@pytest.mark.parametrize("index", range(7))
def test_summary_matches_card(
    fixture_snapshot: dict[str, Any], golden: dict[str, Any], fixed_now: datetime, index: int
) -> None:
    case = _cases(golden)[index]
    _, _, summary = _run(fixture_snapshot, case, fixed_now)
    # The Python summary adds criticalBatteries; compare the card's keys.
    ours = {key: summary[key] for key in case["summary"]}
    assert ours == case["summary"], case["name"]


def test_case_count_matches_parametrisation(golden: dict[str, Any]) -> None:
    """If the card adds a case, the `range(7)` above must grow with it."""
    assert len(_cases(golden)) == 7
