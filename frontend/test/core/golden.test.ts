/**
 * The card's own rules against the golden fixture Python is checked
 * against (`tests/fixtures/golden.json`, see `tests/core/test_golden.py`).
 * Each case holds the devices the integration computed for one set of
 * options, the summary and the action list.
 *
 * The card does not decide whether a device is offline, quiet or not
 * provided, nor its overall severity: it reads those from the payload. So
 * this checks only what the card computes itself: the header counts
 * (`summarise`, which the card recomputes for a filtered view) and each
 * device's battery severity (`deviceBatterySeverity`, which colours the
 * Batteries tab and decides what counts as low).
 */
import { describe, expect, it } from 'vitest';
import goldenJson from '../../../tests/fixtures/golden.json';
import { parseSnapshot } from '../../src/card/snapshot';
import { summarise } from '../../src/core/summarise';
import {
  connectivitySeverity,
  deviceBatterySeverity,
  SEVERITY_RANK,
  type Thresholds,
} from '../../src/core/thresholds';
import type { Severity } from '../../src/core/types';

interface GoldenAction {
  deviceId: string;
  severity: Severity;
}

interface GoldenCase {
  name: string;
  config: { battery_warning?: number; battery_critical?: number };
  devices: unknown[];
  actions: { replace: GoldenAction[]; charge: GoldenAction[] };
  summary: Record<string, number>;
}

const golden = goldenJson as unknown as { now: string; cases: GoldenCase[] };

/** The integration's defaults, which a case's options override. */
function thresholdsOf(c: GoldenCase): Thresholds {
  return {
    battery_warning: c.config.battery_warning ?? 30,
    battery_critical: c.config.battery_critical ?? 15,
  };
}

function worst(...severities: Severity[]): Severity {
  return severities.reduce((a, b) => (SEVERITY_RANK[b] > SEVERITY_RANK[a] ? b : a), 'ok');
}

describe('the golden fixture', () => {
  it('has the seven cases the Python test runs', () => {
    expect(golden.cases).toHaveLength(7);
  });
});

describe.each(golden.cases.map((c) => [c.name, c] as const))('golden case "%s"', (_name, c) => {
  const devices = parseSnapshot({ devices: c.devices }).devices;
  const thresholds = thresholdsOf(c);

  it('parses every device', () => {
    expect(devices).toHaveLength(c.devices.length);
  });

  it("gives the case's summary", () => {
    const summary = summarise(devices, thresholds);
    // The golden summary predates criticalBatteries and notProvided:
    // compare the counts it has, as the Python test does.
    const ours = Object.fromEntries(
      Object.keys(c.summary).map((key) => [key, summary[key as keyof typeof summary]]),
    );
    expect(ours).toEqual(c.summary);
  });

  it('judges each battery as the integration did', () => {
    // The action list holds every battery that is low and not snoozed, at
    // the integration's battery severity; any other battery is "ok".
    const expected = new Map(
      [...c.actions.replace, ...c.actions.charge].map((a) => [a.deviceId, a.severity]),
    );
    const judged = devices.filter((d) => d.battery && !d.snoozedUntil);
    expect(judged.length).toBeGreaterThan(0);
    for (const d of judged) {
      expect(deviceBatterySeverity(d, thresholds), d.deviceId).toBe(
        expected.get(d.deviceId) ?? 'ok',
      );
    }
    // And no action names a device the card would call "ok" or cannot see.
    const ids = new Set(judged.map((d) => d.deviceId));
    for (const id of expected.keys()) expect(ids, id).toContain(id);
  });

  it("agrees with each device's severity from its battery, connectivity and badges", () => {
    for (const d of devices) {
      const extras = d.extras.map((e) => e.severity ?? 'ok');
      const severity = d.snoozedUntil
        ? 'ok'
        : worst(
            deviceBatterySeverity(d, thresholds),
            connectivitySeverity(d.isOffline, d.isQuiet, d.isNotProvided),
            ...extras,
          );
      expect(severity, d.deviceId).toBe(d.severity);
    }
  });
});
