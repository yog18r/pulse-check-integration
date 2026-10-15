# Pulse Check

A [Home Assistant](https://www.home-assistant.io/) integration that watches every device's **battery** and **connectivity** across all your integrations, and tells you what to do about it.

It is the backend companion to the [Pulse Check Card](https://github.com/yog18r/pulse-check-card), but it stands on its own: the entities, notifications and services work with no card installed.

[![CI](https://github.com/yog18r/pulse-check-integration/actions/workflows/ci.yml/badge.svg)](https://github.com/yog18r/pulse-check-integration/actions/workflows/ci.yml)

> **Status: early.** Phases 1 and 2 of the [plan](PLAN.md) are done: the detection rules, the entities, the options dialog and drain estimates. Notifications, per-device settings, services and replacement tracking are on their way. See [Roadmap](#roadmap).

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

Copy the `custom_components/pulse_check` folder into your Home Assistant `config/custom_components/` folder and restart. If you copy from a checkout you have run tests in, delete any `__pycache__` folders first; some file-manager add-ons refuse to upload `.pyc` files. The release zip never contains them.

### Then

Go to **Settings → Devices & services → Add integration** and search for **Pulse Check**. There is nothing to fill in. One instance watches the whole house.

Requires Home Assistant 2026.9 or newer.

## Options

Open **Settings → Devices & services → Pulse Check → Configure**. Everything has a sensible default; the first thing most people change is the filters.

**Thresholds**

| Option | Default | Meaning |
| --- | --- | --- |
| Battery warning level | 30 % | At or below this a battery is a warning |
| Battery critical level | 15 % | At or below this a battery is critical |
| Quiet after | 24 h | Hours without any report before a device is quiet |
| Which devices can be quiet | Battery devices only | "All devices" judges mains devices too; expect noise from lights and media players |
| Quiet threshold per integration | none | Longer thresholds for integrations whose devices report rarely, e.g. `zwave_js` 48 h, blinds 48 h |

**Filters**

| Option | Meaning |
| --- | --- |
| Only these areas / Ignore these areas | Area allow and deny lists. With an allow list, devices without an area are left out |
| Only these integrations / Ignore these integrations | By platform, e.g. `mobile_app` to leave phones out, `music_assistant` for players that are off when the TV is |
| Ignore these devices | Specific devices |
| Ignore these entities | Specific entities: typically a settings sensor an integration labels `device_class: battery` (an inverter's "minimum state of charge") without marking it as a config entity |

The option keys match the card's YAML (`battery_warning`, `exclude_entities`, `integration_thresholds`, …), so a card config translates one to one.

## Entities

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.pulse_check_attention` | Number of devices that need attention (warning or critical) | `devices`: every device with its battery, offline, quiet, severity and days-left facts; `summary`: counts; `actions`: the replace and charge lists and shopping totals; `computed_at` |
| `sensor.pulse_check_low_batteries` | Battery devices at or below the warning level, or reporting "low" | |
| `sensor.pulse_check_critical_batteries` | Battery devices at or below the critical level, or reporting "low" | |
| `sensor.pulse_check_offline` | Devices with every primary entity unavailable | |
| `sensor.pulse_check_quiet` | Devices not heard from within their threshold | |
| `sensor.pulse_check_next_to_run_out` | Name of the battery device with the fewest days left (`unknown` until there is enough history) | `days_left`, `device_id`, `entity_id`, `level` |
| `binary_sensor.pulse_check_problem` | On when anything needs attention | |

Snoozed devices (phase 3) count in nothing.

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
  daysLeft: 6.1
  extras: [{ label: LQI, value: "45", severity: ok }]
  entityIds: [binary_sensor.living_room_motion_occupancy, sensor.living_room_motion_battery, …]
```

The large attributes are excluded from the recorder; only the count is kept as history.

### Automation examples

```yaml
# Push a message when something new needs attention
triggers:
  - trigger: state
    entity_id: binary_sensor.pulse_check_problem
    to: "on"
actions:
  - action: notify.mobile_app_pixel_9
    data:
      message: "{{ states('sensor.pulse_check_attention') }} devices need attention"
```

```yaml
# A shopping list from the action totals
actions:
  - action: notify.mobile_app_pixel_9
    data:
      message: >
        {% for line in state_attr('sensor.pulse_check_attention', 'actions').shopping %}
        {{ line.count }} × {{ line.batteryType }}
        {% endfor %}
```

## How detection works

These rules are shared with the card and checked against the same test fixture (see [Architecture](#architecture)).

**Battery.** A `sensor` with `device_class: battery` and a numeric state; a `binary_sensor` with `device_class: battery` (on = low); or any entity with a numeric `battery_level` attribute. Entities marked `entity_category: config` are never batteries (an inverter's "minimum state of charge" setting is not a battery). Per device, a sensor reading is preferred over an attribute over a binary sensor, the lowest numeric level wins, and any binary "low" flags the device.

**Charging.** A `binary_sensor` with `device_class: battery_charging` that is on; a battery-state sensor reading `charging` or `full`; a docked vacuum; or `is_charging` / `charging` / `battery_charging` / `battery_state` attributes. A charging device is never flagged for its level.

**Offline.** Every primary entity (no entity category) is `unavailable`. Diagnostic and config entities are ignored, because integrations often leave those available when the hardware is gone, or vice versa. A Z-Wave JS node reported `dead` is offline regardless.

**Last heard and quiet.** The newest `last_reported` across the device's live entities. Settings-type entities (`number`, `select`, `button`, `update`, `text`, `scene`, `script`, and anything `entity_category: config`) do not count: changing a setting an hour ago says nothing about whether the sensor is alive. A device is quiet when that timestamp is older than its threshold. By default only battery devices can be quiet: a mains light nobody has touched for two days is fine, not quiet. Offline devices are not also counted as quiet.

**Severity.** *Critical*: offline, battery at or below the critical level (default 15 %), a binary low-battery sensor, or a dead Z-Wave node. *Warning*: battery at or below the warning level (default 30 %), or quiet. Snoozed devices read as ok.

**Grouping.** By device registry entry. Entities with no device get a synthetic id `entity:<entity_id>` and are included only if they carry a battery (a template battery sensor), never offline or quiet. Service devices (Sun, Forecast) and disabled devices are skipped. The device's integration is the most common platform among its entities.

**Enhancers.** Optional, integration-specific extras that never break the core: Z-Wave JS node status, Zigbee2MQTT link quality and `last_seen`, ZHA LQI and RSSI.

**Days left.** Every six hours the integration reads the last 14 days of daily battery means from the recorder's long-term statistics (raw state history for sensors without statistics, and attribute history for batteries that only exist as a `battery_level` attribute), adds the live reading, and fits a straight line. It needs at least three samples over two days and a slope of at least 0.1 % per day; a flat or rising battery (on charge, or noisy) gets no estimate. Days left is the level divided by the rate. It is a rough order of magnitude by design.

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
├── history.py        battery history from the recorder, for days-left
├── options.py        entry.options -> the core's configuration
├── entity.py         the base entity (one "Pulse Check" service device)
├── sensor.py         the sensors
├── binary_sensor.py  the problem binary sensor
├── config_flow.py    the "Add integration" and "Configure" dialogs
└── __init__.py       setup and unload
```

**The core is a port of the card's `src/core`.** Both are tested against the same two files: `tests/fixtures/hass.json`, a mock Home Assistant with 16 devices covering every rule, and `tests/fixtures/golden.json`, the expected output for seven configurations. The card generates them (`npm run golden:update` there) and asserts against them; this repo copies them in and asserts the Python port produces identical JSON. CI fails if the copies drift from the card's `main`. If a rule changes in one place, the test in the other breaks.

**The coordinator** is Home Assistant's `DataUpdateCoordinator`. It listens to `state_changed` for registered entities and recomputes about two seconds after the last change (a debounce, so a burst costs one run), and also every five minutes so time-based transitions happen on their own. It copies the state machine and registries into plain dicts in the event loop, then runs the analysis in a worker thread. The analysis is pure, so it is tested without Home Assistant; the coordinator and sensor are tested with the JSON fixture loaded into a real test instance.

**Nothing is polled from devices.** `last_reported` is Home Assistant's own record of when an entity last pushed a value. Drain estimates read the recorder's database, which already holds the history; those queries run in the recorder's own worker thread.

## Development

Python 3.14 (what Home Assistant 2026.10 requires). On Windows, Home Assistant's test harness imports Unix-only modules, so run the tests under WSL; ruff and mypy run anywhere.

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements_dev.txt
ruff check . && ruff format --check . && mypy
pytest
```

The test suite (45 tests) runs in a few seconds. CI runs ruff, mypy, pytest, [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest/) and the HACS validation action on every push, plus the golden-file drift check.

To try a development build on a live instance, copy `custom_components/pulse_check` into `/config/custom_components/` and restart Home Assistant.

## Roadmap

1. ~~Scaffold and core: tooling, config flow, the ported core with shared golden tests, the attention sensor~~
2. ~~Entities and options: count sensors, the problem binary sensor, an options flow for thresholds, quiet scope and filters, drain estimates from recorder statistics~~
3. Notifications and storage: per-device settings and services, snooze, notifications on transitions with per-device policies (instant, daily, weekly, none), reminders, digests, a `pulse_check_transition` event and a blueprint
4. Replacement tracking: mark replaced or charged, auto-detect, cycle statistics, remaining days, "unusual behaviour" flags, per-device diagnostic sensors
5. Card integration mode: the card reads this integration instead of analysing in the browser

## License

MIT
