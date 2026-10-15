# Pulse Check: the plan, as built

Pulse Check is a Home Assistant custom integration (domain `pulse_check`)
that computes device battery and connectivity health server-side, exposes it
as entities, sends notifications, tracks battery replacements, and serves its
own dashboard card. This file is the design record: what was decided, why,
and what is still open. The [README](README.md) is the reference for how
things behave today; where the two disagree, the README wins and this file
needs a fix.

Portfolio context: the author is a Python/Django developer learning
TypeScript. Code should read well to a hiring manager; brief explanations of
Home Assistant and React concepts are welcome where they are introduced.
Plain tone over playful in user-facing text.

## How it got here

1. **A standalone card.** Pulse Check began as a Lovelace card with its own
   TypeScript core: detection rules, thresholds, filters, snoozes in the
   browser, and a drain estimate from the recorder's statistics.
2. **An integration beside it.** Notifications, shared settings and
   replacement history do not belong in a browser, so the rules were ported
   to Python as this integration. The port was proven against the card's own
   fixture, exported as `tests/fixtures/hass.json` with a golden output file.
3. **The card requires the integration.** Two implementations of the same
   rules would drift, and a card-only install could not share snoozes or
   settings. The card became a pure renderer of the integration's websocket
   snapshot; its analysis, thresholds and filters were removed. The golden
   file is now frozen in this repository as the permanent spec.
4. **One repository.** The card moved into `frontend/` (git subtree, history
   kept). The integration serves the built bundle and registers the dashboard
   resource itself, so one HACS install delivers both and versions can never
   mismatch. The old card repository was deleted.

All planned phases are complete. Remaining ideas are listed at the end.

## Detection rules

The core (`custom_components/pulse_check/core/`) is pure Python with no Home
Assistant imports, tested against the frozen fixture and golden file. A rule
change must come with a deliberate change to the golden file.

- **Battery**: a `sensor` with `device_class: battery` and a numeric state; a
  `binary_sensor` with `device_class: battery` (on = low); any entity with a
  numeric `battery_level` attribute. A battery sensor with a non-numeric
  state falls through to the attribute rule. `entity_category: config`
  entities are never batteries. Per device: sensor > attribute > binary,
  lowest numeric level wins, any binary low flags the device.
- **Charging**: `battery_charging` binary sensor on; a battery-state sensor
  reading `charging`/`full`; a docked vacuum; `is_charging` / `charging` /
  `battery_charging` / `battery_state` attributes. Charging devices are
  never flagged for their level.
- **Offline**: every primary entity (no entity category) is `unavailable`;
  all entities if there are no primary ones. A dead Z-Wave JS node is
  offline regardless.
- **Last heard and quiet**: newest `last_reported` across live entities,
  ignoring settings-type entities (`entity_category: config`; domains
  `number`, `select`, `button`, `update`, `text`, `scene`, `script`). Quiet
  when older than the threshold: per-device > per-integration > global
  (default 24 h). `quiet_scope: battery` (default) judges only battery
  devices; `all` judges mains devices too. Offline devices are not also
  quiet; device-less entities are never offline or quiet.
- **Severity**: critical = offline, battery at/below critical (default 15),
  binary low, or an enhancer says so; warning = at/below warning (default
  30) or quiet. Snoozed devices read as ok.
- **Grouping**: by device registry entry; device-less entities get
  `entity:<entity_id>` and count only as battery readings. Service and
  disabled devices are skipped. Integration = most common platform among
  the device's entities. Name = `name_by_user` > `name`, overridable.
- **Device type**: lock, cover, vacuum, phone, media, remote, climate,
  motion, contact, light, switch or other, from the primary entities'
  domains and device classes.
- **Enhancers**: Z-Wave JS node status, Zigbee2MQTT link quality and
  `last_seen`, ZHA LQI/RSSI. Optional extras that never break the core.
- **Actions**: a device at/below warning (or binary low), not charging, not
  snoozed, becomes "Replace N × TYPE in DEVICE", or "Charge DEVICE" when
  marked rechargeable, plus a to-buy total per battery type.
- **Filters**: include/exclude areas and integrations (id or name), exclude
  devices and entities. A per-device `area` override counts for the filters.

## Days left: the cycle-aware estimate

The first estimator was a least-squares slope over 14 days of daily means.
It was replaced after live use showed two failures: a phone charged every
night read "8 months left", and a lock whose battery reading dipped for a
day lost its estimate. The rule now is **never invent an estimate**: a
stand-in such as "assume a year" was considered and rejected.

