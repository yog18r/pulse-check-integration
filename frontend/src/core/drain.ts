/**
 * Battery history as the integration sends it, and the "~12d" formatter.
 *
 * The estimates themselves (cycles, kinds, fits) are made on the server;
 * the card only draws the points and shows the result with its basis.
 */
import { EN, type Translator } from '../i18n';
import type { Estimate } from './types';

export interface DrainPoint {
  /** Milliseconds since epoch. */
  time: number;
  /** Battery level in percent. */
  level: number;
}

/** What `pulse_check/history` returns for one battery. */
export interface BatteryHistory {
  /** Points over the requested window, oldest first. */
  points: DrainPoint[];
  /** The window those points cover, in days. */
  days: number;
  /** The same estimate the device carries, when the integration has one. */
  estimate?: Estimate;
}

/** "~12d", "~3w", "~4mo": rough on purpose. */
export function formatDaysLeft(days: number, t: Translator = EN): string {
  if (days < 1) return t.t('days_left.under_day');
  if (days < 14) return `~${t.t('unit.days', { n: Math.round(days) })}`;
  if (days < 60) return `~${t.t('unit.weeks', { n: Math.round(days / 7) })}`;
  if (days < 365) return `~${t.t('unit.months', { n: Math.round(days / 30) })}`;
  return t.t('days_left.year_plus');
}
