import { describe, expect, it, vi } from 'vitest';
import {
  attributeHistoryToDailyPoints,
  HISTORY_DAYS,
  historyToDailyPoints,
  loadDrains,
  rowsToPoints,
} from '../../src/card/statistics';
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

describe('historyToDailyPoints', () => {
  it('averages numeric states per UTC day and drops junk', () => {
    const day = Date.UTC(2026, 9, 10) / 1000;
    const points = historyToDailyPoints([
      { s: '60', lu: day + 100 },
      { s: '62', lu: day + 5000 },
      { s: 'unknown', lu: day + 6000 },
      { state: '50', last_updated: '2026-10-11T12:00:00.000Z' },
      { s: '40' }, // no timestamp at all
    ]);
    expect(points).toEqual([
      { time: Date.UTC(2026, 9, 10), level: 61 },
      { time: Date.UTC(2026, 9, 11), level: 50 },
    ]);
  });
});

describe('attributeHistoryToDailyPoints', () => {
  it('reads a numeric attribute, carrying it forward across rows without one', () => {
    const day = Date.UTC(2026, 9, 10) / 1000;
    const points = attributeHistoryToDailyPoints([
      { s: 'home', attributes: { battery_level: 60 }, last_updated: '2026-10-10T01:00:00Z' },
      { s: 'away', lu: day + 7200 }, // no attributes: still 60
      { s: 'home', a: { battery_level: 50 }, lu: day + 86400 + 100 },
      { s: 'home', a: { battery_level: 'low' }, lu: day + 86400 + 200 }, // junk: skipped
    ]);
    expect(points).toEqual([
      { time: Date.UTC(2026, 9, 10), level: 60 },
      { time: Date.UTC(2026, 9, 11), level: 50 },
    ]);
  });
});

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

    // One statistics call, then one raw-history call for sensor.no_stats.
    expect(callWS).toHaveBeenCalledTimes(2);
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

  it('falls back to raw history for sensors without statistics', async () => {
    const secondsAgo = (days: number) => (FIXED_NOW.getTime() - days * DAY) / 1000;
    const callWS = vi.fn().mockImplementation((message: { type: string }) => {
      if (message.type === 'recorder/statistics_during_period') {
        // Only the door sensor has long-term statistics.
        return Promise.resolve({ 'sensor.front_door_battery': decline(FIXED_NOW, 87, 2) });
      }
      // Raw history for the inverter: several readings a day, some junk.
      return Promise.resolve({
        'sensor.inverter_soc': [
          { state: '80', last_updated: new Date(secondsAgo(6) * 1000).toISOString() },
          { s: '78', lu: secondsAgo(5.9) },
          { s: 'unavailable', lu: secondsAgo(5.5) },
          { s: '76', lu: secondsAgo(4) },
          { s: '74', lu: secondsAgo(3) },
          { s: '72', lu: secondsAgo(2) },
          { s: '70', lu: secondsAgo(1) },
        ],
      });
    });

    const drains = await loadDrains(
      { ...hass, callWS },
      [
        { entityId: 'sensor.front_door_battery', level: 87 },
        { entityId: 'sensor.inverter_soc', level: 68 },
        { entityId: 'vacuum.robot', level: 50 }, // attribute reading: never fetched raw
      ],
      FIXED_NOW,
    );

    // statistics, raw history for the sensor, attribute history for the vacuum
    expect(callWS).toHaveBeenCalledTimes(3);
    const historyCall = callWS.mock.calls[1]?.[0] as Record<string, unknown>;
    expect(historyCall.type).toBe('history/history_during_period');
    expect(historyCall.entity_ids).toEqual(['sensor.inverter_soc']);
    expect(historyCall.no_attributes).toBe(true);

    const inverter = drains.get('sensor.inverter_soc');
    expect(inverter).toBeDefined();
    // 5 distinct days with readings (the two 6 days ago average to 79) + live point.
    expect(inverter?.points).toHaveLength(6);
    expect(inverter?.points[0]?.level).toBeCloseTo(79, 5);
    expect(inverter?.estimate?.ratePerDay).toBeCloseTo(2, 0);
    expect(drains.has('vacuum.robot')).toBe(false);
  });

  it('fetches attribute history for batteries that live on a vacuum or tracker', async () => {
    const secondsAgo = (days: number) => (FIXED_NOW.getTime() - days * DAY) / 1000;
    const callWS = vi.fn().mockImplementation((message: Record<string, unknown>) => {
      if (message.type === 'recorder/statistics_during_period') return Promise.resolve({});
      if (message.no_attributes === true) return Promise.resolve({}); // plain sensors: none here
      // Attributes only sent when they change; rows in between carry forward.
      return Promise.resolve({
        'vacuum.robot': [
          { s: 'docked', a: { battery_level: 100 }, lu: secondsAgo(5) },
          { s: 'cleaning', lu: secondsAgo(4.5) },
          { s: 'docked', a: { battery_level: 80 }, lu: secondsAgo(4) },
          { s: 'docked', a: { battery_level: 60 }, lu: secondsAgo(3) },
          { s: 'docked', a: { battery_level: 40 }, lu: secondsAgo(2) },
          { s: 'unavailable', a: {}, lu: secondsAgo(1.5) },
          { s: 'docked', a: { battery_level: 20 }, lu: secondsAgo(1) },
        ],
      });
    });
    const drains = await loadDrains(
      { ...hass, callWS },
      [{ entityId: 'vacuum.robot', level: 10 }],
      FIXED_NOW,
    );
    const attrCall = callWS.mock.calls
      .map((c) => c[0] as Record<string, unknown>)
      .find((m) => m.no_attributes === false)!;
    expect(attrCall.entity_ids).toEqual(['vacuum.robot']);
    const h = drains.get('vacuum.robot');
    // 5 days ago averages 100 (the carried-forward row counts), then 80, 60, 40, 20; + live.
    expect(h?.points.map((p) => Math.round(p.level))).toEqual([100, 80, 60, 40, 20, 10]);
    // Day buckets sit at midnight while the live point is mid-morning, so the
    // fitted slope is a little under the nominal 20%/day.
    expect(h?.estimate?.ratePerDay).toBeGreaterThan(15);
    expect(h?.estimate?.ratePerDay).toBeLessThan(21);
  });

  it('survives a failing raw-history call', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const callWS = vi
      .fn()
      .mockImplementation((message: { type: string }) =>
        message.type === 'recorder/statistics_during_period'
          ? Promise.resolve({})
          : Promise.reject(new Error('history disabled')),
      );
    const drains = await loadDrains({ ...hass, callWS }, [{ entityId: 'sensor.x', level: 1 }]);
    expect(drains.size).toBe(0);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('fetches the longest window once, draws each device its own window, fits on 14 days', async () => {
    const calls: Record<string, unknown>[] = [];
    const callWS = vi.fn().mockImplementation((message: Record<string, unknown>) => {
      calls.push(message);
      if (message.period === 'day') {
        // 60 days of 1%/day decline for both sensors.
        return Promise.resolve({
          'sensor.a': decline(FIXED_NOW, 40, 1, 60),
          'sensor.b': decline(FIXED_NOW, 90, 1, 60),
        });
      }
      return Promise.resolve({});
    });
    const drains = await loadDrains(
      { ...hass, callWS },
      [
        { entityId: 'sensor.a', level: 40, days: 60 },
        { entityId: 'sensor.b', level: 90 }, // default window
      ],
      FIXED_NOW,
    );
    const dayCall = calls.find((c) => c.period === 'day')!;
    const start = new Date(dayCall.start_time as string).getTime();
    expect((FIXED_NOW.getTime() - start) / DAY).toBeCloseTo(60, 5);
    expect(calls.some((c) => c.period === 'hour')).toBe(false); // no short windows

    expect(drains.get('sensor.a')?.days).toBe(60);
    expect(drains.get('sensor.a')?.points).toHaveLength(61); // 60 daily + live
    expect(drains.get('sensor.b')?.days).toBe(HISTORY_DAYS);
    expect(drains.get('sensor.b')?.points).toHaveLength(HISTORY_DAYS + 1);
    // Both fits use only the last 14 days: same slope, days-left from the level.
    expect(drains.get('sensor.a')?.estimate?.samples).toBe(HISTORY_DAYS + 1);
    expect(drains.get('sensor.a')?.estimate?.ratePerDay).toBeCloseTo(1, 5);
  });

  it('adds an hourly request for windows of three days or less', async () => {
    const HOUR = 60 * 60 * 1000;
    const callWS = vi.fn().mockImplementation((message: Record<string, unknown>) => {
      if (message.period === 'hour') {
        const rows = Array.from({ length: 24 }, (_, i) => {
          const start = FIXED_NOW.getTime() - (24 - i) * HOUR;
          return { start, end: start + HOUR, mean: 50 - i * 0.1 };
        });
        return Promise.resolve({ 'sensor.short': rows });
      }
      return Promise.resolve({ 'sensor.short': decline(FIXED_NOW, 48, 2) });
    });
    const drains = await loadDrains(
      { ...hass, callWS },
      [{ entityId: 'sensor.short', level: 47.6, days: 1 }],
      FIXED_NOW,
    );
    const hourCall = callWS.mock.calls.find(
      (c) => (c[0] as Record<string, unknown>).period === 'hour',
    )?.[0] as Record<string, unknown>;
    expect(hourCall.statistic_ids).toEqual(['sensor.short']);
    const h = drains.get('sensor.short');
    expect(h?.days).toBe(1);
    expect(h?.points).toHaveLength(25); // 24 hourly + live
    expect(h?.estimate?.ratePerDay).toBeCloseTo(2, 1); // still fitted on the daily data
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
