import { describe, expect, it, vi } from 'vitest';
import { loadLastReported, MAX_LOOKUPS_PER_ROUND } from '../../src/card/lastReported';
import { hass } from '../fixtures/hass';

describe('loadLastReported', () => {
  it('asks the REST API per entity and parses last_reported', async () => {
    const callApi = vi.fn().mockImplementation((_method: string, path: string) => {
      if (path.endsWith('sensor.broken')) return Promise.reject(new Error('404'));
      return Promise.resolve({
        entity_id: decodeURIComponent(path.replace('states/', '')),
        last_reported: '2026-10-15T08:00:00.000Z',
        last_updated: '2026-10-14T08:00:00.000Z',
      });
    });
    const result = await loadLastReported({ ...hass, callApi }, [
      'sensor.a',
      'sensor.broken',
      'sensor.b',
    ]);
    expect(callApi).toHaveBeenCalledTimes(3);
    expect(callApi).toHaveBeenCalledWith('GET', 'states/sensor.a');
    expect(result.get('sensor.a')?.toISOString()).toBe('2026-10-15T08:00:00.000Z');
    expect(result.get('sensor.b')?.toISOString()).toBe('2026-10-15T08:00:00.000Z');
    expect(result.has('sensor.broken')).toBe(false);
  });

  it('falls back to last_updated on older HA versions without last_reported', async () => {
    const callApi = vi.fn().mockResolvedValue({ last_updated: '2026-10-15T07:00:00.000Z' });
    const result = await loadLastReported({ ...hass, callApi }, ['sensor.a']);
    expect(result.get('sensor.a')?.toISOString()).toBe('2026-10-15T07:00:00.000Z');
  });

  it('caps the number of lookups per round', async () => {
    const callApi = vi.fn().mockResolvedValue({ last_reported: '2026-10-15T08:00:00.000Z' });
    const ids = Array.from(
      { length: MAX_LOOKUPS_PER_ROUND + 25 },
      (_, i) => `sensor.s${String(i)}`,
    );
    await loadLastReported({ ...hass, callApi }, ids);
    expect(callApi).toHaveBeenCalledTimes(MAX_LOOKUPS_PER_ROUND);
  });

  it('does nothing without callApi or without entities', async () => {
    expect((await loadLastReported(hass, ['sensor.a'])).size).toBe(0);
    const callApi = vi.fn();
    expect((await loadLastReported({ ...hass, callApi }, [])).size).toBe(0);
    expect(callApi).not.toHaveBeenCalled();
  });
});
