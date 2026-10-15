/**
 * Time formatting: "just now", "5m ago", "2h ago", "3d ago", thresholds
 * such as "24h", and clock times.
 *
 * "5m ago" comes from `Intl.RelativeTimeFormat` in the user's language,
 * in its narrow style so it fits a narrow card. Unit abbreviations for
 * durations ("24h") are catalog entries instead: `Intl.NumberFormat`'s
 * narrow units are ambiguous in places (English months and minutes are
 * both "m").
 */
import { EN, type Translator } from '../i18n';

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// French narrow style reads "-5 min"; its short style is still compact.
const RELATIVE_STYLE: Partial<Record<string, Intl.RelativeTimeFormatStyle>> = { fr: 'short' };
const relativeFormats = new Map<string, Intl.RelativeTimeFormat>();

function relativeFormat(language: string): Intl.RelativeTimeFormat {
  let format = relativeFormats.get(language);
  if (!format) {
    const style = RELATIVE_STYLE[language] ?? 'narrow';
    format = new Intl.RelativeTimeFormat(language, { style, numeric: 'always' });
    relativeFormats.set(language, format);
  }
  return format;
}

export function formatRelative(date: Date | undefined, now: Date, t: Translator = EN): string {
  if (!date) return t.t('time.never');
  const diff = now.getTime() - date.getTime();
  if (diff < MINUTE) return t.t('time.just_now');
  const format = relativeFormat(t.language);
  if (diff < HOUR) return format.format(-Math.floor(diff / MINUTE), 'minute');
  if (diff < DAY) return format.format(-Math.floor(diff / HOUR), 'hour');
  if (diff < 30 * DAY) return format.format(-Math.floor(diff / DAY), 'day');
  const months = Math.floor(diff / (30 * DAY));
  return months < 12
    ? format.format(-months, 'month')
    : format.format(-Math.floor(months / 12), 'year');
}

/** A threshold in hours rendered the way a person would say it. */
export function formatHours(hours: number, t: Translator = EN): string {
  if (hours < 1) return t.t('unit.minutes', { n: Math.round(hours * 60) });
  if (hours < 48) return t.t('unit.hours', { n: hours });
  const days = hours / 24;
  return Number.isInteger(days) ? t.t('unit.days', { n: days }) : t.t('unit.hours', { n: hours });
}

/**
 * A coming moment as a clock time: "14:30" today, "Fri 14:30" within a
 * week, a date beyond that. In the browser's time zone and `locale`.
 */
export function formatClock(date: Date, now: Date, locale: string = EN.language): string {
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
