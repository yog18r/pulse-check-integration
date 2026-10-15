# Pulse Check Card (frontend)

> This folder used to be its own repository, [github.com/yog18r/pulse-check-card](https://github.com/yog18r/pulse-check-card). It moved here, history included, so one install of the [Pulse Check integration](../README.md) delivers the card too. Installation, the card's options and what it shows are in the [main README](../README.md#the-card).

The dashboard card for Pulse Check, in TypeScript and React. Vite builds it into one JavaScript file, `../custom_components/pulse_check/frontend/pulse-check-card.js`, which the integration serves and registers as a dashboard resource. That file is not committed; CI and the release workflow build it.

## How it talks to the integration

The integration registers two websocket commands. The card subscribes to `pulse_check/subscribe` and receives a full snapshot immediately and again after every recompute (about ten seconds after a relevant state change, and at least every five minutes): one entry per device with its battery, offline, quiet and severity facts, days left, the summary counts, the action list, the thresholds in force and the per-device settings. Sparklines come from `pulse_check/history`, which reads the recorder on the server. Snooze, unsnooze, Done and the editor's per-device settings are service calls; the next snapshot shows the result.

The browser never queries the recorder or analyses entities. A new `hass` object from Home Assistant does not re-render the card; only a new snapshot does.

Rows on the Batteries tab are coloured by the battery alone and rows on the Connectivity tab by connectivity alone, using the thresholds the integration sent, so the header (computed by the integration) and the rows can never disagree.

## Architecture

```
src/
├── core/
│   ├── types.ts            the wire shape (DeviceHealth) and the slice of hass the card reads
│   ├── sort.ts             ordering for the Batteries and Connectivity tabs
│   ├── grouping.ts         sections by area, integration or device type
│   ├── thresholds.ts       battery / connectivity severity for row colours
│   ├── summarise.ts        headline and breakdown text
│   ├── registryOptions.ts  device lists for the editor's picker
│   └── batteryTypes.ts     common battery sizes for the editor
├── card/
│   ├── config.ts           the presentation options, validated
│   ├── snapshot.ts         subscription, history and service calls
│   ├── PulseCheckCardElement.ts   the custom element HA talks to
│   └── PulseCheckCardEditor.ts    the visual editor element
├── ui/                     React components and hooks (useSnapshot, useHistory)
├── demo/                   the dev page's fake Home Assistant
└── index.ts                registers the elements and the card picker entry
```

The custom element owns a shadow root and a React root. `useSnapshot` subscribes once per websocket connection and unsubscribes on unmount; `useHistory` fetches sparkline points for the batteries on screen and refreshes them every six hours.

The card has no version of its own: the build reads `version` from the integration's `manifest.json` and prints it in the browser console banner.

## Development

Node 24.

```bash
npm ci
npm run dev      # demo page with a fake subscription, no HA needed
npm run check    # typecheck, lint, format check, tests, build
npm run build    # just the bundle, into the integration folder
```

Component tests (Testing Library) render the real React tree against a canned snapshot (`test/fixtures/snapshot.json`, 15 devices from the integration's test fixture) and check what a user sees and what the clicks send. The detection rules themselves are tested on the Python side against a frozen golden file (`tests/fixtures/golden.json`).

To try a build on a live instance, see Development in the [main README](../README.md#development).
