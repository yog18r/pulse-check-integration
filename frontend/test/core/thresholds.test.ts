import { describe, expect, it } from 'vitest';
import { parseSnapshot } from '../../src/card/snapshot';
import { batteryList } from '../../src/core/sort';
import { summarise } from '../../src/core/summarise';
import { batterySeverity, deviceBatterySeverity, thresholdsFor } from '../../src/core/thresholds';
import type { DeviceHealth } from '../../src/core/types';

const RULES = { battery_warning: 30, battery_critical: 15 };

function device(id: string, level: number, own?: { warning: number; critical: number }) {
  return {
    deviceId: id,
    name: id,
    integration: 'mobile_app',
    isOffline: false,
    isQuiet: false,
    quietThresholdHours: 24,
    severity: 'ok',
    deviceType: 'phone',
    extras: [],
    entityIds: [],
    battery: { level, isLow: false, source: 'sensor', entityId: `sensor.${id}` },
    ...(own ? { batteryWarning: own.warning, batteryCritical: own.critical } : {}),
  };
}

function parsed(...raw: unknown[]): DeviceHealth[] {
  return parseSnapshot({ devices: raw }).devices;
}

describe('per-device battery levels', () => {
  it('are read from the snapshot and used instead of the integration levels', () => {
    const [phone, tablet] = parsed(
      device('phone', 20, { warning: 10, critical: 5 }),
      device('tablet', 20),
    );
    expect(thresholdsFor(phone!, RULES)).toEqual({ battery_warning: 10, battery_critical: 5 });
    expect(deviceBatterySeverity(phone!, RULES)).toBe('ok');
    expect(deviceBatterySeverity(tablet!, RULES)).toBe('warning');
  });

  it('count and sort the way the integration judged them', () => {
    const devices = parsed(device('phone', 8, { warning: 10, critical: 5 }), device('tablet', 12));
    const summary = summarise(devices, RULES);
    expect(summary.lowBatteries).toBe(2);
    expect(summary.criticalBatteries).toBe(1);
    // The tablet is critical at 12 %; the phone only a warning at 8 %.
    expect(batteryList(devices, RULES).map((d) => d.deviceId)).toEqual(['tablet', 'phone']);
  });
});

describe('battery levels are "at or below"', () => {
  it.each([
    [15, 'critical'],
    [16, 'warning'],
    [30, 'warning'],
    [31, 'ok'],
  ] as const)('%i percent is %s at warning 30 / critical 15', (level, expected) => {
    const battery = { level, isLow: false, source: 'sensor', entityId: 'sensor.x' } as const;
    expect(batterySeverity(battery, RULES)).toBe(expected);
    expect(deviceBatterySeverity(parsed(device('tablet', level))[0]!, RULES)).toBe(expected);
  });

  it.each([
    [5, 'critical'],
    [6, 'warning'],
    [10, 'warning'],
    [11, 'ok'],
  ] as const)(
    '%i percent is %s for a device that warns at 10 and is critical at 5',
    (level, expected) => {
      const [phone] = parsed(device('phone', level, { warning: 10, critical: 5 }));
      expect(deviceBatterySeverity(phone!, RULES)).toBe(expected);
    },
  );
});
