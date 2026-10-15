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
      'Garden Soil Sensor', // 22 %, warning
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

  it('name sorts alphabetically within each severity band', () => {
    const list = names(batteryList(devices, thresholds, 'name'));
    // Critical band first (alphabetical), then the warnings, then the rest by name.
    expect(list.slice(0, 3)).toEqual([
      'Hallway Smoke Alarm',
      'Living Room Motion',
      'TV Remote Battery',
    ]);
    expect(list.slice(3, 5)).toEqual(['Bedroom Temp & Humidity', 'Garden Soil Sensor']);
    expect(list.slice(5, 11)).toEqual([
      'Dog Collar Tracker',
      'Front Door Sensor',
      'Garage Multisensor',
      'Kitchen H&T',
      'Pixel 9',
      'Window Sensor',
    ]);
  });

  it('replace_soon: estimates first by days left, then devices without one by level', () => {
    const tweaked = devices.map((d) => {
      if (d.name === 'Front Door Sensor') {
        return {
          ...d,
          daysLeft: 400,
          estimate: {
            daysLeft: 400,
            basis: 'flat for 120 days',
            confidence: 'low',
            kind: 'replace',
            openEnded: true,
          } as const,
        };
      }
      if (d.name === 'Window Sensor') {
        return {
          ...d,
          daysLeft: 3,
          estimate: {
            daysLeft: 3,
            basis: 'trend over current cycle',
            confidence: 'high',
            kind: 'replace',
          } as const,
        };
      }
      if (d.name === 'Kitchen H&T') {
        return {
          ...d,
          daysLeft: 20,
          estimate: {
            daysLeft: 20,
            basis: 'until charge needed',
            confidence: 'medium',
            kind: 'charge',
          } as const,
        };
      }
      return d;
    });
    const list = names(batteryList(tweaked, thresholds, 'replace_soon'));
    // Critical rows stay on top whatever the estimates say.
    expect(list.slice(0, 3)).toEqual([
      'Hallway Smoke Alarm',
      'TV Remote Battery',
      'Living Room Motion',
    ]);
    // Within the ok band: the three estimates ascending whatever their
    // basis, then the devices without one by level. Nothing is invented.
    expect(list.slice(5, 11)).toEqual([
      'Window Sensor',
      'Kitchen H&T',
      'Front Door Sensor',
      'Dog Collar Tracker',
      'Garage Multisensor',
      'Pixel 9',
    ]);
  });

  it('prefers a fetched history estimate over the snapshot one', () => {
    const drains = new Map([
      [
        'sensor.kitchen_ht_battery',
        {
          estimate: {
            daysLeft: 1,
            basis: 'trend over current cycle',
            confidence: 'high',
            kind: 'replace',
          } as const,
        },
      ],
    ]);
    const list = names(batteryList(devices, thresholds, 'replace_soon', drains));
    // Still the two warnings, by level.
    expect(list.slice(3, 5)).toEqual(['Garden Soil Sensor', 'Bedroom Temp & Humidity']);
    expect(list[5]).toBe('Kitchen H&T'); // 1 day left beats every level
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
