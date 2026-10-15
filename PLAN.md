# Pulse Check integration: plan

A Home Assistant custom integration (domain `pulse_check`) that computes device
battery and connectivity health server-side, exposes it as entities, sends
notifications, and tracks battery replacements. It is the backend companion to
the Pulse Check Card (now in `frontend/`), but it
**must be fully useful with no card installed**: entities, notifications,
services and the blueprint stand on their own. The card is one optional view.

Portfolio context: the author is a Python/Django developer learning TypeScript.
Keep code clean and well commented so it reads well to a hiring manager; brief
explanations of Home Assistant concepts (config entries, coordinators, entity
platforms, storage, services) are welcome as they are introduced. Plain tone
over playful in user-facing text.

## Rules to port (from the card's `src/core`)

The card's pure TypeScript core is the spec. Port it faithfully to Python and
check both against the same fixture:

- **Battery**: `sensor` with `device_class: battery` and numeric state; a
  `binary_sensor` with `device_class: battery` (on = low); any entity with a
  numeric `battery_level` attribute. A battery sensor with a non-numeric state
  falls through to the attribute rule. Entities with `entity_category: config`
  are never batteries. Per device: prefer sensor > attribute > binary, lowest
  numeric level wins, any binary "low" flags the device.
- **Charging**: `binary_sensor` `device_class: battery_charging` on; a sensor
  whose id contains "battery" reading `charging`/`full`; a `vacuum` that is
  `docked`; attributes `is_charging` / `charging` / `battery_charging` true or
  `battery_state: charging`. A charging device is never flagged for battery.
- **Offline**: every primary entity (no `entity_category`) is `unavailable`;
  fall back to all entities if there are no primary ones.
- **Last heard**: newest `last_reported` across the device's live entities.
  Static entities are ignored: `entity_category: config`, and domains
  `number`, `select`, `button`, `update`, `text`, `scene`, `script`. (The
  backend has `last_reported` directly; the card could only use
  `last_updated` plus an on-demand lookup.)
- **Quiet**: last heard older than the threshold. Resolution: per-device >
  per-integration > global (default 24h). By default only battery devices can
  be quiet (`quiet_scope: battery`); `all` judges mains devices too. Offline
  devices are not also quiet. Devices with no device registry entry can only
  be battery readings, never offline or quiet.
- **Severity**: critical = offline, battery at/below critical (default 15),
  binary low, or an enhancer says so; warning = battery at/below warning
  (default 30) or quiet; snoozed devices read as ok.
- **Grouping**: by device registry entry; entities with no device get a
  synthetic id `entity:<entity_id>` and are included only if they carry a
  battery. Skip `entry_type: service` and disabled devices. Integration =
  most common `platform` among the device's entities. Name = `name_by_user`
  > `name`, overridable per device.
- **Enhancers**: Z-Wave JS node status (`dead` = offline/critical),
  Zigbee2MQTT `linkquality` (warning <= 30) and optional `last_seen`, ZHA
  `lqi`/`rssi`. Same interface idea: optional extras that never break the core.
- **Drain estimate**: least-squares slope over the last 14 days of daily
  means plus the live reading; needs 3+ samples over 2+ days and a slope of at
  least 0.1 %/day; flat or rising series give no estimate; days left =
  level / rate. Statistics from the recorder, raw history as fallback for
  sensors without statistics, attribute history for attribute-based batteries.
- **Actions**: a device at/below warning (or binary low), not charging, not
  snoozed, becomes "replace N × TYPE in DEVICE" or "charge DEVICE" when
  `rechargeable`; a to-buy total per battery type.
- **Filters**: include/exclude areas (id or name, case-insensitive; an include
  list drops devices with no area), include/exclude integrations, exclude
  devices and entities. Per-device `area` override counts for the filters.

Port the fixture: export the card's `test/fixtures/hass.ts` as JSON
(`tests/fixtures/hass.json`) together with a golden file of expected
`DeviceHealth` output, and make the card's tests also assert against the same
golden file, so the two implementations cannot drift.

## What the integration owns

**State in Home Assistant storage** (`homeassistant.helpers.storage.Store`),
shared across every browser and device:
- per-device settings: `name`, `area`, `quiet_threshold_hours`,
  `battery_type`, `battery_count`, `rechargeable`, `notify_policy`
- snoozes (device id -> until)
- replacement/charge history per device: timestamp, kind (replaced/charged),
  battery type, level before/after, and the cycle length and average drain of
  each completed cycle

**Entities**
- `sensor.pulse_check_attention`: count of devices needing attention, with the
  full device list as attributes in the card's `DeviceHealth` shape (id, name,
  area, integration, battery level/isLow/isCharging, lastHeard, isOffline,
  isQuiet, severity, extras, daysLeft, lastReplaced, unusual)
