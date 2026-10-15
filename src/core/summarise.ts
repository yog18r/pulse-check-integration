/**
 * The header summary: the integration's counts, and the one-line verdict
 * and breakdown the card makes from them.
 */

/** The `summary` the integration sends. */
export interface Summary {
  /** Devices that are warning or critical. */
  attention: number;
  critical: number;
  warning: number;
  /** Battery-powered devices seen. */
  batteryDevices: number;
  /** Battery-powered devices at or below the warning threshold (or binary low). */
  lowBatteries: number;
  /** Battery-powered devices at or below the critical threshold (or binary low). */
  criticalBatteries: number;
  offline: number;
  quiet: number;
  /** Devices the user has muted; they count in nothing else. */
  snoozed: number;
}

export const EMPTY_SUMMARY: Summary = {
  attention: 0,
  critical: 0,
  warning: 0,
  batteryDevices: 0,
  lowBatteries: 0,
  criticalBatteries: 0,
  offline: 0,
  quiet: 0,
  snoozed: 0,
};

/** Short and plain. Reads well in a screen reader too. */
export function headline(summary: Summary): string {
  if (summary.attention === 0) return '✅ All devices OK';
  if (summary.attention === 1) return '⚠️ 1 device needs attention';
  return `⚠️ ${String(summary.attention)} devices need attention`;
}

function plural(n: number, singular: string, pluralForm = `${singular}s`): string {
  return `${String(n)} ${n === 1 ? singular : pluralForm}`;
}

/** "2 low batteries · 1 offline · 3 quiet", or an empty string when all is well. */
export function breakdown(summary: Summary): string {
  const parts: string[] = [];
  if (summary.lowBatteries > 0)
    parts.push(plural(summary.lowBatteries, 'low battery', 'low batteries'));
  if (summary.offline > 0) parts.push(`${String(summary.offline)} offline`);
  if (summary.quiet > 0) parts.push(`${String(summary.quiet)} quiet`);
  return parts.join(' · ');
}
