# Pulse Check Card

A universal device health card for [Home Assistant](https://www.home-assistant.io/). One card, every protocol: it shows which devices are **low on battery**, which are **offline**, and which have **gone quiet**, across Zigbee, Z-Wave, Matter, Bluetooth, ESPHome, Shelly, Wi-Fi and the companion app.

Fully local. One file to install. No HACS required (but supported).

<p align="center">
  <img src="docs/screenshot-batteries.jpg" alt="Batteries tab in a dark theme: devices sorted lowest battery first with coloured bars" width="420" />
  <img src="docs/screenshot-connectivity.jpg" alt="Connectivity tab in a light theme: one offline lock and three quiet devices" width="420" />
</p>

<p align="center"><em>Rendered from the demo page with mock data. Dark and light HA themes.</em></p>

[![CI](https://github.com/yog18r/pulse-check-card/actions/workflows/ci.yml/badge.svg)](https://github.com/yog18r/pulse-check-card/actions/workflows/ci.yml)

---

## The problem

Devices quietly drop off. A door sensor's coin cell dies on a Tuesday, and you find out three weeks later when an automation never fires. A Z-Wave node goes dead after a power blip. A Wi-Fi plug loses its connection and sits there reporting its last known state forever.

Home Assistant has all the data to spot this, but it is spread across hundreds of entities. Pulse Check Card pulls it into one place:

- **🔋 Batteries**: every battery-powered device, lowest first, with a coloured bar
- **📡 Connectivity**: anything offline or not heard from within a threshold
- **🛒 Shopping** (optional tab): which batteries to buy, grouped by type
- **Snooze** a device for 1, 7 or 30 days when you already know about it
- **Trend sparklines** next to each battery bar, from the same 14-day history
- **Row cap** with "show more", and **area and integration filters** for per-room cards
- **Charging awareness**: a docked vacuum or a phone on the charger is never "low"
- **"Replace soon" ordering** (optional): uses each battery's drain rate from HA's recorder to put the ones about to die first, even when their percentage still looks fine

Everything is grouped by **device**, not entity, so each physical thing appears once. Tap a row to jump to that device's page in Home Assistant.

## Installation

### Option 1: manual (recommended, no dependencies)

1. Download `pulse-check-card.js` from the [latest release](https://github.com/yog18r/pulse-check-card/releases/latest) (or build it yourself, see below).
2. Copy it to your Home Assistant `config/www/` folder.
3. In Home Assistant go to **Settings → Dashboards → ⋮ → Resources → Add resource**:
   - URL: `/local/pulse-check-card.js`
   - Type: **JavaScript module**
4. Refresh the browser. "Pulse Check Card" now appears in the card picker.

### Option 2: HACS

Add this repository as a custom repository in HACS (category: Dashboard), then install it. HACS adds the resource for you.

### Minimal card config

```yaml
type: custom:pulse-check-card
```

That is all you need. Everything else has a sensible default.

## Configuration

```yaml
type: custom:pulse-check-card
title: Pulse Check
battery_warning: 30 # % at or below this is a warning (orange)
battery_critical: 15 # % at or below this is critical (red)
quiet_threshold_hours: 24 # no update for this long = "quiet"
integration_thresholds: # per-integration overrides for quiet_threshold_hours
  zwave_js: 48 # sleeping Z-Wave sensors report rarely
  mqtt: 12
device_overrides: # per-device overrides
  - device_id: abc123
    quiet_threshold_hours: 72
    battery_type: CR2032 # free text, used by the upcoming shopping list
exclude_integrations: [mobile_app] # hide phones
exclude_devices: [] # device ids (or an entity id for device-less entities)
exclude_entities: [] # entity ids to ignore, e.g. a settings sensor labelled as a battery
quiet_scope: battery # "battery" (default) or "all": which devices can be flagged quiet
battery_sort: level # "level" (default) or "replace_soon": order of the Batteries tab
max_rows: 12 # rows per tab before "Show N more"; a number or "all"
show_sparklines: true # 14-day trend line next to each battery bar
include_areas: [] # only devices in these areas (names or ids); empty = all
exclude_areas: []
include_integrations: [] # only these integrations; empty = all
show_tabs: [batteries, connectivity] # add "shopping" for the battery shopping list
default_tab: batteries
```

Prefer clicking to typing? The card has a **visual editor**: add the card from the picker, or press "Edit" on an existing one, and every option above is a form field. Integration thresholds and device overrides are rows you add and remove, with dropdowns of the integrations and devices that actually exist in your instance, so you never have to look up a device id.

| Option                   | Type    | Default                     | Notes                                                              |
| ------------------------ | ------- | --------------------------- | ------------------------------------------------------------------ |
| `title`                  | string  | `Pulse Check`               |                                                                    |
| `battery_warning`        | number  | `30`                        | 0–100. Inclusive: 30% counts as a warning.                         |
| `battery_critical`       | number  | `15`                        | 0–100. Must not exceed `battery_warning`.                          |
| `quiet_threshold_hours`  | number  | `24`                        | Hours since the device's newest `last_updated`.                    |
| `integration_thresholds` | mapping | `{}`                        | `platform: hours`. Platform is the integration domain (see badge). |
| `device_overrides`       | list    | `[]`                        | Each item needs `device_id`.                                       |
| `exclude_integrations`   | list    | `[]`                        |                                                                    |
| `exclude_devices`        | list    | `[]`                        |                                                                    |
| `exclude_entities`       | list    | `[]`                        | Removes single entities from consideration.                        |
| `quiet_scope`            | string  | `battery`                   | `battery` or `all`. See "Quiet" below.                             |
| `battery_sort`           | string  | `level`                     | `level` or `replace_soon`. See \"Replace soon\" below.             |
| `max_rows`               | number  | `12`                        | Or `all`. Applies to the Batteries and Connectivity tabs.          |
| `show_sparklines`        | boolean | `true`                      | Needs recorder history; hidden otherwise.                          |
| `include_areas`          | list    | `[]`                        | Area names or ids. Devices with no area are dropped when set.      |
| `exclude_areas`          | list    | `[]`                        |                                                                    |
| `include_integrations`   | list    | `[]`                        | Allow-list counterpart of `exclude_integrations`.                  |
| `show_tabs`              | list    | `[batteries, connectivity]` | Any of `batteries`, `connectivity`, `shopping`.                    |
| `default_tab`            | string  | `batteries`                 | Must be in `show_tabs`.                                            |

Invalid config shows a plain-English error on the card, for example `"battery_critical" (40) must not be higher than "battery_warning" (30).`

**Finding a device id:** open the device in **Settings → Devices & services → Devices**. The id is the last part of the URL: `/config/devices/device/<device_id>`.

## How detection works

The card reads only what the Home Assistant frontend already has in memory (`hass.states`, `hass.entities`, `hass.devices`, `hass.areas`). No API calls, no polling, no cloud.

**Battery** (first match wins per entity; the best reading per device is kept):

1. `sensor.*` with `device_class: battery` and a numeric state → level in %
2. `binary_sensor.*` with `device_class: battery` → `on` means **low**
3. Any entity with a numeric `battery_level` attribute → level in % (older and custom integrations)

If a device has several readings, the lowest numeric level wins (the weakest cell matters), and any binary "low" flags the device regardless.

**Offline:** every _primary_ entity of the device is `unavailable`. Primary means no `entity_category`; diagnostic and config entities are ignored because integrations handle those inconsistently.

**Quiet:** the newest `last_updated` across the device's _live_ entities is older than the threshold. Static entities are ignored when working this out: anything with `entity_category: config`, and the `number`, `select`, `button`, `update`, `text`, `scene` and `script` domains, because those only change when a person changes a setting. Threshold resolution: device override → integration override → global default.

By default only **battery-powered devices** can be quiet (`quiet_scope: battery`). Those are the ones that die silently. Mains-powered devices announce failure by going `unavailable`, and a light nobody has toggled for two days is simply a light nobody has toggled, so flagging it would bury the real problems. Set `quiet_scope: all` if you want every device judged.

**Settings are not batteries.** Some integrations expose configuration values with `device_class: battery` because the unit is `%` (an inverter's minimum state of charge, say). Entities with `entity_category: config` are never read as batteries. If an integration forgets to categorise such an entity, drop it with `exclude_entities`.

**Severity:** critical for offline, battery at/below critical, or binary low. Warning for battery at/below warning, or quiet. The header counts anything that is not OK.

**Skipped on purpose:** service devices (Sun, Forecast…), disabled devices, excluded integrations/devices/entities, and entities with no device that carry no battery information. An entity with no device can only ever contribute a battery reading; with no hardware behind it there is nothing to be offline or quiet.

**Replace soon** (`battery_sort: replace_soon`): the card asks Home Assistant's recorder for 14 days of daily averages of every battery sensor, once when the card loads and then every 6 hours, and fits a straight line through them. The slope is the drain rate; the current level divided by it is the time left, shown on each row as "~12d left". The live reading is added as the last point, so a battery that just dropped sharply moves straight away rather than waiting for the recorder's hourly statistics. The fit needs at least 3 days of history and ignores flat or rising series (a phone that gets charged, a lock sitting at 62% for a fortnight), so those devices simply keep their level-based position and show no estimate. Treat the number as an order of magnitude: locks and other motorised devices report in coarse steps and under load, and the estimate will wander for a few days after a sudden drop. Without a recorder nothing changes.

**Sparklines:** the same 14 days of daily means that feed the drain estimate are drawn as a small trend line beside the battery bar, scaled to the data so a slow decline is visible. No extra requests; if there is no history, there is no line.

**Row cap and filters:** `max_rows` (default 12, or `all`) limits each of the Batteries and Connectivity tabs, with a "Show N more" control so nothing is hidden silently. `include_areas` / `exclude_areas` and `include_integrations` / `exclude_integrations` scope the card, which is how you put a per-room card on a sections dashboard: `include_areas: [Office]`. Area filters accept the name shown in Home Assistant or the area id, case-insensitively.

**Shopping list** (`show_tabs` including `shopping`): every device at or below the warning threshold, grouped by the `battery_type` you set in `device_overrides`. There is no reliable way to know from Home Assistant's data that a sensor takes a CR2032, so untyped devices sit in an "Unknown type" group until you tell the card.

**Charging:** a device that says it is charging is never flagged for battery, whatever its level, and sorts last within its band. The card recognises the standard `battery_charging` binary sensor, companion-app "battery state" sensors reading charging/full, a vacuum that is `docked`, and the `is_charging` / `charging` / `battery_state` attributes some integrations use.

**On-demand `last_reported` lookup:** once a device is flagged quiet, the card asks Home Assistant's REST API for the true `last_reported` of that device's live entities (`GET /api/states/<entity_id>`). Unlike `last_updated`, that timestamp moves on every report, even when the value is unchanged, so a sensor that keeps saying "21.4 °C" stops looking dead. This is a question to the Home Assistant server about data it already holds. **Nothing is sent to any device**, so it cannot wake a sensor or cost it battery. It is also deliberately frugal: only entities of quiet devices, each asked at most once every 5 minutes, at most 40 per round.

**Snooze:** the 💤 button on any flagged row hides that device from the counts, the Connectivity tab and the shopping list for 1, 7 or 30 days. Snoozes are stored in your browser, not in the card config, so they are per browser and need no YAML edit. A footer shows how many are snoozed and lets you un-snooze. The Batteries tab still lists a snoozed device, greyed and badged, because it is still a battery.

### Known limitations

- **`last_reported` is not available in the frontend.** Home Assistant tracks a `last_reported` timestamp (updated even when a value is re-sent unchanged), but the websocket subscription that feeds the dashboard only carries `last_changed` and `last_updated`. The on-demand lookup above closes most of that gap, but it only runs for devices already flagged quiet and refreshes every 5 minutes, so a device can appear quiet for up to a few minutes before the lookup clears it.
- **Sleeping devices look quiet.** Battery Z-Wave and Zigbee sensors may only wake every day or two. Use `integration_thresholds` (e.g. `zwave_js: 48`).
- **Mains devices are only judged by availability.** With the default `quiet_scope: battery`, a mains device shows up only when it is `unavailable`. A Wi-Fi device that silently stops responding but that its integration never marks unavailable will not be caught. `quiet_scope: all` catches it, at the cost of noise from idle lights and media players.
- **Powered-off media players show as offline.** A TV that is switched off is `unavailable` to Home Assistant, which is indistinguishable from a TV that has lost its network. Exclude them with `exclude_integrations` or `exclude_devices` if that is not useful to you.
- **Battery-less devices only appear on the Connectivity tab**, and only when something is wrong. A healthy mains-powered device is invisible, by design.

## Architecture

```
src/
├── index.ts                  registers <pulse-check-card>, adds it to the card picker
├── card/
│   ├── PulseCheckCardElement.ts   the HA card contract: setConfig, hass setter, sizes
│   ├── PulseCheckCardEditor.ts    the visual editor element (fires config-changed)
│   ├── config.ts                  CardConfig → ResolvedConfig with validation
│   ├── navigation.ts              open a device page / more-info from a row
│   ├── statistics.ts              recorder websocket call → drain estimates
│   ├── lastReported.ts            REST lookup of true last_reported (rate limited)
│   └── snoozeStore.ts             snoozes in localStorage, pure helpers + storage
├── core/                     pure TypeScript, no React, no DOM, 100% unit-testable
│   ├── battery.ts            detection rules 1–3
│   ├── availability.ts       offline / last heard / quiet
│   ├── group.ts              entities → one group per device
│   ├── thresholds.ts         threshold resolution and severity
│   ├── analyse.ts            the orchestrator: hass + config → DeviceHealth[]
│   ├── drain.ts              drain rate and days-left from history samples
│   ├── shopping.ts           batteries to buy, grouped by type
│   ├── sort.ts, summarise.ts, time.ts, fingerprint.ts
├── enhancers/                optional per-integration extras (Enhancer interface)
└── ui/                       React components, hooks (useNow, useDrainEstimates,
                              useLastReported, useSnoozes), two stylesheets
```

**Universal core + optional enhancers.** The core uses only data every integration provides. An _enhancer_ implements one small interface and adds detail when, and only when, the data exists. Enhancers can never break the card: each call is isolated, and returning nothing is always valid. Adding one is a new file plus one line in the registry.

An enhancer returns three things, all optional: `extras` (badges for the row), a better `lastHeard` timestamp, and an `offline` verdict. The core merges them with its own generic rules, so an integration that knows more can override the heuristics.

| Enhancer    | Integration | What it reads                                    | What it adds                                                               |
| ----------- | ----------- | ------------------------------------------------ | -------------------------------------------------------------------------- |
| Z-Wave JS   | `zwave_js`  | the diagnostic _Node status_ sensor              | `Node: alive/asleep/dead` badge; a **dead** node is offline                |
| Zigbee2MQTT | `mqtt`      | `linkquality`, and `last_seen` if enabled in Z2M | `LQI` badge (warning at ≤30); `last_seen` replaces the timestamp heuristic |
| ZHA         | `zha`       | the optional `lqi` and `rssi` diagnostic sensors | `LQI` badge (warning at ≤30) and `RSSI` badge                              |

Plain MQTT devices that aren't from Zigbee2MQTT simply get no badges.

**Why React inside a custom element?** Home Assistant talks to a plain `HTMLElement`. That element owns a shadow root (CSS isolation both ways) and a React root inside it. The element decides _when_ to render: HA pushes a new `hass` object on every state change in the house, so the setter computes a cheap fingerprint of just the entities the card depends on and skips the render when it hasn't moved. React decides _what_ to render, with `useMemo` caching the analysis between tab clicks.

**Single file, no runtime dependencies.** Vite's library mode bundles React and the stylesheet into one ES module. Nothing is fetched at runtime.

## Development

```bash
npm install
npm run dev          # demo page at http://localhost:5173 with mock data, no HA needed
npm test             # Vitest unit tests
npm run check        # typecheck + lint + format + test + build, same as CI
npm run build        # dist/pulse-check-card.js
```

The demo page renders the real card element with a realistic mock `hass` (Zigbee2MQTT, ZHA, Z-Wave JS, ESPHome, Shelly, Matter, phone, binary battery sensor, attribute fallback, offline and stale devices). It has a dark mode toggle and a few config scenarios, including a deliberately broken one to show error handling.

The same fixture drives the unit tests, so every detection, grouping, threshold and sorting rule is pinned by a test that reads like a spec.

## Roadmap

- [x] **Phase 1 (MVP):** card contract, universal detection, both tabs, config with defaults, theming, unit tests, demo page, CI
- [x] **Phase 2:** Z-Wave JS, Zigbee2MQTT and ZHA enhancers; tap a row to open the device page (or the more-info dialog for device-less entities); header breakdown and per-row threshold hints
- [x] **Phase 3:** "replace soon" ordering using drain rate from HA statistics; battery shopping list grouped by `battery_type`; visual config editor
- [x] **v0.2:** charging awareness; on-demand `last_reported` lookup; snooze; visual editor rows for thresholds and overrides
- [x] **v0.3:** trend sparklines; configurable row cap; area and integration filters; editor checkbox pickers for both
- [ ] **Ideas:** a problems-only toggle on the Batteries tab; translations; HACS default-repository submission

## Licence

MIT
