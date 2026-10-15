import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../../src/card/config';
import { analyseDevices } from '../../src/core/analyse';
import { ORPHAN_PREFIX } from '../../src/core/group';
import { shoppingList, UNKNOWN_BATTERY_TYPE } from '../../src/core/shopping';
import { DEV, FIXED_NOW, hass } from '../fixtures/hass';

const devices = analyseDevices(hass, DEFAULT_CONFIG, { now: FIXED_NOW });

describe('shoppingList', () => {
  it('lists only devices that need a battery, all under unknown when untyped', () => {
    const groups = shoppingList(devices, DEFAULT_CONFIG);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.batteryType).toBe(UNKNOWN_BATTERY_TYPE);
    expect(groups[0]?.isUnknown).toBe(true);
    expect(groups[0]?.devices.map((d) => d.deviceId).sort()).toEqual(
      [
        DEV.smokeAlarm, // binary low
        DEV.z2mMotion, // 12%
        DEV.zhaTemp, // 28%
        ORPHAN_PREFIX + 'sensor.remote_battery_template', // 9%
      ].sort(),
    );
  });

  it('groups by battery_type from device_overrides, typed groups first', () => {
    const config = {
      ...DEFAULT_CONFIG,
      device_overrides: [
        { device_id: DEV.z2mMotion, battery_type: 'CR2450' },
        { device_id: DEV.zhaTemp, battery_type: 'CR2032' },
        { device_id: DEV.smokeAlarm, battery_type: 'CR2032' },
        { device_id: DEV.z2mDoor, battery_type: 'CR1632' }, // 87%, not needed
      ],
    };
    const groups = shoppingList(devices, config);
    expect(groups.map((g) => g.batteryType)).toEqual(['CR2032', 'CR2450', UNKNOWN_BATTERY_TYPE]);
    expect(groups[0]?.devices.map((d) => d.name)).toEqual([
      'Bedroom Temp & Humidity',
      'Hallway Smoke Alarm',
    ]);
    expect(groups[2]?.devices).toHaveLength(1); // just the orphan remote
  });

  it('is empty when every battery is healthy', () => {
    const healthy = devices.filter((d) => (d.battery?.level ?? 0) > 50);
    expect(shoppingList(healthy, DEFAULT_CONFIG)).toEqual([]);
  });
});
