/**
 * The payload contract, card side. `tests/fixtures/card_contract.json` is
 * what the integration emits, pinned by a Python test: a device with every
 * optional field set, a summary whose counts all differ, and one
 * `pulse_check/history` result. Here the card's parsers must read all of
 * it. Expected values are spelt out field by field, so a field the parser
 * silently drops fails the test instead of passing unnoticed.
 */
import { describe, expect, it, vi } from 'vitest';
import contract from '../../../tests/fixtures/card_contract.json';
import { loadHistories, loadHistory, parseDevice, parseSnapshot } from '../../src/card/snapshot';
import { EMPTY_SUMMARY } from '../../src/core/summarise';
import { fakeHass } from '../fixtures/snapshot';

describe('the contract device', () => {
  it('has only the fields this test checks', () => {
    // A field added to the contract must be added here too, with its check below.
    expect(Object.keys(contract.device).sort()).toEqual(
      [
        'area',
        'battery',
        'batteryCritical',
        'batteryKind',
        'batteryWarning',
        'daysLeft',
        'deviceId',
        'deviceType',
        'entityIds',
        'estimate',
        'extras',
        'integration',
        'isNotProvided',
        'isOffline',
        'isQuiet',
        'lastHeard',
        'lastReplaced',
        'manufacturer',
        'model',
        'name',
        'quietThresholdHours',
        'severity',
        'snoozedUntil',
        'source',
        'unavailableParts',
        'unusual',
        'usualLow',
      ].sort(),
    );
  });

  it('is parsed with every field kept and every date as a Date', () => {
    const device = parseDevice(contract.device);
    expect(device).toBeDefined();
    expect(device).toStrictEqual({
      deviceId: 'dev_everything',
      name: 'Everything Sensor',
      integration: 'zha',
      isOffline: false,
      isQuiet: true,
      quietThresholdHours: 36.5,
      severity: 'warning',
      deviceType: 'motion',
      extras: [{ label: 'LQI', value: '28', severity: 'warning' }],
      entityIds: ['sensor.everything_battery', 'sensor.everything_temperature'],
      area: 'Hallway',
      manufacturer: 'Aqara',
      model: 'RTCGQ11LM',
      batteryKind: 'charged',
      unusual: 'draining 3× faster than usual',
      batteryWarning: 25,
      batteryCritical: 10.5,
      battery: {
        isLow: false,
        source: 'sensor',
        entityId: 'sensor.everything_battery',
        level: 24,
        isCharging: true,
      },
      lastHeard: new Date('2026-10-15T10:00:00.000Z'),
      snoozedUntil: new Date('2026-10-16T10:00:00.000Z'),
      daysLeft: 400,
      estimate: {
        daysLeft: 400,
        basis: 'until charge needed',
        confidence: 'low',
        kind: 'charge',
        openEnded: true,
      },
      lastReplaced: new Date('2026-09-01T00:00:00.000Z'),
      isNotProvided: true,
      source: 'entity',
      usualLow: 24,
      unavailableParts: [{ entityId: 'sensor.everything_temperature', name: 'Temperature' }],
    });
    expect(device?.lastHeard).toBeInstanceOf(Date);
    expect(device?.snoozedUntil).toBeInstanceOf(Date);
    expect(device?.lastReplaced).toBeInstanceOf(Date);
  });
});

describe('the contract summary', () => {
  it('has exactly the counts the card knows', () => {
    expect(Object.keys(contract.summary).sort()).toEqual(Object.keys(EMPTY_SUMMARY).sort());
  });

  it('is parsed with every count kept', () => {
    // The counts are all different, so a count read into the wrong key shows.
    expect(parseSnapshot({ summary: contract.summary }).summary).toStrictEqual({
      attention: 1,
      critical: 2,
      warning: 3,
      batteryDevices: 4,
      lowBatteries: 5,
      criticalBatteries: 6,
      offline: 7,
      quiet: 8,
      notProvided: 9,
      snoozed: 10,
    });
  });
});

describe('the contract history result', () => {
  // `openEnded: false` is left out, as the card only sets it when true;
  // `ratePerDay` is not something the card shows.
  const EXPECTED = {
    days: 7,
    points: [{ time: 1792058400000, level: 24 }],
    estimate: {
      daysLeft: 12.5,
      basis: 'trend over current cycle',
      confidence: 'high',
      kind: 'replace',
    },
  };

  it('is parsed from pulse_check/history with its estimate and points intact', async () => {
    const { hass } = fakeHass({ history: () => contract.history });
    // Asked for 14 days: the answer's own window (7) must win.
    const history = await loadHistory(hass, 'sensor.everything_battery', 14);
    expect(history).toStrictEqual(EXPECTED);
    expect(history?.estimate?.daysLeft).toBe(12.5);
    expect(history?.estimate?.kind).toBe('replace');
    expect(history?.estimate?.openEnded).toBeUndefined();
    expect(history?.points).toEqual([{ time: 1792058400000, level: 24 }]);
  });

  it('is parsed the same from one pulse_check/histories entry', async () => {
    const { hass } = fakeHass();
    const callWS = vi.fn(() => Promise.resolve({ results: [contract.history] }));
    const histories = await loadHistories({ ...hass, callWS: callWS as never }, [
      { entityId: 'sensor.everything_battery', days: 14 },
    ]);
    expect([...histories.keys()]).toEqual(['sensor.everything_battery']);
    expect(histories.get('sensor.everything_battery')).toStrictEqual(EXPECTED);
  });
});
