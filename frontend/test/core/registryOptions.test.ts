import { describe, expect, it } from 'vitest';
import { listIntegrations } from '../../src/core/registryOptions';
import { hass } from '../fixtures/hass';

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
