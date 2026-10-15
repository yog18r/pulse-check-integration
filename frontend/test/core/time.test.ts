import { describe, expect, it } from 'vitest';
import { formatClock, formatHours, formatRelative } from '../../src/core/time';
import { FIXED_NOW, hoursAgo, minutesAgo } from '../fixtures/hass';

const now = FIXED_NOW;
const at = (iso: string) => new Date(iso);

describe('formatRelative', () => {
  it('handles the common buckets', () => {
    expect(formatRelative(undefined, now)).toBe('never');
    expect(formatRelative(now, now)).toBe('just now');
    expect(formatRelative(at(minutesAgo(now, 5)), now)).toBe('5m ago');
    expect(formatRelative(at(hoursAgo(now, 2)), now)).toBe('2h ago');
    expect(formatRelative(at(hoursAgo(now, 47)), now)).toBe('1d ago');
    expect(formatRelative(at(hoursAgo(now, 72)), now)).toBe('3d ago');
    expect(formatRelative(at(hoursAgo(now, 24 * 45)), now)).toBe('1mo ago');
    expect(formatRelative(at(hoursAgo(now, 24 * 400)), now)).toBe('1y ago');
  });
});

describe('formatHours', () => {
  it('reads naturally', () => {
    expect(formatHours(0.5)).toBe('30m');
    expect(formatHours(12)).toBe('12h');
    expect(formatHours(24)).toBe('24h');
    expect(formatHours(48)).toBe('2d');
    expect(formatHours(72)).toBe('3d');
    expect(formatHours(50)).toBe('50h');
  });
});

describe('formatClock', () => {
  it('drops the date today and names the day within a week', () => {
    const later = new Date(now.getTime() + 4.5 * 60 * 60 * 1000);
    expect(formatClock(later, now, 'en-GB')).toBe('14:30');
    const friday = new Date('2026-10-16T08:00:00Z');
    expect(formatClock(friday, now, 'en-GB')).toBe('Fri 08:00');
    const far = new Date('2026-11-02T08:00:00Z');
    expect(formatClock(far, now, 'en-GB')).toBe('2 Nov, 08:00');
  });
});
