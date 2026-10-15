import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../../src/card/config';
import { analyseDevices } from '../../src/core/analyse';
import { ORPHAN_PREFIX } from '../../src/core/group';
import { batteryList, connectivityList, sortableBatteryLevel } from '../../src/core/sort';
import type { DeviceHealth } from '../../src/core/types';
import { DEV, FIXED_NOW, hass } from '../fixtures/hass';

const devices = analyseDevices(hass, DEFAULT_CONFIG, { now: FIXED_NOW });

describe('batteryList', () => {
  it('includes only devices with a battery reading, lowest first', () => {
    const ids = batteryList(devices, DEFAULT_CONFIG).map((d) => d.deviceId);
    expect(ids).toEqual([
      DEV.smokeAlarm, // binary low: critical, sorts above every number
      ORPHAN_PREFIX + 'sensor.remote_battery_template', // 9%
      DEV.z2mMotion, // 12%
      DEV.zhaTemp, // 28%
      DEV.matterContact, // 40%
      DEV.legacyTracker, // 44%
      DEV.zwaveMulti, // 55%
      DEV.phone, // 71%
      DEV.z2mDoor, // 87%
      DEV.shellyHt, // 92%
    ]);
    // The offline lock has an unavailable battery sensor, so no reading.
    expect(ids).not.toContain(DEV.zwaveLock);
    expect(ids).not.toContain(DEV.esphomePlant);
  });
});

describe('connectivityList', () => {
  it('lists only offline or quiet devices, offline first then oldest contact', () => {
    const ids = connectivityList(devices).map((d) => d.deviceId);
    expect(ids).toEqual([
      DEV.zwaveLock, // offline
      DEV.zwaveMulti, // quiet 40h
      DEV.zhaTemp, // quiet 30h
    ]);
    // Mains devices (Shelly plug 72h, MQTT light 50h) are not quiet by default.
    expect(ids).not.toContain(DEV.shellyPlug);
    expect(ids).not.toContain(DEV.mqttLight);
  });
});

describe('sortableBatteryLevel', () => {
  const base: DeviceHealth = {
    deviceId: 'x',
    name: 'x',
    integration: 'zha',
    isOffline: false,
    isQuiet: false,
    quietThresholdHours: 24,
    severity: 'ok',
    extras: [],
    entityIds: [],
  };

  it('orders binary low < any number < binary ok < no battery', () => {
    const low = sortableBatteryLevel({
      ...base,
      battery: { isLow: true, source: 'binary', entityId: 'b' },
    });
    const zero = sortableBatteryLevel({
      ...base,
      battery: { level: 0, isLow: false, source: 'sensor', entityId: 's' },
    });
    const full = sortableBatteryLevel({
      ...base,
      battery: { level: 100, isLow: false, source: 'sensor', entityId: 's' },
    });
    const ok = sortableBatteryLevel({
      ...base,
      battery: { isLow: false, source: 'binary', entityId: 'b' },
    });
    const none = sortableBatteryLevel(base);
    expect(low).toBeLessThan(zero);
    expect(zero).toBeLessThan(full);
    expect(full).toBeLessThan(ok);
    expect(ok).toBeLessThan(none);
  });
});
