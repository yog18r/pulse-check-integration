import { describe, expect, it, vi } from 'vitest';
import { HISTORY_DAYS, loadDrains, rowsToPoints } from '../../src/card/statistics';
import type { HassLike } from '../../src/core/types';
import { FIXED_NOW, hass } from '../fixtures/hass';

const DAY = 24 * 60 * 60 * 1000;

/** Daily rows declining `perDay` percent, ending at `endLevel` on `now`. */
function decline(now: Date, endLevel: number, perDay: number, days = HISTORY_DAYS) {
  return Array.from({ length: days }, (_, i) => {
    const start = now.getTime() - (days - i) * DAY;
    return { start, end: start + DAY, mean: endLevel + (days - i) * perDay };
  });
}

describe('rowsToPoints', () => {
  it('accepts epoch ms and ISO starts, and skips null means', () => {
    const points = rowsToPoints([
      { start: 1_000, mean: 50 },
      { start: '2026-10-15T00:00:00.000Z', mean: 49 },
      { start: 2_000, mean: null },
    ]);
    expect(points).toEqual([
      { time: 1_000, level: 50 },
      { time: Date.UTC(2026, 9, 15), level: 49 },
    ]);
  });
});

describe('loadDrains', () => {
  it('asks the recorder for daily means and estimates each sensor', async () => {
    const callWS = vi.fn().mockResolvedValue({
      'sensor.front_door_battery': decline(FIXED_NOW, 87, 2),
      'sensor.kitchen_ht_battery': decline(FIXED_NOW, 92, 0), // flat: no estimate
    });
    const withWS: HassLike = { ...hass, callWS };

    const drains = await loadDrains(
      withWS,
      [
        { entityId: 'sensor.front_door_battery', level: 87 },
        { entityId: 'sensor.kitchen_ht_battery', level: 92 },
        { entityId: 'sensor.no_stats', level: 50 },
      ],
      FIXED_NOW,
    );

    expect(callWS).toHaveBeenCalledOnce();
    const message = callWS.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(message.type).toBe('recorder/statistics_during_period');
    expect(message.period).toBe('day');
    expect(message.statistic_ids).toEqual([
      'sensor.front_door_battery',
      'sensor.kitchen_ht_battery',
      'sensor.no_stats',
    ]);

    expect(drains.get('sensor.front_door_battery')?.ratePerDay).toBeCloseTo(2, 5);
    expect(drains.get('sensor.front_door_battery')?.daysLeft).toBeCloseTo(43.5, 5);
    expect(drains.has('sensor.kitchen_ht_battery')).toBe(false);
    expect(drains.has('sensor.no_stats')).toBe(false);
  });

  it('returns an empty map without a websocket or without batteries', async () => {
    expect((await loadDrains(hass, [{ entityId: 'sensor.x', level: 1 }])).size).toBe(0);
    const callWS = vi.fn();
    expect((await loadDrains({ ...hass, callWS }, [])).size).toBe(0);
    expect(callWS).not.toHaveBeenCalled();
  });

  it('swallows recorder errors', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const callWS = vi.fn().mockRejectedValue(new Error('recorder not loaded'));
    const drains = await loadDrains({ ...hass, callWS }, [{ entityId: 'sensor.x', level: 1 }]);
    expect(drains.size).toBe(0);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
