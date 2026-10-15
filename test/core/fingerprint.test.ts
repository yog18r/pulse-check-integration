import { describe, expect, it } from 'vitest';
import { fingerprint, registriesChanged } from '../../src/core/fingerprint';
import { FIXED_NOW, hass, makeState } from '../fixtures/hass';

describe('fingerprint', () => {
  it('is stable for identical input', () => {
    expect(fingerprint(hass)).toBe(fingerprint({ ...hass }));
  });

  it('changes when a device entity updates', () => {
    const changed = {
      ...hass,
      states: {
        ...hass.states,
        'sensor.front_door_battery': makeState('sensor.front_door_battery', '86', FIXED_NOW, {
          attributes: { device_class: 'battery' },
        }),
      },
    };
    expect(fingerprint(changed)).not.toBe(fingerprint(hass));
  });

  it('ignores entities that have no device and no battery', () => {
    const changed = {
      ...hass,
      states: {
        ...hass.states,
        'sensor.random_template': makeState('sensor.random_template', '43', FIXED_NOW),
      },
    };
    expect(fingerprint(changed)).toBe(fingerprint(hass));
  });
});

describe('registriesChanged', () => {
  it('compares registry identity, not states', () => {
    expect(registriesChanged(undefined, hass)).toBe(true);
    expect(registriesChanged(hass, { ...hass, states: {} })).toBe(false);
    expect(registriesChanged(hass, { ...hass, devices: { ...hass.devices } })).toBe(true);
  });
});
