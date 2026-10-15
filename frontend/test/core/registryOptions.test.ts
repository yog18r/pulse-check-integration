import { describe, expect, it } from 'vitest';
import {
  deviceLabel,
  listDevices,
  listIntegrations,
  listOrphanBatteryEntities,
} from '../../src/core/registryOptions';
import { DEV, hass } from '../fixtures/hass';

describe('listIntegrations', () => {
  it('lists every platform with its entity count, biggest first', () => {
    const options = listIntegrations(hass);
    const ids = options.map((o) => o.id);
    expect(ids[0]).toBe('mqtt'); // door + motion + light: the most entities
    expect(ids).toContain('zwave_js');
    expect(ids).toContain('template');
    expect(options.find((o) => o.id === 'zwave_js')?.entityCount).toBe(7);
  });

  it('breaks ties alphabetically', () => {
    const ids = listIntegrations(hass).map((o) => o.id);
    const shelly = ids.indexOf('shelly');
    const zha = ids.indexOf('zha');
    // Both have the same count only if the fixture says so; what we assert
    // is that the output is deterministic and sorted, not the exact tie.
    expect(shelly).toBeGreaterThanOrEqual(0);
    expect(zha).toBeGreaterThanOrEqual(0);
    expect(ids).toEqual(
      [...ids].sort((a, b) => {
        const ca = listIntegrations(hass).find((o) => o.id === a)!.entityCount;
        const cb = listIntegrations(hass).find((o) => o.id === b)!.entityCount;
        return cb - ca || a.localeCompare(b);
      }),
    );
  });
});

describe('listDevices', () => {
  const devices = listDevices(hass);

  it('skips service and disabled devices and sorts by name', () => {
    const ids = devices.map((d) => d.id);
    expect(ids).not.toContain(DEV.sun);
    expect(ids).not.toContain(DEV.disabledSensor);
    const names = devices.map((d) => d.name);
    expect(names).toEqual(
      [...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' })),
    );
  });

  it('uses the user rename and attaches area and integration', () => {
    const zha = devices.find((d) => d.id === DEV.zhaTemp);
    expect(zha).toEqual({
      id: DEV.zhaTemp,
      name: 'Bedroom Temp & Humidity',
      area: 'Bedroom',
      integration: 'zha',
    });
    const phone = devices.find((d) => d.id === DEV.phone);
    expect(phone?.area).toBeUndefined();
    expect(phone?.integration).toBe('mobile_app');
  });
});

describe('listOrphanBatteryEntities', () => {
  it('lists device-less battery sensors under their entity: id, skipping config ones', () => {
    const options = listOrphanBatteryEntities(hass);
    expect(options).toEqual([
      // Only a state, no registry entry: so no integration either.
      { id: 'entity:sensor.garden_soil_moisture', name: 'Garden Soil Sensor' },
      {
        id: 'entity:sensor.remote_battery_template',
        name: 'TV Remote Battery',
        integration: 'template',
      },
    ]);
    // sensor.inverter_min_soc is a config entity and sensor.random_template has no battery.
  });
});

describe('deviceLabel', () => {
  it('appends whatever context exists', () => {
    expect(deviceLabel({ id: 'a', name: 'Lock', area: 'Hall', integration: 'zwave_js' })).toBe(
      'Lock (Hall · zwave_js)',
    );
    expect(deviceLabel({ id: 'a', name: 'Lock', integration: 'zwave_js' })).toBe('Lock (zwave_js)');
    expect(deviceLabel({ id: 'a', name: 'Lock' })).toBe('Lock');
  });
});
