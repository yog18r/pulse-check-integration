import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../../src/card/config';
import { actionList, UNKNOWN_BATTERY_TYPE } from '../../src/core/actions';
import { analyseDevices } from '../../src/core/analyse';
import { ORPHAN_PREFIX } from '../../src/core/group';
import { DEV, FIXED_NOW, hass } from '../fixtures/hass';

const devices = analyseDevices(hass, DEFAULT_CONFIG, { now: FIXED_NOW });

describe('actionList', () => {
  it('turns every low battery into a replace action when nothing is configured', () => {
    const list = actionList(devices, DEFAULT_CONFIG);
    expect(list.charge).toEqual([]);
    expect(list.replace.map((a) => a.device.deviceId)).toEqual([
      // critical first, alphabetical within: Hallway Smoke Alarm, Living Room Motion, TV Remote
      DEV.smokeAlarm,
      DEV.z2mMotion,
      ORPHAN_PREFIX + 'sensor.remote_battery_template',
      // then the 28% warning
      DEV.zhaTemp,
    ]);
    expect(list.replace[0]?.label).toBe('Replace the battery in Hallway Smoke Alarm');
    expect(list.shopping).toEqual([{ batteryType: UNKNOWN_BATTERY_TYPE, count: 4, devices: 4 }]);
  });

  it('uses type, count and rechargeable from device_settings', () => {
    const config = {
      ...DEFAULT_CONFIG,
      device_settings: [
        { device_id: DEV.z2mMotion, battery_type: 'CR2450' },
        { device_id: DEV.zhaTemp, battery_type: 'AAA', battery_count: 2 },
        { device_id: DEV.smokeAlarm, battery_type: 'AAA', battery_count: 3 },
        { device_id: DEV.z2mDoor, battery_type: 'CR1632' }, // 87%: not needed
      ],
    };
    const list = actionList(devices, config);
    const labels = list.replace.map((a) => a.label);
    expect(labels).toEqual([
      'Replace 3 × AAA in Hallway Smoke Alarm',
      'Replace CR2450 in Living Room Motion',
      'Replace the battery in TV Remote Battery',
      'Replace 2 × AAA in Bedroom Temp & Humidity',
    ]);
    // Totals: 5 AAA across 2 devices, 1 CR2450, 1 unknown last.
    expect(list.shopping).toEqual([
      { batteryType: 'AAA', count: 5, devices: 2 },
      { batteryType: 'CR2450', count: 1, devices: 1 },
      { batteryType: UNKNOWN_BATTERY_TYPE, count: 1, devices: 1 },
    ]);
  });

  it('puts rechargeable devices in the charge list and keeps them out of the shopping totals', () => {
    const config = {
      ...DEFAULT_CONFIG,
      device_settings: [
        { device_id: DEV.zhaTemp, rechargeable: true, battery_type: 'Built-in rechargeable' },
      ],
    };
    const list = actionList(devices, config);
    expect(list.charge.map((a) => a.label)).toEqual(['Charge Bedroom Temp & Humidity']);
    expect(list.replace.map((a) => a.device.deviceId)).not.toContain(DEV.zhaTemp);
    expect(list.shopping.reduce((n, l) => n + l.count, 0)).toBe(3);
  });

  it('treats a missing or false rechargeable flag as "replace"', () => {
    const config = {
      ...DEFAULT_CONFIG,
      device_settings: [
        { device_id: DEV.zhaTemp, rechargeable: false },
        { device_id: DEV.z2mMotion }, // key absent, as the editor writes after unticking
      ],
    };
    const list = actionList(devices, config);
    expect(list.charge).toEqual([]);
    expect(list.replace.map((a) => a.device.deviceId)).toEqual(
      expect.arrayContaining([DEV.zhaTemp, DEV.z2mMotion]),
    );
  });

  it('skips charging and snoozed devices', () => {
    const snoozed = analyseDevices(hass, DEFAULT_CONFIG, {
      now: FIXED_NOW,
      snoozes: new Map([[DEV.z2mMotion, new Date('2027-01-01')]]),
    });
    const list = actionList(snoozed, DEFAULT_CONFIG);
    expect(list.replace.map((a) => a.device.deviceId)).not.toContain(DEV.z2mMotion);
    expect(list.replace.map((a) => a.device.deviceId)).not.toContain(DEV.vacuum); // 18%, docked
  });

  it('is empty when every battery is healthy', () => {
    const healthy = devices.filter((d) => (d.battery?.level ?? 0) > 50);
    expect(actionList(healthy, DEFAULT_CONFIG)).toEqual({ replace: [], charge: [], shopping: [] });
  });
});
