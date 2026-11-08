import { describe, expect, it } from 'vitest';
import {
  deviceLabel,
  listDevices,
  listIntegrations,
  listOrphanEntities,
} from '../../src/core/registryOptions';
import type { HassLike } from '../../src/core/types';
import { DEV, FIXED_NOW, hass, makeDevice, makeEntity, makeState } from '../fixtures/hass';

/**
 * The fixture plus what a real install also has: Pulse Check's own service
 * device, the sensor it attaches to a watched device, and a few device-less
 * entities that are not batteries.
 */
function withPulseCheck(): HassLike {
  const extraEntities = [
    makeEntity('sensor.pulse_check_attention', 'pulse_check', 'dev_pulse_check'),
    makeEntity('binary_sensor.pulse_check_problem', 'pulse_check', 'dev_pulse_check'),
    makeEntity('sensor.front_door_lock_pulse', 'pulse_check', DEV.zwaveLock),
    // A device-less Pulse Check entity: never offered either.
    makeEntity('sensor.pulse_check_low_batteries', 'pulse_check', undefined),
    makeEntity('automation.night_lights', 'automation', undefined),
  ];
  const extraStates = [
    makeState('sensor.pulse_check_attention', '3', FIXED_NOW),
    makeState('sensor.pulse_check_low_batteries', '2', FIXED_NOW),
    makeState('automation.night_lights', 'unavailable', FIXED_NOW, {
      attributes: { friendly_name: 'Night lights' },
    }),
  ];
  return {
    ...hass,
    devices: {
      ...hass.devices,
      dev_pulse_check: makeDevice('dev_pulse_check', 'Pulse Check', { entry_type: 'service' }),
    },
    entities: {
      ...hass.entities,
      ...Object.fromEntries(extraEntities.map((e) => [e.entity_id, e])),
    },
    states: {
      ...hass.states,
      ...Object.fromEntries(extraStates.map((st) => [st.entity_id, st])),
    },
  };
}

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

  it('offers service devices, skips disabled ones and sorts by name', () => {
    const ids = devices.map((d) => d.id);
    // The integration watches services (Sun, AdGuard Home) for being unavailable.
    expect(devices.find((d) => d.id === DEV.sun)).toEqual({
      id: DEV.sun,
      name: 'Sun',
      integration: 'sun',
    });
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

  it("leaves out Pulse Check's own device but not the devices it watches", () => {
    const options = listDevices(withPulseCheck());
    const ids = options.map((d) => d.id);
    expect(ids).not.toContain('dev_pulse_check');
    // The lock carries a Pulse Check sensor too; it is still the lock's integration.
    const lock = options.find((d) => d.id === DEV.zwaveLock);
    expect(lock?.integration).toBe('zwave_js');
    expect(ids).toContain(DEV.sun);
  });

  it("names a device by its own integration, even when Pulse Check's sensors outnumber it", () => {
    const base = withPulseCheck();
    const extra = [
      makeEntity('sensor.coin_battery', 'zha', 'dev_coin'),
      makeEntity('sensor.coin_battery_days_left', 'pulse_check', 'dev_coin'),
      makeEntity('sensor.coin_battery_last_replaced', 'pulse_check', 'dev_coin'),
    ];
    const options = listDevices({
      ...base,
      devices: { ...base.devices, dev_coin: makeDevice('dev_coin', 'Coin sensor') },
      entities: { ...base.entities, ...Object.fromEntries(extra.map((e) => [e.entity_id, e])) },
    });
    expect(options.find((d) => d.id === 'dev_coin')?.integration).toBe('zha');
  });
});

describe('listOrphanEntities', () => {
  it('lists every device-less entity under its entity: id, skipping config ones', () => {
    const options = listOrphanEntities(hass);
    expect(options).toEqual([
      // Only a state, no registry entry: so no integration either.
      { id: 'entity:sensor.garden_soil_moisture', name: 'Garden Soil Sensor' },
      // Not a battery, but watched for being unavailable since 0.2.8.
      {
        id: 'entity:sensor.random_template',
        name: 'sensor.random_template',
        integration: 'template',
      },
      {
        id: 'entity:sensor.remote_battery_template',
        name: 'TV Remote Battery',
        integration: 'template',
      },
    ]);
    // sensor.inverter_min_soc is a config entity: a setting, never watched.
  });

  it("offers automations and the like, but not Pulse Check's own entities", () => {
    const ids = listOrphanEntities(withPulseCheck()).map((o) => o.id);
    expect(ids).toContain('entity:automation.night_lights');
    expect(ids).not.toContain('entity:sensor.pulse_check_low_batteries');
    expect(ids).not.toContain('entity:sensor.pulse_check_attention');
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
