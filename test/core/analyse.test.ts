import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG, type ResolvedConfig } from '../../src/card/config';
import { analyseDevices } from '../../src/core/analyse';
import { ORPHAN_PREFIX } from '../../src/core/group';
import type { Enhancer } from '../../src/enhancers';
import { DEV, FIXED_NOW, hass } from '../fixtures/hass';

const now = FIXED_NOW;

function run(overrides: Partial<ResolvedConfig> = {}, enhancers?: Enhancer[]) {
  const config = { ...DEFAULT_CONFIG, ...overrides };
  const list = analyseDevices(hass, config, enhancers ? { now, enhancers } : { now });
  return { list, byId: new Map(list.map((d) => [d.deviceId, d])) };
}

describe('analyseDevices', () => {
  it('returns one entry per real device plus battery-bearing orphans', () => {
    const { byId } = run();
    expect(byId.has(DEV.z2mDoor)).toBe(true);
    expect(byId.has(DEV.esphomePlant)).toBe(true); // mains powered but still a device
    expect(byId.has(ORPHAN_PREFIX + 'sensor.remote_battery_template')).toBe(true);
    expect(byId.has(ORPHAN_PREFIX + 'sensor.random_template')).toBe(false);
    expect(byId.has(DEV.sun)).toBe(false);
    expect(byId.has(DEV.disabledSensor)).toBe(false);
  });

  it('fills in name, area, integration and metadata', () => {
    const { byId } = run();
    const zha = byId.get(DEV.zhaTemp)!;
    expect(zha.name).toBe('Bedroom Temp & Humidity');
    expect(zha.area).toBe('Bedroom');
    expect(zha.integration).toBe('zha');
    expect(zha.manufacturer).toBe('SONOFF');
    expect(zha.model).toBe('SNZB-02');
    expect(zha.entityIds).toHaveLength(5);
  });

  it('classifies the fixture devices as designed', () => {
    const { byId } = run();
    expect(byId.get(DEV.z2mDoor)?.severity).toBe('ok');
    expect(byId.get(DEV.z2mMotion)?.severity).toBe('critical'); // 12%
    expect(byId.get(DEV.zhaTemp)?.severity).toBe('warning'); // 28% and quiet
    expect(byId.get(DEV.zhaTemp)?.isQuiet).toBe(true);
    expect(byId.get(DEV.zwaveMulti)?.isQuiet).toBe(true); // 40h > 24h default
    expect(byId.get(DEV.zwaveLock)?.isOffline).toBe(true);
    expect(byId.get(DEV.zwaveLock)?.severity).toBe('critical');
    expect(byId.get(DEV.zwaveLock)?.isQuiet).toBe(false); // offline, not double-counted
    expect(byId.get(DEV.shellyPlug)?.isQuiet).toBe(true); // 72h, mains powered
    expect(byId.get(DEV.shellyPlug)?.battery).toBeUndefined();
    expect(byId.get(DEV.smokeAlarm)?.battery?.isLow).toBe(true);
    expect(byId.get(DEV.smokeAlarm)?.severity).toBe('critical');
    expect(byId.get(DEV.legacyTracker)?.battery).toMatchObject({ level: 44, source: 'attribute' });
    expect(byId.get(DEV.esphomePlant)?.severity).toBe('ok');
  });

  it('honours per-integration quiet thresholds', () => {
    const { byId } = run({ integration_thresholds: { zwave_js: 48 } });
    expect(byId.get(DEV.zwaveMulti)?.isQuiet).toBe(false); // 40h < 48h
    expect(byId.get(DEV.zhaTemp)?.isQuiet).toBe(true); // unaffected
  });

  it('honours per-device quiet thresholds', () => {
    const { byId } = run({
      device_overrides: [{ device_id: DEV.shellyPlug, quiet_threshold_hours: 100 }],
    });
    expect(byId.get(DEV.shellyPlug)?.isQuiet).toBe(false);
  });

  it('excludes integrations and devices', () => {
    const { byId } = run({
      exclude_integrations: ['mobile_app'],
      exclude_devices: [DEV.z2mDoor, 'sensor.remote_battery_template'],
    });
    expect(byId.has(DEV.phone)).toBe(false);
    expect(byId.has(DEV.z2mDoor)).toBe(false);
    expect(byId.has(ORPHAN_PREFIX + 'sensor.remote_battery_template')).toBe(false);
  });

  it('runs matching enhancers and lets them escalate severity', () => {
    const shout: Enhancer = {
      id: 'test-shout',
      platform: 'esphome',
      enhance: () => [{ label: 'Test', value: 'boom', severity: 'critical' }],
    };
    const { byId } = run({}, [shout]);
    expect(byId.get(DEV.esphomePlant)?.extras).toEqual([
      { label: 'Test', value: 'boom', severity: 'critical' },
    ]);
    expect(byId.get(DEV.esphomePlant)?.severity).toBe('critical');
    expect(byId.get(DEV.z2mDoor)?.extras).toEqual([]); // different platform
  });

  it('survives a throwing enhancer', () => {
    const broken: Enhancer = {
      id: 'test-broken',
      platform: 'zha',
      enhance: () => {
        throw new Error('bug');
      },
    };
    const { byId } = run({}, [broken]);
    expect(byId.get(DEV.zhaTemp)?.extras).toEqual([]);
    expect(byId.get(DEV.zhaTemp)?.severity).toBe('warning');
  });
});
