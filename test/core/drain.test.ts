import { describe, expect, it } from 'vitest';
import { estimateDrain, formatDaysLeft, type DrainPoint } from '../../src/core/drain';

const DAY = 24 * 60 * 60 * 1000;
const t0 = Date.UTC(2026, 9, 1);

/** Build daily samples from a starting level and a per-day change. */
function series(days: number, start: number, perDay: number): DrainPoint[] {
  return Array.from({ length: days }, (_, i) => ({
    time: t0 + i * DAY,
    level: start + i * perDay,
  }));
}

describe('estimateDrain', () => {
  it('fits a clean linear drain', () => {
    // 90% dropping 2%/day for 10 days -> now at 72%
    const est = estimateDrain(series(10, 90, -2), 72);
    expect(est?.ratePerDay).toBeCloseTo(2, 5);
    expect(est?.daysLeft).toBeCloseTo(36, 5);
    expect(est?.samples).toBe(10);
  });

  it('copes with noisy samples', () => {
    const noisy = series(14, 80, -1).map((p, i) => ({
      ...p,
      level: p.level + (i % 2 ? 0.6 : -0.6),
    }));
    const est = estimateDrain(noisy, 67);
    expect(est?.ratePerDay).toBeGreaterThan(0.8);
    expect(est?.ratePerDay).toBeLessThan(1.2);
  });

  it('refuses thin or short data', () => {
    expect(estimateDrain(series(2, 90, -2), 86)).toBeUndefined(); // too few samples
    expect(
      estimateDrain(
        [
          { time: t0, level: 90 },
          { time: t0 + DAY / 2, level: 89 },
          { time: t0 + DAY, level: 88 },
        ],
        88,
      ),
    ).toBeUndefined(); // spans only 1 day
  });

  it('gives no estimate for flat, rising or charging batteries', () => {
    expect(estimateDrain(series(10, 50, 0), 50)).toBeUndefined();
    expect(estimateDrain(series(10, 50, 3), 80)).toBeUndefined();
    expect(estimateDrain(series(10, 50, -0.05), 49.5)).toBeUndefined(); // below noise floor
  });

  it('ignores garbage points and unsorted input', () => {
    const pts = [...series(6, 60, -1)].reverse();
    pts.push({ time: Number.NaN, level: 10 });
    const est = estimateDrain(pts, 55);
    expect(est?.samples).toBe(6);
    expect(est?.ratePerDay).toBeCloseTo(1, 5);
  });

  it('never returns negative days left', () => {
    expect(estimateDrain(series(5, 10, -2), 0)?.daysLeft).toBe(0);
  });
});

describe('formatDaysLeft', () => {
  it('rounds to a friendly unit', () => {
    expect(formatDaysLeft(0.4)).toBe('under a day');
    expect(formatDaysLeft(3.6)).toBe('~4d');
    expect(formatDaysLeft(20)).toBe('~3w');
    expect(formatDaysLeft(100)).toBe('~3mo');
    expect(formatDaysLeft(900)).toBe('1y+');
  });
});