`core/cycles.py` cuts up to a year of daily means (plus a fortnight of
hourly means) into cycles at a rise of 15+ points within 48 h, at a
`mark_replaced` / `mark_charged` call, or when a charging signal turns on. A
lone dip far below both neighbours is a glitch, not a cycle. Each battery
gets a kind: **charged** (phone, marked rechargeable, charging seen, or
cycles shorter than 30 days), **replaceable** (every cycle began near full),
or **unknown** (no estimate). Replaceable batteries are estimated from the
current cycle's trend when it spans a week, else from completed cycles, with
"flat for 90+ days" and "slow drain over a fortnight" tiers that read "more
than a year" where appropriate. Charged batteries get "charge in ~N days"
until the warning level, suppressed under a day, so phones show nothing.
Every estimate carries a basis and a confidence. "Unusual" flags apply only
to replaceable batteries, comparing the current cycle with the device's own
past cycles like for like, or on a sudden 20-point drop.

## What the integration owns

- **Storage** (`.storage`, shared by every browser and user): per-device
  settings (`name`, `area`, `quiet_threshold_hours`, `battery_type`,
  `battery_count`, `rechargeable`, `notify_policy`, `sparkline_days`),
  snoozes, notification state, and replacement/charge history with cycle
  statistics.
- **Entities**: attention count with a summary attribute; low, critical,
  offline and quiet counts; next to run out; a problem binary sensor;
  optional per-device diagnostic sensors. Nothing time-stamped goes on an
  entity, so an unchanged result writes no recorder row.
- **Notifications**: once per transition (enters warning, enters critical,
  goes offline, goes quiet), never per update. Per-device policy `instant`,
  `daily`, `weekly` or `none`, defaulting by severity; reminders while
  unresolved with a cap; daily and weekly digests; a `pulse_check_transition`
  event and a blueprint. On startup: a baseline, a grace period, and a
  confirmation window; a device must have been seen online since startup
  before it can be reported offline, so slow-starting integrations do not
  produce a flood of false alarms after a restart.
- **Services**: `snooze`, `unsnooze`, `set_device_settings`,
  `mark_replaced`, `mark_charged`, `refresh`.
- **Websocket API**: `pulse_check/subscribe` streams the snapshot (devices,
  summary, actions, config, device settings) and re-sends it after every
  recompute, option change or service call; `pulse_check/history` returns a
  battery's trend points for sparklines.
- **The card**: `card.py` serves `frontend/pulse-check-card.js` and keeps a
  single dashboard resource current with `?v=<version>`; the version lives
  only in `manifest.json`.

## How it runs

- Config entry with an options flow: thresholds, quiet scope, per-integration
  thresholds, filters, notify targets, policies, reminders, digest schedule,
  startup grace and confirmation minutes, per-device sensors.
- A `DataUpdateCoordinator` listening to `state_changed`. Only changes that
  can alter the result get through (availability, battery and charging
  values, node status, `battery_level` attributes); relevant changes are
  debounced to one recompute per 10 s, and a timer recomputes every 5 min
  for time-based transitions. The analysis runs in a worker thread.
- Battery history re-read from the recorder every 6 h, after Home Assistant
  has started; insights survive a reload.
- Nothing is ever polled from a device.

## The card

A renderer over the subscription with presentation-only options: `title`,
`show_tabs`, `default_tab`, `max_rows`, `sort` (`level`, `name`,
`replace_soon`), `group_by` (`none`, `area`, `integration`, `device_type`),
view filters `areas` / `integrations` / `device_types`, `problems_only`,
`show_sparklines`, `sparkline_days`. The visual editor covers all of them
and has a per-device settings panel that saves through
`pulse_check.set_device_settings`. Snooze and Done call services. The demo
page (`npm run dev` in `frontend/`) replays a canned snapshot and takes
`?scenario=…&theme=…&shot` for the README screenshots.

## Tooling

- Python 3.14 (Home Assistant 2026.10); `probatio` replaced voluptuous in
  2026.9, so `hacs.json` requires 2026.9.0 or newer. Ruff, mypy, pytest with
  `pytest-homeassistant-custom-component` (under WSL on Windows).
- Node 24, Vite, React, TypeScript strict, Vitest, ESLint and Prettier in
  `frontend/`; the bundle is built in CI and the release workflow, not
  committed.
- GitHub Actions: ruff, mypy, pytest, the card's checks and build, hassfest,
  HACS validation; a `v*` tag matching `manifest.json` publishes
  `pulse_check.zip`.
- Small, meaningful commits.

## Still open

- Catching up missed digests after a restart.
- Watching entities that have no registry entry beyond battery readings.
- Translations beyond English; HACS default-store submission once released.
