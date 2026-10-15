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

    const door = drains.get('sensor.front_door_battery');
    expect(door?.estimate?.ratePerDay).toBeCloseTo(2, 5);
    expect(door?.estimate?.daysLeft).toBeCloseTo(43.5, 5);
    expect(door?.points).toHaveLength(HISTORY_DAYS + 1); // daily means + the live reading
    expect(door?.points.at(-1)).toEqual({ time: FIXED_NOW.getTime(), level: 87 });
    // Flat history still comes back (for the sparkline) but with no estimate.
    expect(drains.get('sensor.kitchen_ht_battery')?.points.length).toBeGreaterThan(2);
    expect(drains.get('sensor.kitchen_ht_battery')?.estimate).toBeUndefined();
    expect(drains.has('sensor.no_stats')).toBe(false);
  });

  it('lets a sudden drop in the live reading pull the estimate forward', async () => {
    // Two flat weeks at 62% in the recorder, but the sensor now says 42%.
    const callWS = vi.fn().mockResolvedValue({
      'sensor.lock_battery': decline(FIXED_NOW, 62, 0),
    });
    const flat = await loadDrains(
      { ...hass, callWS },
      [{ entityId: 'sensor.lock_battery', level: 62 }],
      FIXED_NOW,
    );
    expect(flat.get('sensor.lock_battery')?.estimate).toBeUndefined(); // genuinely flat

    const dropped = await loadDrains(
      { ...hass, callWS },
      [{ entityId: 'sensor.lock_battery', level: 42 }],
      FIXED_NOW,
    );
    const est = dropped.get('sensor.lock_battery')?.estimate;
    expect(est).toBeDefined();
    // 20 points lost over the 14-day window: roughly 1.4%/day on the fit's
    // slope once the single live point is weighed against two flat weeks.
    expect(est!.ratePerDay).toBeGreaterThanOrEqual(0.4);
    expect(est!.daysLeft).toBeLessThan(120);
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
