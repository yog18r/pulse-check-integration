import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG, type ResolvedConfig } from '../../src/card/config';
import { analyseDevices, lastReportedCandidates } from '../../src/core/analyse';
import { ORPHAN_PREFIX } from '../../src/core/group';
import type { Enhancer } from '../../src/enhancers';
import { DEV, FIXED_NOW, hass, hoursAgo } from '../fixtures/hass';

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
    expect(zha.entityIds).toHaveLength(6);
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
    // Mains devices are not "quiet" by default, however long they sit still.
    expect(byId.get(DEV.shellyPlug)?.isQuiet).toBe(false); // 72h, mains powered
    expect(byId.get(DEV.shellyPlug)?.battery).toBeUndefined();
    expect(byId.get(DEV.mqttLight)?.isQuiet).toBe(false); // 50h, mains powered
    expect(byId.get(DEV.mqttLight)?.severity).toBe('ok');
    expect(byId.get(DEV.smokeAlarm)?.battery?.isLow).toBe(true);
    expect(byId.get(DEV.smokeAlarm)?.severity).toBe('critical');
    expect(byId.get(DEV.legacyTracker)?.battery).toMatchObject({ level: 44, source: 'attribute' });
    expect(byId.get(DEV.esphomePlant)?.severity).toBe('ok');
  });

  it('ignores recently pressed config buttons when judging quiet', () => {
    // The ZHA sensor's identify button was "pressed" 1h ago; the sensor
    // itself last reported 30h ago, so it is still quiet.
    const { byId } = run();
    expect(byId.get(DEV.zhaTemp)?.isQuiet).toBe(true);
  });

  it('quiet_scope: all flags mains devices too', () => {
    const { byId } = run({ quiet_scope: 'all' });
    expect(byId.get(DEV.shellyPlug)?.isQuiet).toBe(true);
    expect(byId.get(DEV.mqttLight)?.isQuiet).toBe(true);
    expect(byId.get(DEV.mqttLight)?.severity).toBe('warning');
    expect(byId.get(DEV.esphomePlant)?.isQuiet).toBe(false); // reported 2 minutes ago
  });

  it('never treats a config sensor as a battery, even if labelled one', () => {
    const { byId } = run();
    expect(byId.has(ORPHAN_PREFIX + 'sensor.inverter_min_soc')).toBe(false);
  });

  it('device-less entities can only be batteries, never offline or quiet', () => {
    const { byId } = run({ quiet_scope: 'all', quiet_threshold_hours: 1 });
    const orphan = byId.get(ORPHAN_PREFIX + 'sensor.remote_battery_template')!;
    expect(orphan.battery?.level).toBe(9);
    expect(orphan.isQuiet).toBe(false); // 4h old, threshold 1h, still not quiet
    expect(orphan.isOffline).toBe(false);
  });

  it('exclude_entities removes single entities, and whole orphans', () => {
    const { byId } = run({
      exclude_entities: ['sensor.living_room_motion_battery', 'sensor.remote_battery_template'],
    });
    // The motion sensor device stays, but without its battery reading.
    expect(byId.has(DEV.z2mMotion)).toBe(true);
    expect(byId.get(DEV.z2mMotion)?.battery).toBeUndefined();
    expect(byId.get(DEV.z2mMotion)?.severity).toBe('ok');
    // The orphan had only that one entity, so it is gone entirely.
    expect(byId.has(ORPHAN_PREFIX + 'sensor.remote_battery_template')).toBe(false);
  });

  it('does not flag a charging device however low it is', () => {
    const { byId } = run();
    const vacuum = byId.get(DEV.vacuum)!;
    expect(vacuum.battery).toMatchObject({ level: 18, isCharging: true });
    expect(vacuum.severity).toBe('ok');
  });

  it('uses on-demand last_reported when it is newer than last_updated', () => {
    // The ZHA sensor last changed value 30h ago, but HA's server says the
    // temperature entity reported (unchanged) 2h ago: not quiet after all.
    const lastReported = new Map([
      ['sensor.bedroom_climate_temperature', new Date(hoursAgo(FIXED_NOW, 2))],
      // A static entity's report must not count.
      ['button.bedroom_climate_identify', new Date(FIXED_NOW)],
    ]);
    const list = analyseDevices(hass, DEFAULT_CONFIG, { now, lastReported });
    const zha = list.find((d) => d.deviceId === DEV.zhaTemp)!;
    expect(zha.isQuiet).toBe(false);
    expect(zha.lastHeard?.toISOString()).toBe(hoursAgo(FIXED_NOW, 2));
    expect(zha.severity).toBe('warning'); // still 28%
  });

  it('ignores last_reported that is older than what the frontend knows', () => {
    const lastReported = new Map([
      ['sensor.bedroom_climate_temperature', new Date(hoursAgo(FIXED_NOW, 90))],
    ]);
    const list = analyseDevices(hass, DEFAULT_CONFIG, { now, lastReported });
    expect(list.find((d) => d.deviceId === DEV.zhaTemp)?.isQuiet).toBe(true);
  });

  it('snoozes keep the facts but mute the severity until they expire', () => {
    const future = new Date('2027-01-01T00:00:00Z');
    const past = new Date('2020-01-01T00:00:00Z');
    const list = analyseDevices(hass, DEFAULT_CONFIG, {
      now,
      snoozes: new Map([
        [DEV.zwaveLock, future],
        [DEV.z2mMotion, past],
      ]),
    });
    const lock = list.find((d) => d.deviceId === DEV.zwaveLock)!;
    expect(lock.isOffline).toBe(true);
    expect(lock.severity).toBe('ok');
    expect(lock.snoozedUntil).toEqual(future);
    const motion = list.find((d) => d.deviceId === DEV.z2mMotion)!;
    expect(motion.severity).toBe('critical'); // expired snooze
    expect(motion.snoozedUntil).toBeUndefined();
  });

  it('lists only live entities of quiet devices as last_reported candidates', () => {
    const { list } = run();
    const ids = lastReportedCandidates(list, hass);
    expect(ids).toContain('sensor.bedroom_climate_temperature');
    expect(ids).toContain('sensor.garage_multisensor_battery_level');
    expect(ids).not.toContain('button.bedroom_climate_identify'); // static
    expect(ids).not.toContain('sensor.front_door_battery'); // not quiet
    expect(ids).not.toContain('lock.front_door_lock'); // offline, not quiet
  });

  it('include_integrations is an allow-list', () => {
    const { byId, list } = run({ include_integrations: ['zha', 'MQTT'] }); // case-insensitive
    expect(byId.has(DEV.zhaTemp)).toBe(true);
    expect(byId.has(DEV.z2mDoor)).toBe(true);
    expect(byId.has(DEV.zwaveLock)).toBe(false);
    expect(byId.has(DEV.phone)).toBe(false);
    expect(list.every((d) => ['zha', 'mqtt'].includes(d.integration))).toBe(true);
  });

  it('area filters match ids or names, and devices without an area are dropped by an include list', () => {
    const inc = run({ include_areas: ['bedroom', 'Garage'] });
    expect(inc.byId.has(DEV.zhaTemp)).toBe(true); // Bedroom
    expect(inc.byId.has(DEV.matterContact)).toBe(true); // Bedroom
    expect(inc.byId.has(DEV.zwaveMulti)).toBe(true); // Garage
    expect(inc.byId.has(DEV.z2mDoor)).toBe(false); // Hallway
    expect(inc.byId.has(DEV.phone)).toBe(false); // no area
    expect(inc.byId.has(ORPHAN_PREFIX + 'sensor.remote_battery_template')).toBe(false);

    const exc = run({ exclude_areas: ['Hallway'] });
    expect(exc.byId.has(DEV.z2mDoor)).toBe(false);
    expect(exc.byId.has(DEV.zwaveLock)).toBe(false);
    expect(exc.byId.has(DEV.phone)).toBe(true); // no area: unaffected by exclude
  });

  it('honours per-integration quiet thresholds', () => {
    const { byId } = run({ integration_thresholds: { zwave_js: 48 } });
    expect(byId.get(DEV.zwaveMulti)?.isQuiet).toBe(false); // 40h < 48h
    expect(byId.get(DEV.zhaTemp)?.isQuiet).toBe(true); // unaffected
  });

  it('honours per-device quiet thresholds', () => {
    const { byId } = run({
      device_settings: [{ device_id: DEV.shellyPlug, quiet_threshold_hours: 100 }],
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
      enhance: () => ({ extras: [{ label: 'Test', value: 'boom', severity: 'critical' }] }),
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
