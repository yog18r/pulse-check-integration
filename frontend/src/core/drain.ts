/**
 * Battery history as the integration sends it, and the "~12d" formatter.
 *
 * The estimates themselves (cycles, kinds, fits) are made on the server;
 * the card only draws the points and shows the result with its basis.
 */
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
export function formatDaysLeft(days: number): string {
  if (days < 1) return 'under a day';
  if (days < 14) return `~${String(Math.round(days))}d`;
  if (days < 60) return `~${String(Math.round(days / 7))}w`;
  if (days < 365) return `~${String(Math.round(days / 30))}mo`;
  return '1y+';
}
