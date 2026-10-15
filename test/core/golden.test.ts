/**
 * The shared golden test.
 *
 * The Pulse Check integration (github.com/yog18r/pulse-check-integration)
 * ports `src/core` to Python. To stop the two implementations drifting,
 * both are checked against the same two files:
 *
 *   test/fixtures/hass.json    the fixture from `buildHass(FIXED_NOW)`,
 *                              with `last_reported` added to every state
 *                              (the backend has it; this card does not)
 *   test/fixtures/golden.json  what `analyseDevices`, `actionList` and
 *                              `summarise` produce for a set of configs
 *
 * This test asserts the card still produces exactly the committed files
 * (they are Vitest file snapshots). When a rule changes on purpose,
 * regenerate both with
 *
 *   npm run golden:update
 *
 * and copy them into the integration repo's `tests/fixtures/`. Its CI
 * compares the copies with this repo's `main`, so a stale copy fails there.
 */
import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG, type ResolvedConfig } from '../../src/card/config';
import { actionList } from '../../src/core/actions';
import { analyseDevices, type AnalyseOptions } from '../../src/core/analyse';
import { summarise } from '../../src/core/summarise';
import type { HassLike } from '../../src/core/types';
import { ENHANCERS } from '../../src/enhancers';
import { buildHass, DEV, FIXED_NOW } from '../fixtures/hass';

/** One configuration worth checking, named so a failure says which rule broke. */
interface GoldenCase {
  name: string;
  config: Partial<ResolvedConfig>;
  /** Device id -> ISO timestamp the snooze ends. */
  snoozes?: Record<string, string>;
}

const CASES: GoldenCase[] = [
  { name: 'defaults', config: {} },
  { name: 'quiet scope all', config: { quiet_scope: 'all' } },
  {
    name: 'thresholds and device settings',
    config: {
      battery_warning: 60,
      battery_critical: 45,
      quiet_threshold_hours: 1,
      integration_thresholds: { zwave_js: 48, zha: 0.5 },
      device_settings: [
        {
          device_id: DEV.zhaTemp,
          name: 'Bedroom Climate',
          battery_type: 'CR2450',
          battery_count: 2,
        },
        { device_id: DEV.z2mMotion, battery_type: 'cr2450' },
        { device_id: DEV.phone, rechargeable: true, area: 'Office' },
        { device_id: DEV.shellyPlug, quiet_threshold_hours: 100 },
        { device_id: 'sensor.remote_battery_template', name: 'TV Remote', battery_type: 'AAA' },
        { device_id: 'entity:sensor.remote_battery_template', quiet_threshold_hours: 2 },
      ],
      exclude_entities: ['sensor.living_room_motion_linkquality'],
    },
  },
  {
    name: 'area include list',
    config: { include_areas: ['bedroom', 'Garage'], quiet_scope: 'all' },
  },
  {
    name: 'exclusions',
    config: {
      exclude_integrations: ['mobile_app'],
      exclude_devices: [DEV.z2mDoor, 'sensor.remote_battery_template'],
      exclude_areas: ['Hallway'],
      exclude_entities: ['sensor.mr_roboto_battery'],
    },
  },
  {
    name: 'integration include list with area override',
    config: {
      include_integrations: ['zha', 'MQTT', 'template'],
      include_areas: ['living room', 'hallway'],
      device_settings: [{ device_id: 'sensor.remote_battery_template', area: 'Living Room' }],
    },
  },
  {
    name: 'snoozes',
    config: {},
    snoozes: {
      [DEV.zwaveLock]: '2027-01-01T00:00:00.000Z',
      [DEV.z2mMotion]: '2020-01-01T00:00:00.000Z',
      [DEV.smokeAlarm]: '2026-10-16T10:00:00.000Z',
    },
  },
];

/** The fixture with `last_reported` on every state, as the backend would see it. */
function fixtureWithLastReported(): HassLike {
  const hass = buildHass(FIXED_NOW);
  const states = Object.fromEntries(
    Object.entries(hass.states).map(([id, s]) => [id, { ...s, last_reported: s.last_updated }]),
  );
  return { ...hass, states };
}

/** Dates become ISO strings and undefined keys disappear, exactly as JSON does. */
function plain(value: unknown): unknown {
  return JSON.parse(JSON.stringify(value));
}

/** Pretty JSON with a trailing newline, the way the files are committed. */
function pretty(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function computeGolden(hass: HassLike) {
  const now = FIXED_NOW;
  return {
    now: now.toISOString(),
    cases: CASES.map((c) => {
      const config = { ...DEFAULT_CONFIG, ...c.config };
      const options: AnalyseOptions = { now, enhancers: ENHANCERS };
      if (c.snoozes) {
        options.snoozes = new Map(
          Object.entries(c.snoozes).map(([id, iso]) => [id, new Date(iso)]),
        );
      }
      const devices = analyseDevices(hass, config, options);
      const actions = actionList(devices, config);
      const compact = (items: typeof actions.replace) =>
        items.map(({ device, ...rest }) => ({
          kind: rest.kind,
          deviceId: device.deviceId,
          name: device.name,
          severity: rest.severity,
          batteryType: rest.batteryType,
          count: rest.count,
          label: rest.label,
        }));
      return {
        name: c.name,
        config: c.config,
        snoozes: c.snoozes,
        devices: plain(devices),
        actions: {
          replace: compact(actions.replace),
          charge: compact(actions.charge),
          shopping: actions.shopping,
        },
        summary: summarise(devices, config),
      };
    }),
  };
}

describe('shared golden output', () => {
  const hass = fixtureWithLastReported();

  it('the committed fixture is the current buildHass output', async () => {
    await expect(pretty(hass)).toMatchFileSnapshot('../fixtures/hass.json');
  });

  it('the card still produces the committed golden output', async () => {
    await expect(pretty(computeGolden(hass))).toMatchFileSnapshot('../fixtures/golden.json');
  });
});
