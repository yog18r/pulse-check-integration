# Pulse Check

A [Home Assistant](https://www.home-assistant.io/) integration that watches every device's **battery** and **connectivity** across all your integrations, and tells you what to do about it.

It is the backend companion to the [Pulse Check Card](https://github.com/yog18r/pulse-check-card), but it stands on its own: the entities, notifications and services work with no card installed.

[![CI](https://github.com/yog18r/pulse-check-integration/actions/workflows/ci.yml/badge.svg)](https://github.com/yog18r/pulse-check-integration/actions/workflows/ci.yml)

> **Status: early.** Phase 1 of the [plan](PLAN.md) is done: the detection rules and one sensor. Notifications, per-device settings, services and replacement tracking are on their way. See [Roadmap](#roadmap).

---

## The problem

Devices quietly drop off. A door sensor's coin cell dies on a Tuesday and you find out three weeks later when an automation never fires. A Z-Wave node goes dead after a power blip. A Wi-Fi plug loses its connection and sits there reporting its last known state forever.

Home Assistant has all the data to spot this, but it is spread across hundreds of entities, and Home Assistant's own low-battery alerts only cover devices that expose a battery sensor the standard way. Pulse Check pulls it together:

- **Low batteries** from percentage sensors, binary "low battery" sensors, and `battery_level` attributes alike, with charging devices never flagged
- **Offline** devices: every primary entity unavailable
- **Quiet** devices: no report within a threshold, judged per device and per integration
- **Actions**: "Replace 2 × AA in Kitchen Mini Switch", "Charge Office Tablet", and a to-buy total per battery type
- Everything grouped by **device**, not entity, so each physical thing appears once

It reads only what Home Assistant already knows: the state machine and the registries. **It never contacts a device**, so it cannot wake or drain anything.

## Installation

### Option 1: HACS

Add `https://github.com/yog18r/pulse-check-integration` as a custom repository in HACS (category: Integration) and install it. Restart Home Assistant.

### Option 2: manual

Copy the `custom_components/pulse_check` folder into your Home Assistant `config/custom_components/` folder and restart.

### Then

Go to **Settings → Devices & services → Add integration** and search for **Pulse Check**. There is nothing to fill in. One instance watches the whole house.

Requires Home Assistant 2026.9 or newer.

## Entities

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.pulse_check_attention` | Number of devices that need attention (warning or critical) | `devices`: every device with its battery, offline, quiet and severity facts; `summary`: counts; `actions`: the replace and charge lists and shopping totals; `computed_at` |

The `devices` attribute uses the same shape as the card's `DeviceHealth`, one entry per device:

```yaml
- deviceId: 3f2a…
  name: Living Room Motion
  area: Living Room
  integration: mqtt
  manufacturer: Philips
  model: SML001
  battery: { level: 12, isLow: false, source: sensor, entityId: sensor.living_room_motion_battery }
  lastHeard: "2026-10-15T09:20:00.000Z"
  isOffline: false
  isQuiet: false
  quietThresholdHours: 24
  severity: critical
  extras: [{ label: LQI, value: "45", severity: ok }]
  entityIds: [binary_sensor.living_room_motion_occupancy, sensor.living_room_motion_battery, …]
```

The large attributes are excluded from the recorder; only the count is kept as history.

Planned (phase 2): plain count sensors for low and critical batteries, offline and quiet devices, a "next to run out" sensor, and a `binary_sensor.pulse_check_problem`.

## How detection works

These rules are shared with the card and checked against the same test fixture (see [Architecture](#architecture)).

**Battery.** A `sensor` with `device_class: battery` and a numeric state; a `binary_sensor` with `device_class: battery` (on = low); or any entity with a numeric `battery_level` attribute. Entities marked `entity_category: config` are never batteries (an inverter's "minimum state of charge" setting is not a battery). Per device, a sensor reading is preferred over an attribute over a binary sensor, the lowest numeric level wins, and any binary "low" flags the device.

**Charging.** A `binary_sensor` with `device_class: battery_charging` that is on; a battery-state sensor reading `charging` or `full`; a docked vacuum; or `is_charging` / `charging` / `battery_charging` / `battery_state` attributes. A charging device is never flagged for its level.

**Offline.** Every primary entity (no entity category) is `unavailable`. Diagnostic and config entities are ignored, because integrations often leave those available when the hardware is gone, or vice versa. A Z-Wave JS node reported `dead` is offline regardless.

**Last heard and quiet.** The newest `last_reported` across the device's live entities. Settings-type entities (`number`, `select`, `button`, `update`, `text`, `scene`, `script`, and anything `entity_category: config`) do not count: changing a setting an hour ago says nothing about whether the sensor is alive. A device is quiet when that timestamp is older than its threshold. By default only battery devices can be quiet: a mains light nobody has touched for two days is fine, not quiet. Offline devices are not also counted as quiet.

**Severity.** *Critical*: offline, battery at or below the critical level (default 15 %), a binary low-battery sensor, or a dead Z-Wave node. *Warning*: battery at or below the warning level (default 30 %), or quiet. Snoozed devices read as ok.

**Grouping.** By device registry entry. Entities with no device get a synthetic id `entity:<entity_id>` and are included only if they carry a battery (a template battery sensor), never offline or quiet. Service devices (Sun, Forecast) and disabled devices are skipped. The device's integration is the most common platform among its entities.

**Enhancers.** Optional, integration-specific extras that never break the core: Z-Wave JS node status, Zigbee2MQTT link quality and `last_seen`, ZHA LQI and RSSI.

## Architecture

```
custom_components/pulse_check/
├── core/             pure Python, no Home Assistant imports
│   ├── models.py     the input snapshot (TypedDicts) and output dataclasses
│   ├── battery.py    battery and charging detection
│   ├── availability.py  offline, last heard, quiet
│   ├── group.py      entities -> devices
│   ├── thresholds.py severity and threshold resolution
│   ├── analyse.py    the orchestrator: snapshot + config -> DeviceHealth list
│   ├── actions.py    replace / charge lists and shopping totals
│   ├── drain.py      drain-rate estimation (used from phase 2)
│   └── enhancers/    Z-Wave JS, Zigbee2MQTT, ZHA
├── coordinator.py    when to recompute; builds the snapshot from HA
├── sensor.py         the entities
├── config_flow.py    the "Add integration" dialog
└── __init__.py       setup and unload
```

**The core is a port of the card's `src/core`.** Both are tested against the same two files: `tests/fixtures/hass.json`, a mock Home Assistant with 16 devices covering every rule, and `tests/fixtures/golden.json`, the expected output for seven configurations. The card generates them (`npm run golden:update` there) and asserts against them; this repo copies them in and asserts the Python port produces identical JSON. CI fails if the copies drift from the card's `main`. If a rule changes in one place, the test in the other breaks.

**The coordinator** is Home Assistant's `DataUpdateCoordinator`. It listens to `state_changed` for registered entities and recomputes about two seconds after the last change (a debounce, so a burst costs one run), and also every five minutes so time-based transitions happen on their own. It copies the state machine and registries into plain dicts in the event loop, then runs the analysis in a worker thread. The analysis is pure, so it is tested without Home Assistant; the coordinator and sensor are tested with the JSON fixture loaded into a real test instance.

**Nothing is polled from devices.** `last_reported` is Home Assistant's own record of when an entity last pushed a value. Phase 2's drain estimates read the recorder's statistics, which already exist.

## Development

Python 3.14 (what Home Assistant 2026.10 requires). On Windows, Home Assistant's test harness imports Unix-only modules, so run the tests under WSL; ruff and mypy run anywhere.

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements_dev.txt
ruff check . && ruff format --check . && mypy
pytest
```

The test suite (28 tests) runs in about a second. CI runs ruff, mypy, pytest, [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest/) and the HACS validation action on every push, plus the golden-file drift check.

To try a development build on a live instance, copy `custom_components/pulse_check` into `/config/custom_components/` and restart Home Assistant.

## Roadmap

1. ~~Scaffold and core: tooling, config flow, the ported core with shared golden tests, the attention sensor~~
2. Entities and options: count sensors, the problem binary sensor, an options flow for thresholds, quiet scope and filters, drain estimates from recorder statistics
3. Notifications and storage: per-device settings and services, snooze, notifications on transitions with per-device policies (instant, daily, weekly, none), reminders, digests, a `pulse_check_transition` event and a blueprint
4. Replacement tracking: mark replaced or charged, auto-detect, cycle statistics, remaining days, "unusual behaviour" flags, per-device diagnostic sensors
5. Card integration mode: the card reads this integration instead of analysing in the browser

## License

MIT
