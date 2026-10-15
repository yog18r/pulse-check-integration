# Pulse Check

A [Home Assistant](https://www.home-assistant.io/) integration that watches every device's **battery** and **connectivity** across all your integrations, and tells you what to do about it.

It brings entities, notifications, services, a blueprint and a **dashboard card**. One install provides all of them: the integration serves the card itself and adds it to your dashboards, so it simply appears in the card picker.

<p align="center">
  <img src="https://raw.githubusercontent.com/yog18r/pulse-check-integration/main/frontend/docs/screenshot-batteries.jpg" alt="Batteries tab, dark theme: devices sorted lowest battery first, with coloured bars, trend sparklines and days left" width="280" />
  <img src="https://raw.githubusercontent.com/yog18r/pulse-check-integration/main/frontend/docs/screenshot-connectivity.jpg" alt="Connectivity tab, light theme, grouped by area: one offline lock and two quiet sensors" width="280" />
  <img src="https://raw.githubusercontent.com/yog18r/pulse-check-integration/main/frontend/docs/screenshot-actions.jpg" alt="Actions tab, dark theme: what to buy, which batteries to replace and which devices to charge, each with a Done button" width="280" />
</p>

<p align="center"><em>The card's Batteries, Connectivity and Actions tabs, rendered from its demo page with mock data.</em></p>

[![CI](https://github.com/yog18r/pulse-check-integration/actions/workflows/ci.yml/badge.svg)](https://github.com/yog18r/pulse-check-integration/actions/workflows/ci.yml)

> **Status: feature complete, lightly tested.** Everything in the [plan](https://github.com/yog18r/pulse-check-integration/blob/main/PLAN.md) is built: detection rules, entities, options, notifications, services, replacement tracking and the card. It has run on one real instance. Expect rough edges; issues are welcome. See [Roadmap](#roadmap).

---

## The problem

Devices quietly drop off. A door sensor's coin cell dies on a Tuesday and you find out three weeks later when an automation never fires. A Z-Wave node goes dead after a power blip. A Wi-Fi plug loses its connection and sits there reporting its last known state forever.

Home Assistant has all the data to spot this, but it is spread across hundreds of entities, and Home Assistant's own low-battery alerts only cover devices that expose a battery sensor the standard way. Pulse Check pulls it together:

- **Low batteries** from percentage sensors, binary "low battery" sensors, and `battery_level` attributes alike, with charging devices never flagged
- **Offline** devices: every primary entity unavailable
- **Quiet** devices: no report within a threshold, judged per device and per integration
- **Actions**: "Replace 2 × AA in Kitchen Mini Switch", "Charge Office Tablet", and a to-buy total per battery type
- **Notifications** once per transition, not once per update: a device goes offline, goes quiet, or drops to warning or critical. Instant with reminders, or collected into a daily or weekly digest, chosen per device
- **Days left** from the recorder's history, **replacement tracking** with cycle statistics, and a flag when a battery drains much faster than it used to
- **Snooze** a device for a while; snoozes are shared across every browser and user
- Everything grouped by **device**, not entity, so each physical thing appears once
- In **ten languages**: English, German, French, Spanish, Dutch, Italian, Brazilian Portuguese, Polish, Simplified Chinese and Czech

It reads only what Home Assistant already knows: the state machine and the registries. **It never contacts a device**, so it cannot wake or drain anything.

## Installation

### Option 1: HACS

Add `https://github.com/yog18r/pulse-check-integration` as a custom repository in HACS (category: Integration) and install it. Restart Home Assistant.

### Option 2: manual

Download `pulse_check.zip` from the [latest release](https://github.com/yog18r/pulse-check-integration/releases/latest), unzip it into `config/custom_components/pulse_check/` and restart. The zip already contains the card.

Copying `custom_components/pulse_check` from a checkout of this repository works too, but build the card into it first (it is not committed):

```bash
cd frontend
npm ci
npm run build
```

That writes `custom_components/pulse_check/frontend/pulse-check-card.js`. Delete any `__pycache__` folders before copying; some file-manager add-ons refuse to upload `.pyc` files. The release zip never contains them.

### Then

Go to **Settings → Devices & services → Add integration** and search for **Pulse Check**. There is nothing to fill in. One instance watches the whole house.

Refresh the browser, edit a dashboard, **Add card**, and pick **Pulse Check Card**, or add it in YAML:

```yaml
type: custom:pulse-check-card
```

Requires Home Assistant 2026.9 or newer.

### How the card gets onto your dashboards

A *dashboard resource* (Settings → Dashboards → ⋮ → Resources) is a script every dashboard loads. On each start the integration serves its card at `/pulse_check/pulse-check-card.js` and makes sure there is exactly one resource for it, of type *JavaScript module*, with the integration's version on the end (`?v=0.1.0`). After an update the version changes, the resource is updated with it, and browsers fetch the new card instead of a cached old one. Removing the integration removes the resource.

If your resources are defined in YAML (`lovelace: resource_mode: yaml`), an integration must not edit them, so Pulse Check logs the line to add instead:

```yaml
lovelace:
  resources:
    - url: /pulse_check/pulse-check-card.js?v=0.1.0
      type: module
```

## Languages

Pulse Check speaks English, German (`de`), French (`fr`), Spanish (`es`), Dutch (`nl`), Italian (`it`), Brazilian Portuguese (`pt-BR`), Polish (`pl`), Simplified Chinese (`zh-Hans`) and Czech (`cs`), in three places:

- **Dialogs, entity names and services** follow each user's language, like any integration (`custom_components/pulse_check/translations/`).
- **Notifications and digests** are written in the server language (Settings → System → General), checked as each message is sent, so a change needs no restart (`custom_components/pulse_check/messages/`).
- **The card and its editor** follow each user's profile language, including dates and "5m ago" style times (`frontend/src/i18n/`).

A regional variant uses its base language (`de-CH` reads German, `pt` reads Brazilian Portuguese) and anything else reads English. A few things stay as they are everywhere: device and area names, battery sizes such as CR2032, and YAML keys in the card's error messages.

> **The translations were made by machine.** They have been checked for completeness and placeholders, not by native speakers. Corrections are very welcome: each language is one file in each of the three folders above, so a pull request that fixes a phrase touches only that line.

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

**Notifications** (collapsed by default)

| Option | Default | Meaning |
| --- | --- | --- |
| Send to | none | Notify services (`notify.mobile_app_…`) or notify entities. Empty means no notifications; the event still fires |
| Critical problems | Instantly | Default delivery for offline devices and critical batteries |
| Warnings | Weekly digest | Default delivery for quiet devices and low batteries |
| Remind after | 3 days | How long an instant notification may stay unresolved before it is sent again |
| Reminders at most | 3 | 0 turns reminders off |
| Digest time | 09:00 | When the daily digest goes out, and the weekly one on its day. One missed while Home Assistant was off goes out once after the next start |
| Weekly digest day | Monday | |
| Weekly "all clear" | off | Send the weekly digest even when there is nothing to report |
| Quiet period after start | 5 min | Nothing is judged until Home Assistant has started plus this long. Integrations load one by one and most devices look unavailable meanwhile; what is still wrong at the end is recorded as the starting point, not announced |
| Confirm offline or quiet after | 5 min | An offline or quiet state must persist this long before it counts. A missed poll that heals within the window sends nothing. Battery levels count at once |
| Maintenance mode length | 2 h | How long `pulse_check.maintenance_mode` holds notifications back when it is called without `hours` |

A device's own `notify_policy` (set with the `set_device_settings` service) overrides the defaults: `instant`, `daily`, `weekly` or `none`. A leak detector can be instant while the blinds wait for the weekly digest.

**Entities** (collapsed by default)

| Option | Default | Meaning |
| --- | --- | --- |
| Per-device battery sensors | off | Adds "Battery days left" and "Battery last replaced" diagnostic sensors to every battery device's own page |

## The card

- **🔋 Batteries**: every battery-powered device, lowest first (or soonest to run out), with a coloured bar, a trend sparkline, "~12d left", and a note when a battery is draining much faster than it used to
- **📡 Connectivity**: anything offline or not heard from within its threshold
- **🛠️ Actions** (optional tab): "Replace 2 × AA in Kitchen Mini Switch", "Charge Office Tablet", a to-buy total, and a **Done** button that records the replacement
- **Snooze** a device for 1, 7 or 30 days. Snoozes live in the integration, so every dashboard, phone and notification agrees
- **Group by** area, integration or device type. Tap a row to open the device in Home Assistant
- A line under the header while **maintenance mode** holds notifications back, with its end time

The card shows what the integration computed; it analyses nothing itself. What counts as low, how long a device may stay quiet, which devices are ignored and which notifications go out are the integration's options (above). The card's own options are about presentation only, and the visual editor covers all of them:

```yaml
type: custom:pulse-check-card
title: Device Health # leave out for no title row
show_tabs: [batteries, connectivity, actions]
default_tab: batteries
max_rows: 12 # or "all"
sort: level # level, name or replace_soon
group_by: none # none, area, integration or device_type
areas: [] # view filters: names or ids; empty means all
integrations: []
device_types: []
problems_only: false # Batteries tab shows only warning/critical rows
show_sparklines: true
sparkline_days: 14 # 1 to 365
```

| Option | Default | Notes |
| --- | --- | --- |
| `title` | none | Leave out (or blank) for no title row |
| `show_tabs` | `[batteries, connectivity]` | Any of `batteries`, `connectivity`, `actions` |
| `default_tab` | `batteries` | Must be in `show_tabs` |
| `max_rows` | `12` | Or `all`. A "show more" control reveals the rest |
| `sort` | `level` | Inside each severity band: `level` (lowest first), `name`, or `replace_soon` (devices with an estimate first, fewest days left first, then the rest by level). `battery_sort` still works |
| `group_by` | `none` | `none`, `area`, `integration` or `device_type` |
| `areas`, `integrations`, `device_types` | `[]` | Show only these. Device types: `lock`, `cover`, `vacuum`, `phone`, `media`, `remote`, `climate`, `motion`, `contact`, `light`, `switch`, `other` |
| `problems_only` | `false` | Batteries tab shows only warning and critical rows |
| `show_sparklines` | `true` | Trend lines from recorder history, read by the integration |
| `sparkline_days` | `14` | 1 to 365. A device's own sparkline window overrides it |

The integration's filters decide what is monitored at all; a card's `areas`, `integrations` and `device_types` only decide what *that* card shows, so one integration can feed a hallway card, a locks-only card and a whole-house card. The header counts follow the card's filters.

The visual editor also has a **Per-device settings** panel: display name, area, battery type and count, rechargeable, quiet threshold, notification policy and sparkline window for any device. Each change is saved at once through `pulse_check.set_device_settings`, not into the card's YAML, so it applies to every card and to notifications.

## Entities

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.pulse_check_attention` | Number of devices that need attention (warning or critical) | `summary`: the counts below as one mapping; `computed_at`. The device list itself is served over the websocket (see below), not as an attribute |
| `sensor.pulse_check_low_batteries` | Battery devices at or below the warning level, or reporting "low" | |
| `sensor.pulse_check_critical_batteries` | Battery devices at or below the critical level, or reporting "low" | |
| `sensor.pulse_check_offline` | Devices with every primary entity unavailable | |
| `sensor.pulse_check_quiet` | Devices not heard from within their threshold | |
| `sensor.pulse_check_next_to_run_out` | Name of the battery device with the fewest days left (`unknown` until there is enough history) | `days_left`, `device_id`, `entity_id`, `level` |
| `binary_sensor.pulse_check_problem` | On when anything needs attention | |
| `binary_sensor.pulse_check_maintenance_mode` | On while maintenance mode holds notifications back | `until`: when it ends |

Snoozed devices count in nothing. With the per-device option on, every battery device also gets `sensor.<device>_battery_days_left` and `sensor.<device>_battery_last_replaced` (diagnostic), the latter with the device's cycle statistics as attributes.

## Websocket API

This is the contract between the integration and the card. The card, or anything else on Home Assistant's websocket, can subscribe to the computed data instead of polling entities. Keeping the device list off the sensor's attributes keeps the state machine and the recorder free of a large, frequently changing payload.

**`pulse_check/subscribe`** sends one event immediately and another after every recompute (about ten seconds after a relevant state change, and at least every five minutes):

```json
{
  "devices": [ ...one entry per device, see below... ],
  "summary": { "attention": 4, "critical": 2, "warning": 2, "batteryDevices": 11, "lowBatteries": 4, "criticalBatteries": 3, "offline": 1, "quiet": 2, "snoozed": 0 },
  "actions": { "replace": [...], "charge": [...], "shopping": [{ "batteryType": "CR2450", "count": 2, "devices": 1 }] },
  "config": { "battery_warning": 30, "battery_critical": 15, "quiet_threshold_hours": 24, "quiet_scope": "battery", "integration_thresholds": {}, "device_settings": [...] },
  "device_settings": { "<device id>": { "battery_type": "CR2450", "battery_count": 2, "notify_policy": "weekly" } },
  "computed_at": "2026-10-15T10:00:00.000Z",
  "maintenance_until": null
}
```

**`pulse_check/history`** with `entity_id` (a watched battery entity) and optional `days` (1 to 365, default 14) returns sparkline points, hourly means for windows of three days or less and daily means otherwise, from the recorder's statistics with raw and attribute history as fallbacks, plus the current drain estimate:

```json
{ "entity_id": "sensor.living_room_motion_battery", "days": 14, "points": [{ "time": 1760000000000, "level": 40.0 }], "estimate": { "ratePerDay": 2.0, "daysLeft": 6.0, "samples": 15 } }
```

Both return the error `not_loaded` when the integration is not set up.

Each device entry uses the card's `DeviceHealth` shape:

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

Each device entry also carries `deviceType` (lock, cover, vacuum, phone, media, remote, climate, motion, contact, light, switch or other), `daysLeft`, `lastReplaced` and `unusual` when known, and `snoozedUntil` while snoozed.

## Notifications

A message is sent when a device *enters* a state: goes offline, goes quiet, or its battery drops to warning or critical. Nothing is sent on every update, and the states each device is in are stored, so a restart does not repeat old news. After a restart nothing is judged until Home Assistant has started plus a quiet period (default five minutes), and the first look after that only records what is wrong rather than announcing it; an offline or quiet state must then persist for a confirmation window (default five minutes) before it counts, so a brief hiccup never notifies. A device that has not been seen online at all since the restart is treated as not loaded yet rather than offline, however long that takes, so integrations that are slow to come up never look like outages. When the problem goes away nothing is sent either, but the event below fires with `kind: resolved`.

Each device has a policy: **instant** (sent at once, then a reminder every few days while it stays unresolved, up to a cap), **daily** or **weekly** (collected into one digest message at the configured time; no message when there is nothing to say), or **none**. The defaults are by severity (critical instant, warning weekly) and any device can override them.

A digest whose time passes while Home Assistant is off, or still starting, is not lost. The integration stores when each digest was last due and dealt with, whether or not there was anything to say. When the quiet period after the next start ends, a digest that has fallen due since then is sent once, with what is wrong at that moment, however many were missed; then the normal schedule resumes. The same rules apply as at the usual time: nothing is sent when there is nothing to say, unless the weekly "all clear" is on. A new install starts counting from the moment it is set up, so it never sends a digest for a time before that.

### Buttons on phone notifications

A target that is a companion-app service (`notify.mobile_app_<phone>`, iOS or Android) gets buttons on instant notifications and reminders:

| Problem | Buttons |
| --- | --- |
| Battery low or critical | **Mark replaced** (or **Mark charged** for a device set as rechargeable), **Remind me later** |
| Offline or quiet | **Snooze 1 day** |

Pressing one does what the service of the same name does, for that device, without opening the app. **Remind me later** changes nothing: the reminder comes when it was due anyway, so it is only offered when another reminder will actually follow. Digests and the maintenance summary cover many devices and have no buttons. Every other target (notify entities, e-mail, Telegram, a notify group) gets the plain message as before.

The buttons follow the companion app's [actionable notifications](https://companion.home-assistant.io/docs/notifications/actionable-notifications/): each has an `action` identifier of the form `PULSE_CHECK_SNOOZE_DAY:<device id>`, and the app fires `mobile_app_notification_action` with it when pressed. Your own automations can listen for the same event.

### Maintenance mode

Some jobs knock many devices over at once on purpose: moving to a new Zigbee coordinator, re-pairing a Z-Wave network, rewiring a rack. Call `pulse_check.maintenance_mode` with the number of `hours` the work should take (or leave it out for the default in the options) and Pulse Check holds every message back until then: no instant notifications, no reminders, no digests. Everything else carries on. Problems are still tracked, the event below still fires (with `maintenance: true`), the card shows a line in its header, and `binary_sensor.pulse_check_maintenance_mode` is on with the end time in its `until` attribute. Calling it again moves the end; `hours: 0` ends it now. The window is stored, so a restart in the middle of the work keeps it, and one that ends while Home Assistant is off ends at the next start.

When it ends nothing is replayed. Pulse Check compares what is wrong now with what was already wrong when the window began and sends one message listing the problems that appeared during it and are still there, such as a sensor that never re-paired. Only devices on the instant policy are listed; daily and weekly ones appear in their next digest as usual, and a digest whose time fell inside the window is skipped, not caught up. Reminders for older problems resume where they left off. If nothing new is wrong, nothing is sent.

### The event

Every transition also fires a `pulse_check_transition` event with `device_id`, `name`, `area`, `integration`, `issue` (`offline`, `quiet`, `battery_warning`, `battery_critical`), `kind` (`entered` or `resolved`), `severity`, `message` (in the server language), `policy`, `level` and `maintenance` (true while maintenance mode is on). The blueprint in [`blueprints/automation/pulse_check/transition_notify.yaml`](https://github.com/yog18r/pulse-check-integration/blob/main/blueprints/automation/pulse_check/transition_notify.yaml) turns those into notifications of your own design; import it from Settings → Automations → Blueprints with the file's GitHub URL. By default it stays quiet during maintenance mode too.

## Services

| Service | What it does |
| --- | --- |
| `pulse_check.snooze` | Mute a device for `days` (default 7) or `until` a time. Its facts are still reported but it counts as ok and sends nothing |
| `pulse_check.unsnooze` | Lift a snooze early |
| `pulse_check.set_device_settings` | `name`, `area`, `quiet_threshold_hours`, `battery_type`, `battery_count`, `rechargeable`, `notify_policy`, `sparkline_days`. Only given fields change; an empty value clears one |
| `pulse_check.mark_replaced` | Record a replacement now (optional `battery_type`), closing the current cycle |
| `pulse_check.mark_charged` | The same for a charge |
| `pulse_check.refresh` | Recompute now and re-read battery history |
| `pulse_check.maintenance_mode` | Hold every notification back for `hours` (default from the options; 0 ends it now). See [Maintenance mode](#maintenance-mode) |

`device_id` is the device registry id, or the entity id of a battery sensor that has no device (`sensor.remote_battery_template` or `entity:sensor.remote_battery_template`). Everything is stored in `.storage/pulse_check.data`.

## Replacement tracking

`mark_replaced` and `mark_charged` record an event; the cycle that just ended is summarised (how many days it lasted, how fast it drained). A level that rises by 20 points or more in one step is detected as a replacement by itself (a charge for devices marked rechargeable, or that were charging). Once a device has completed cycles on record, a current drain rate more than twice its own average is flagged as `unusual: "draining 3× faster than usual"`; a sudden drop of 20 points is flagged for a week. Days left always comes from the current drain estimate.

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

Entities without a `unique_id`, such as YAML template sensors and some MQTT entities, never reach the entity registry and exist only as a state. They are treated the same way: `entity:<entity_id>`, included only with a battery reading (a numeric battery sensor, a binary low-battery sensor or a `battery_level` attribute), never offline or quiet. Their integration shows as `unknown`, because a state does not say which integration made it. "Ignore these entities" leaves one out, and so do the integration and area filters (with no area, an area allow list leaves them out). Having no registry entry they have no entity category, so the config-entity rule cannot apply to them.

**Enhancers.** Optional, integration-specific extras that never break the core: Z-Wave JS node status, Zigbee2MQTT link quality and `last_seen`, ZHA LQI and RSSI.

**Days left: cycles, kinds and bases.** Every six hours the integration reads up to a year of daily battery means from the recorder's long-term statistics, plus hourly means for the last fortnight (raw state history as the fallback for sensors without statistics, attribute history for batteries that only exist as a `battery_level` attribute). It cuts each battery's history into *cycles*: a new cycle starts at a rise of 15 points or more within 48 hours (a charge or a new battery), at a `mark_replaced` or `mark_charged` call, or when a charging signal turns on. A lone reading far below both its neighbours is a glitch, not a cycle, so a lock that read 42 % for a day and then 61 % again keeps its estimate.

From the cycles each battery gets a *kind*, published as `batteryKind`:

- **charged**: the device is a phone (`mobile_app`), is marked rechargeable in its settings, has shown a charging signal, or has completed cycles with a median length under 30 days.
- **replaceable**: every cycle so far began near full (85 % or more), which is what a fresh cell looks like.
- **unknown**: anything else, such as a partial top-up. No estimate is made; nothing is ever invented.

The estimate depends on the kind, and always carries a `basis` and a `confidence` (`estimate` on the device, `daysLeft` alongside it):

| Kind | Basis | What it means |
| --- | --- | --- |
| replaceable | "trend over current cycle" | The current cycle spans at least a week of decline; days left is the level divided by the fitted rate. High confidence with two weeks or more of samples |
| replaceable | "from N previous cycles of ~D days" | Too early in the current cycle, so the device's own completed cycles are used: how many days they lasted per 100 points, scaled to the current level. Medium confidence with two or more cycles, low with one |
| replaceable | "flat for D days" | At least 90 days in the current cycle and fewer than 10 points lost: "more than a year", low confidence, `openEnded: true` |
| replaceable | "slow drain over D days" | The fit had nothing to say (too slow, or too few readings) but the current cycle spans at least a fortnight and has lost a point: the drop over the span, low confidence. Beyond a year it is "more than a year", `openEnded: true`. This is what a lock two weeks after install gets |
| charged | "until charge needed" | Days until the warning level at the rate since the last charge, from the hourly means. A device charged every day never spans enough to fit, and anything under a day is suppressed, so phones show nothing while a blind charged every couple of months shows "charge in ~N days" |

Rows are also flagged as `unusual` when the current cycle drains more than twice as fast as the median of the device's past cycles ("draining 3× faster than usual"), or when the level fell by 20 points within 48 hours in the last week ("level dropped suddenly").

## Architecture

One repository, two halves that meet at the websocket API above:

- **`custom_components/pulse_check/`**, the integration in Python, does all the work: detection, history, notifications, storage, services.
- **`frontend/`**, the card in TypeScript and React, built with Vite into one JavaScript file inside the integration folder. It renders the `pulse_check/subscribe` snapshot, fetches sparklines with `pulse_check/history` and calls the `pulse_check.*` services. See [frontend/README.md](https://github.com/yog18r/pulse-check-integration/blob/main/frontend/README.md).

The card used to be a separate repository; it moved here with its history so a single HACS install delivers both, and so the two can never be installed at mismatched versions. `manifest.json` holds the one version number; the card's build reads it from there.

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
├── websocket.py      pulse_check/subscribe and pulse_check/history for the card
├── card.py           serves the card and keeps its dashboard resource current
├── frontend/         the built card, pulse-check-card.js (not in git; built from /frontend)
├── coordinator.py    when to recompute; builds the snapshot from HA
├── history.py        battery history from the recorder, for days-left
├── notify.py         transitions, policies, reminders, digests, maintenance mode, the event
├── notify_actions.py buttons on companion-app notifications, and what they do
├── messages.py       notification text in the server's language (messages/<language>.json)
├── translations/     dialogs, entity names and services, one file per language
├── replacements.py   replacement and charge history, cycles, unusual drain
├── storage.py        the .storage file: settings, snoozes, notify state, history
├── services.py       the pulse_check.* services
├── options.py        entry.options -> the core's configuration
├── entity.py         the base entity (one "Pulse Check" service device)
├── sensor.py         the sensors
├── binary_sensor.py  the problem and maintenance mode binary sensors
├── config_flow.py    the "Add integration" and "Configure" dialogs
└── __init__.py       setup and unload
```

**The core began as a port of the card's TypeScript `src/core`** and is tested against two frozen files: `tests/fixtures/hass.json`, a mock Home Assistant with 16 devices covering every rule, and `tests/fixtures/golden.json`, the expected output for seven configurations, generated by the original TypeScript implementation before the card became a renderer. A rule change here must come with a deliberate change to the golden file.

**The coordinator** is Home Assistant's `DataUpdateCoordinator`. It listens to `state_changed`, but only a change that can alter the result gets through: an entity of an analysed device appearing, disappearing or changing availability, a battery or charging value changing, a Z-Wave node status, or a `battery_level` attribute. A new battery entity appearing counts too, since one with no registry entry brings no registry event. A power sensor reporting every second never causes a run. Relevant changes are debounced to at most one recompute every ten seconds, and a timer recomputes every five minutes so time-based transitions (quiet devices, expiring snoozes) happen on their own. Nothing time-stamped is written to entity attributes, so a recompute that changes no count leaves no new row in the recorder. Set the logger to debug to see which entity triggered each run. It copies the state machine and registries into plain dicts in the event loop, then runs the analysis in a worker thread. The analysis is pure, so it is tested without Home Assistant; the coordinator and sensor are tested with the JSON fixture loaded into a real test instance.

**Nothing is polled from devices.** `last_reported` is Home Assistant's own record of when an entity last pushed a value. Drain estimates read the recorder's database, which already holds the history; those queries run in the recorder's own worker thread.

## Development

**Integration.** Python 3.14 (what Home Assistant 2026.10 requires). On Windows, Home Assistant's test harness imports Unix-only modules, so run the tests under WSL; ruff and mypy run anywhere.

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements_dev.txt
ruff check . && ruff format --check . && mypy
pytest
```

The test suite (142 tests) runs in under half a minute.

**Card.** Node 24, in `frontend/`:

```bash
cd frontend
npm ci
npm run dev      # demo page with a fake subscription, no Home Assistant needed
npm run check    # typecheck, lint, format check, tests (92), build
```

With the demo running, `python frontend/docs/screenshots.py` retakes the README screenshots from it.

CI runs ruff, mypy, pytest, the card's checks and build, [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest/) (on the integration with the built card inside) and the HACS validation action on every push. Pushing a `v*` tag that matches `manifest.json` builds the card and publishes `pulse_check.zip` as a release.

To try a development build on a live instance, run `npm run build` in `frontend/`, delete any `__pycache__` folders, copy `custom_components/pulse_check` into `/config/custom_components/`, restart Home Assistant and refresh the browser. The card is served without long-lived cache headers, so a rebuilt card with the same version is picked up on a normal reload.

## Roadmap

Everything planned is built; [PLAN.md](https://github.com/yog18r/pulse-check-integration/blob/main/PLAN.md) records how the design got here. Still to come:

- Native-speaker review of the machine-made translations
- Submission to the HACS default store

## License

MIT
