/**
 * Relative time formatting: "just now", "5m ago", "2h ago", "3d ago".
 *
 * Deliberately simple and dependency-free. `Intl.RelativeTimeFormat` exists,
 * but produces long strings ("2 hours ago") that don't fit a narrow card.
 */

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function formatRelative(date: Date | undefined, now: Date): string {
  if (!date) return 'never';
  const diff = now.getTime() - date.getTime();
  if (diff < MINUTE) return 'just now';
  if (diff < HOUR) return `${String(Math.floor(diff / MINUTE))}m ago`;
  if (diff < DAY) return `${String(Math.floor(diff / HOUR))}h ago`;
  if (diff < 30 * DAY) return `${String(Math.floor(diff / DAY))}d ago`;
  const months = Math.floor(diff / (30 * DAY));
  return months < 12 ? `${String(months)}mo ago` : `${String(Math.floor(months / 12))}y ago`;
}

/** A threshold in hours rendered the way a person would say it. */
export function formatHours(hours: number): string {
  if (hours < 1) return `${String(Math.round(hours * 60))}m`;
  if (hours < 48) return `${String(hours)}h`;
  const days = hours / 24;
  return Number.isInteger(days) ? `${String(days)}d` : `${String(hours)}h`;
}

/**
 * A coming moment as a clock time: "14:30" today, "Fri 14:30" within a
 * week, a date beyond that. In the browser's time zone and `locale`.
 */
export function formatClock(date: Date, now: Date, locale?: string): string {
  const time: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' };
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(locale, time);
  }
  const withinWeek = date.getTime() - now.getTime() < 6 * DAY;
  return date.toLocaleString(locale, {
    ...time,
    ...(withinWeek ? { weekday: 'short' } : { day: 'numeric', month: 'short' }),
  });
}