- `sensor.pulse_check_low_batteries`, `..._critical_batteries`,
  `..._offline`, `..._quiet`: plain counts for independent automations
- `sensor.pulse_check_next_to_run_out`: name of the device with the fewest
  days left, with days as an attribute
- `binary_sensor.pulse_check_problem`: on when anything needs attention
- Optionally per-device: a `sensor.<device>_days_left` and
  `sensor.<device>_last_replaced` for battery devices (diagnostic category)

**Notifications** (built in, configured in the options flow; not dependent on
the card):
- notify action(s) to call (any `notify.*`), chosen in the options flow
- per-device thresholds as today; per-device **notify policy**: `instant`,
  `daily`, `weekly`, `none`, with defaults by severity (critical -> instant,
  warning -> weekly digest). Example: a leak detector instant, blinds weekly.
- **once per event**: notify when a device *transitions* into a state (enters
  warning, enters critical, goes offline, goes quiet), never on every state
  update. Track per-device "last notified state" in storage so a restart
  does not re-notify.
- **reminders**: if the problem remains unresolved after a configurable
  interval (default 3 days), send again; configurable cap.
- **digests**: daily/weekly summary at a configured time for devices on those
  policies; nothing is sent when there is nothing to say (optional
  "all clear" weekly line).
- also fire an event `pulse_check_transition` for every transition so users
  can build their own automations, and ship a blueprint that uses it.

**Replacement tracking**
- `pulse_check.mark_replaced` / `mark_charged` services (device, optional
  battery type) record an entry and start a new cycle
- **auto-detect** a replacement or charge: a jump of >= 20 points, or the
  charging signal followed by a higher level, closes the cycle automatically
- remaining days from the current drain estimate; **unusual behaviour** flags
  when the current cycle drains markedly faster than the device's own
  history (e.g. > 2× the average rate of past cycles) or after a sudden drop,
  surfaced as `unusual: "draining 3× faster than usual"` on the device

**Grouping and categories**
- compute a `device_type` per device from its primary entities' domains and
  device classes (lock, cover/blind, vacuum, phone, motion, contact,
  climate, remote, light, switch, media, other) so views can group by type
- group-by for the card: `none | area | integration | device_type`
  (phase 4, card side); the integration exposes the fields

**Services**: `snooze`, `unsnooze`, `mark_replaced`, `mark_charged`,
`set_device_settings`, `refresh`.

## How it runs

- Config entry with an options flow (thresholds, quiet scope, filters,
  notify targets, digest schedule, reminder interval).
- A `DataUpdateCoordinator` that listens to `state_changed` for all entities,
  recomputes with a short debounce (about 2 s), and also refreshes every few
  minutes so time-based transitions (quiet, snooze expiry) happen on their own.
- Drain estimates from recorder statistics every 6 h, via the recorder's
  `statistics_during_period` in the executor; raw history fallback as in the
  card.
- Notifications evaluated after each recompute from the transition set.

## Tooling

- Python as required by the current Home Assistant release (3.13 today; 3.14
  is installed on this machine, so install 3.13 via `py`/winget if needed).
- `custom_components/pulse_check/` layout, `manifest.json`, `hacs.json`,
  `strings.json` + `translations/en.json`.
- Ruff (lint + format), mypy, pytest with `pytest-homeassistant-custom-component`.
- GitHub Actions: ruff, mypy, pytest, hassfest, HACS validation on every push;
  a release workflow on `v*` tags.
- Small meaningful commits with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- README for users and reviewers: what it does, install (HACS custom repo or
  copy the folder), options reference, entities, services, notifications,
  how detection works, architecture, running tests, roadmap.

## Phases

1. **Scaffold + core**: repo tooling, config flow (no options yet), the
   ported pure core with the shared fixture and golden tests, the attention
   sensor. Installable.
2. **Entities + options**: all sensors and the binary sensor, options flow
   for thresholds/scope/filters, drain estimates, HACS metadata, CI, README.
3. **Notifications + storage**: Store, per-device settings and services,
   snooze, transition tracking, notify policies, reminders, digests, events,
   blueprint.
4. **Replacement tracking**: history, auto-detect, cycle stats, unusual
   behaviour, per-device sensors.
5. **Card integration mode** (in the card, now `frontend/`): `source: integration` reads
   the attention sensor instead of analysing; snooze and mark-replaced call
   services; `group_by` option. Standalone mode stays, deprecated later.

Testing on the author's live instance: copy `custom_components/pulse_check`
into `/config/custom_components/`, restart, add the integration from
Settings > Devices & services. Tell the author when a phase is ready to try.
