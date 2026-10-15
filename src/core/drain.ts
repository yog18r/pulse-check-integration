/**
 * Battery history as the integration sends it, and the "~12d" formatter.
 *
 * The fit itself (least squares over the recorder's daily means) runs on
 * the server; the card only draws the points and shows the result.
 */

export interface DrainPoint {
  /** Milliseconds since epoch. */
  time: number;
  /** Battery level in percent. */
  level: number;
}

export interface DrainEstimate {
  /** Percentage points lost per day. Always positive. */
  ratePerDay: number;
  /** Days until the battery reaches 0% at the current rate. */
  daysLeft: number;
  /** How many samples the fit used, so the UI can hedge on thin data. */
  samples: number;
}

/** What `pulse_check/history` returns for one battery. */
export interface BatteryHistory {
  /** Points over the requested window, oldest first. */
  points: DrainPoint[];
  /** The window those points cover, in days. */
  days: number;
  estimate?: DrainEstimate;
}

/** "~12d", "~3w", "~4mo": rough on purpose. */
export function formatDaysLeft(days: number): string {
  if (days < 1) return 'under a day';
  if (days < 14) return `~${String(Math.round(days))}d`;
  if (days < 60) return `~${String(Math.round(days / 7))}w`;
  if (days < 365) return `~${String(Math.round(days / 30))}mo`;
  return '1y+';
}
