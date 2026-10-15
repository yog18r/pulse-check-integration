import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../../src/card/config';
import { analyseDevices } from '../../src/core/analyse';
import { collectDeviceGroups } from '../../src/core/group';
import { applyEnhancers, ENHANCERS, type Enhancer } from '../../src/enhancers';
import { zhaEnhancer } from '../../src/enhancers/zha';
import { zigbee2mqttEnhancer } from '../../src/enhancers/zigbee2mqtt';
import { zwaveJsEnhancer } from '../../src/enhancers/zwaveJs';
import { DEV, FIXED_NOW, hass, minutesAgo } from '../fixtures/hass';

const groups = new Map(collectDeviceGroups(hass).map((g) => [g.deviceId, g]));
const group = (id: string) => groups.get(id)!;

describe('zwaveJsEnhancer', () => {
  it('reports an asleep node as informational', () => {
    const r = zwaveJsEnhancer.enhance(group(DEV.zwaveMulti), hass);
    expect(r.extras).toEqual([{ label: 'Node', value: 'asleep', severity: 'ok' }]);
    expect(r.offline).toBeUndefined();
  });

  it('reports a dead node as critical and offline', () => {
    const r = zwaveJsEnhancer.enhance(group(DEV.zwaveLock), hass);
    expect(r.extras).toEqual([{ label: 'Node', value: 'dead', severity: 'critical' }]);
    expect(r.offline).toBe(true);
  });

  it('adds nothing for a device without a node status sensor', () => {
    expect(zwaveJsEnhancer.enhance(group(DEV.esphomePlant), hass).extras).toEqual([]);
  });
});

describe('zigbee2mqttEnhancer', () => {
  it('reads linkquality and the optional last_seen sensor', () => {
    const r = zigbee2mqttEnhancer.enhance(group(DEV.z2mDoor), hass);
    expect(r.extras).toEqual([{ label: 'LQI', value: '120', severity: 'ok' }]);
    expect(r.lastHeard?.toISOString()).toBe(minutesAgo(FIXED_NOW, 12));
  });

  it('warns on a weak link', () => {
    const r = zigbee2mqttEnhancer.enhance(group(DEV.z2mMotion), hass);
    expect(r.extras[0]?.severity).toBe('ok'); // 45 is above the 30 cut-off
    const weak = {
      ...group(DEV.z2mMotion),
      states: group(DEV.z2mMotion).states.map((s) =>
        s.entity_id.endsWith('_linkquality') ? { ...s, state: '12' } : s,
      ),
    };
    expect(zigbee2mqttEnhancer.enhance(weak, hass).extras[0]).toEqual({
      label: 'LQI',
      value: '12',
      severity: 'warning',
    });
  });

  it('adds nothing for a plain MQTT device', () => {
    const plain = { ...group(DEV.mqttLight), states: [group(DEV.mqttLight).states[0]!] };
    const r = zigbee2mqttEnhancer.enhance(plain, hass);
    expect(r.extras).toEqual([]);
    expect(r.lastHeard).toBeUndefined();
  });
});

describe('zhaEnhancer', () => {
  it('reads lqi and rssi when present', () => {
    const r = zhaEnhancer.enhance(group(DEV.zhaTemp), hass);
    expect(r.extras).toEqual([
      { label: 'LQI', value: '88', severity: 'ok' },
      { label: 'RSSI', value: '-71 dBm' },
    ]);
  });

  it('adds nothing when the diagnostic sensors are disabled', () => {
    expect(zhaEnhancer.enhance(group(DEV.smokeAlarm), hass).extras).toEqual([]);
  });
});

describe('applyEnhancers', () => {
  it('only runs enhancers for the matching platform and merges results', () => {
    const r = applyEnhancers(ENHANCERS, 'zwave_js', group(DEV.zwaveLock), hass);
    expect(r.offline).toBe(true);
    expect(r.extras).toHaveLength(1);
    expect(applyEnhancers(ENHANCERS, 'shelly', group(DEV.shellyHt), hass).extras).toEqual([]);
  });

  it('keeps the newest lastHeard across enhancers', () => {
    const older: Enhancer = {
      id: 'older',
      platform: 'mqtt',
      enhance: () => ({ extras: [], lastHeard: new Date('2020-01-01T00:00:00Z') }),
    };
    const r = applyEnhancers([older, zigbee2mqttEnhancer], 'mqtt', group(DEV.z2mDoor), hass);
    expect(r.lastHeard?.toISOString()).toBe(minutesAgo(FIXED_NOW, 12));
  });
});

describe('enhancers inside the full analysis', () => {
  const devices = analyseDevices(hass, DEFAULT_CONFIG, { now: FIXED_NOW, enhancers: ENHANCERS });
  const byId = new Map(devices.map((d) => [d.deviceId, d]));

  it('attaches badges and keeps the lock offline via the dead node', () => {
    expect(byId.get(DEV.zwaveLock)?.isOffline).toBe(true);
    expect(byId.get(DEV.zwaveLock)?.extras[0]?.value).toBe('dead');
    expect(byId.get(DEV.zwaveMulti)?.extras[0]?.value).toBe('asleep');
    expect(byId.get(DEV.zhaTemp)?.extras.map((e) => e.label)).toEqual(['LQI', 'RSSI']);
  });

  it('prefers the Zigbee2MQTT last_seen over last_updated when it is newer', () => {
    // The door sensor's newest last_updated is 12m (contact), last_seen is also 12m,
    // so build a variant where last_seen is fresher than any entity update.
    const fresher = {
      ...hass,
      states: {
        ...hass.states,
        'sensor.front_door_last_seen': {
          ...hass.states['sensor.front_door_last_seen']!,
          state: minutesAgo(FIXED_NOW, 1),
        },
      },
    };
    const result = analyseDevices(fresher, DEFAULT_CONFIG, {
      now: FIXED_NOW,
      enhancers: ENHANCERS,
    });
    const door = result.find((d) => d.deviceId === DEV.z2mDoor);
    expect(door?.lastHeard?.toISOString()).toBe(minutesAgo(FIXED_NOW, 1));
  });
});
