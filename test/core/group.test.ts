import { describe, expect, it } from 'vitest';
import {
  areaName,
  collectDeviceGroups,
  displayName,
  dominantIntegration,
  isIgnorableDevice,
  ORPHAN_PREFIX,
} from '../../src/core/group';
import { DEV, hass, makeDevice, makeEntity } from '../fixtures/hass';

const groups = collectDeviceGroups(hass);
const byId = new Map(groups.map((g) => [g.deviceId, g]));

describe('collectDeviceGroups', () => {
  it('produces one group per physical device', () => {
    const ids = groups.map((g) => g.deviceId);
    expect(ids).toContain(DEV.z2mDoor);
    expect(ids).toContain(DEV.zwaveLock);
    expect(ids).toContain(DEV.phone);
    // Each id appears exactly once.
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('puts all of a device’s entities and states in its group', () => {
    const door = byId.get(DEV.z2mDoor)!;
    expect(door.entities.map((e) => e.entity_id).sort()).toEqual([
      'binary_sensor.front_door_contact',
      'sensor.front_door_battery',
      'sensor.front_door_last_seen',
      'sensor.front_door_linkquality',
    ]);
    expect(door.states).toHaveLength(4);
    expect(door.device?.manufacturer).toBe('Aqara');
  });

  it('skips service devices and disabled devices', () => {
    expect(byId.has(DEV.sun)).toBe(false);
    expect(byId.has(DEV.disabledSensor)).toBe(false);
  });

  it('gives entities without a device a synthetic group each', () => {
    const orphan = byId.get(ORPHAN_PREFIX + 'sensor.remote_battery_template');
    expect(orphan).toBeDefined();
    expect(orphan?.device).toBeNull();
    expect(orphan?.entities).toHaveLength(1);
  });

  it('treats an entity pointing at an unknown device id as an orphan', () => {
    const partial = {
      ...hass,
      entities: { 'sensor.lost': makeEntity('sensor.lost', 'zha', 'does_not_exist') },
      states: {},
    };
    const result = collectDeviceGroups(partial);
    expect(result).toHaveLength(1);
    expect(result[0]?.deviceId).toBe(ORPHAN_PREFIX + 'sensor.lost');
  });
});

describe('isIgnorableDevice', () => {
  it('flags service and disabled devices only', () => {
    expect(isIgnorableDevice(makeDevice('a', 'Sun', { entry_type: 'service' }))).toBe(true);
    expect(isIgnorableDevice(makeDevice('b', 'Old', { disabled_by: 'user' }))).toBe(true);
    expect(isIgnorableDevice(makeDevice('c', 'Fine'))).toBe(false);
  });
});

describe('dominantIntegration', () => {
  it('returns the most common platform', () => {
    expect(
      dominantIntegration([
        makeEntity('sensor.a', 'zha', 'd'),
        makeEntity('sensor.b', 'zha', 'd'),
        makeEntity('sensor.c', 'template', 'd'),
      ]),
    ).toBe('zha');
  });

  it('returns "unknown" when nothing has a platform', () => {
    expect(dominantIntegration([{ entity_id: 'sensor.a' }])).toBe('unknown');
    expect(dominantIntegration([])).toBe('unknown');
  });
});

describe('displayName and areaName', () => {
  it('prefers the user rename over the device name', () => {
    expect(displayName(byId.get(DEV.zhaTemp)!)).toBe('Bedroom Temp & Humidity');
    expect(displayName(byId.get(DEV.z2mDoor)!)).toBe('Front Door Sensor');
  });

  it('uses friendly_name for orphan entities', () => {
    expect(displayName(byId.get(ORPHAN_PREFIX + 'sensor.remote_battery_template')!)).toBe(
      'TV Remote Battery',
    );
  });

  it('resolves the area name from the device area', () => {
    expect(areaName(byId.get(DEV.zhaTemp)!, hass)).toBe('Bedroom');
    expect(areaName(byId.get(DEV.phone)!, hass)).toBeUndefined();
  });
});
