import { describe, expect, it } from 'vitest';
import { parseSnapshot } from '../../src/card/snapshot';
import { batteryList, connectivityList, sortableBatteryLevel } from '../../src/core/sort';
import type { DeviceHealth } from '../../src/core/types';
import { SNAPSHOT_PAYLOAD } from '../fixtures/snapshot';

const snapshot = parseSnapshot(SNAPSHOT_PAYLOAD);
const { devices, config: thresholds } = snapshot;
const names = (list: DeviceHealth[]) => list.map((d) => d.name);

describe('batteryList', () => {
  it('shows every battery device, worst severity first, then lowest level', () => {
    const list = names(batteryList(devices, thresholds));
    expect(list).toEqual([
      'Hallway Smoke Alarm', // binary low: critical, sorts above every level
      'TV Remote Battery', // 9 %
      'Living Room Motion', // 12 %
      'Bedroom Temp & Humidity', // 28 %, warning
      'Window Sensor', // 40 %
      'Dog Collar Tracker', // 44 %
      'Garage Multisensor', // 55 %
      'Pixel 9', // 71 %
      'Front Door Sensor', // 87 %
      'Kitchen H&T', // 92 %
      'Mr Roboto', // 18 % but charging: last
    ]);
  });

  it('replace_soon puts the fewest days left first, using the integration estimates', () => {
    const withDays = devices.map((d) => (d.name === 'Window Sensor' ? { ...d, daysLeft: 3 } : d));
    const list = names(batteryList(withDays, thresholds, 'replace_soon'));
    // Critical rows stay on top; within the ok band the 40 % sensor with
    // 3 days left now beats the 44 % tracker without an estimate.
    expect(list.indexOf('Window Sensor')).toBeLessThan(list.indexOf('Dog Collar Tracker'));
    expect(list.slice(0, 3)).toEqual([
      'Hallway Smoke Alarm',
      'TV Remote Battery',
      'Living Room Motion',
    ]);
  });

  it('prefers a fetched history estimate over the snapshot one', () => {
    const drains = new Map([
      ['sensor.kitchen_ht_battery', { estimate: { ratePerDay: 50, daysLeft: 1, samples: 5 } }],
    ]);
    const list = names(batteryList(devices, thresholds, 'replace_soon', drains));
    expect(list[3]).toBe('Bedroom Temp & Humidity'); // still the only warning
    expect(list[4]).toBe('Kitchen H&T'); // 1 day left beats every ok level
  });

  it('sortableBatteryLevel puts binary low first and binary ok last', () => {
    const low = devices.find((d) => d.name === 'Hallway Smoke Alarm')!;
    expect(sortableBatteryLevel(low)).toBe(-1);
    expect(sortableBatteryLevel({ ...low, battery: { ...low.battery!, isLow: false } })).toBe(101);
    const noBattery = { ...low };
    delete noBattery.battery;
    expect(sortableBatteryLevel(noBattery)).toBe(Number.POSITIVE_INFINITY);
  });
});

describe('connectivityList', () => {
  it('lists only problems: offline first, then the quietest', () => {
    expect(names(connectivityList(devices))).toEqual([
      'Front Door Lock', // offline
      'Garage Multisensor', // quiet 40 h
      'Bedroom Temp & Humidity', // quiet 30 h
    ]);
  });

  it('leaves snoozed devices out', () => {
    const snoozed = devices.map((d) =>
      d.name === 'Front Door Lock' ? { ...d, snoozedUntil: new Date('2027-01-01') } : d,
    );
    expect(names(connectivityList(snoozed))).not.toContain('Front Door Lock');
  });
});
