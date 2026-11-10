"""The integration-to-card payload, pinned in one file both sides test against.

`tests/fixtures/card_contract.json` holds a device with every optional field
set, a summary and a history result, exactly as the integration emits them.
This test fails when the Python side renames or drops a key; the card's
`frontend/test/card/contract.test.ts` parses the same file and fails when
the card stops reading one. After a deliberate change, regenerate with
`PULSE_CHECK_UPDATE_CONTRACT=1 pytest tests/test_card_contract.py` and update
the card to match.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from custom_components.pulse_check.core.cycles import Estimate
from custom_components.pulse_check.core.models import (
    BatteryReading,
    DeviceHealth,
    EnhancerExtra,
    EstimateInfo,
    UnavailablePart,
)
from custom_components.pulse_check.core.summarise import Summary
from custom_components.pulse_check.websocket import _history_result

if TYPE_CHECKING:
    from custom_components.pulse_check.coordinator import PulseCheckCoordinator

CONTRACT = Path(__file__).parent / "fixtures" / "card_contract.json"
AT = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)


def _kitchen_sink_device() -> dict[str, Any]:
    """A device with every optional field set, so every key is emitted."""
    return DeviceHealth(
        device_id="dev_everything",
        name="Everything Sensor",
        integration="zha",
        is_offline=False,
        is_quiet=True,
        quiet_threshold_hours=36.5,
        severity="warning",
        device_type="motion",
        extras=[EnhancerExtra("LQI", "28", "warning")],
        entity_ids=["sensor.everything_battery", "sensor.everything_temperature"],
        area="Hallway",
        manufacturer="Aqara",
        model="RTCGQ11LM",
        battery=BatteryReading(
            is_low=False,
            source="sensor",
            entity_id="sensor.everything_battery",
            level=24,
            is_charging=True,
        ),
        last_heard=AT,
        snoozed_until=datetime(2026, 10, 16, 10, 0, tzinfo=UTC),
        days_left=400.04,
        estimate=EstimateInfo(400.04, "until charge needed", "low", "charge", open_ended=True),
        battery_kind="charged",
        last_replaced=datetime(2026, 9, 1, tzinfo=UTC),
        unusual="draining 3× faster than usual",
        is_not_provided=True,
        usual_low=23.6,
        source="entity",
        battery_warning=25,
        battery_critical=10.5,
        unavailable_parts=[UnavailablePart("sensor.everything_temperature", "Temperature")],
    ).to_dict()


def _summary() -> dict[str, Any]:
    """Every count different, so a swapped key shows."""
    return Summary(
        attention=1,
        critical=2,
        warning=3,
        battery_devices=4,
        low_batteries=5,
        critical_batteries=6,
        offline=7,
        quiet=8,
        not_provided=9,
        snoozed=10,
    ).to_dict()


def _history() -> dict[str, Any]:
    estimate = Estimate(
        days_left=12.5,
        basis="trend over current cycle",
        confidence="high",
        kind="replace",
        open_ended=False,
        rate_per_day=1.25,
    )
    insights = {"sensor.everything_battery": SimpleNamespace(estimate=estimate)}
    coordinator = cast(
        "PulseCheckCoordinator", SimpleNamespace(history=SimpleNamespace(insights=insights))
    )
    point = SimpleNamespace(time=AT, level=24)
    return _history_result(coordinator, "sensor.everything_battery", 7, [point])  # type: ignore[list-item]


def _contract() -> dict[str, Any]:
    return {"device": _kitchen_sink_device(), "summary": _summary(), "history": _history()}


def test_the_payload_matches_the_pinned_contract() -> None:
    emitted = _contract()
    if os.environ.get("PULSE_CHECK_UPDATE_CONTRACT"):
        CONTRACT.write_text(
            json.dumps(emitted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    pinned = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert emitted == pinned


def test_the_kitchen_sink_device_really_sets_every_field() -> None:
    """A new optional field left unset here would slip past the contract unnoticed."""
    emitted = _kitchen_sink_device()
    missing = [name for name in DeviceHealth.__dataclass_fields__ if _key(name) not in emitted]
    assert missing == []


def _key(field: str) -> str:
    """snake_case field -> the card's camelCase key."""
    head, *rest = field.split("_")
    return head + "".join(part.title() for part in rest)
