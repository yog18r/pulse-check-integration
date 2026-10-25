/**
 * The header summary: the counts, and the one-line verdict and breakdown
 * the card makes from them.
 */
import { EN, type Translator } from '../i18n';
import { batterySeverity, type Thresholds } from './thresholds';
import type { DeviceHealth } from './types';

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
  /** Devices whose integration no longer provides them (stale configuration). */
  notProvided: number;
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
  notProvided: 0,
  snoozed: 0,
};

/**
 * Count the devices a card shows. The integration sends whole-house
 * counts; a card with view filters needs its own, and for an unfiltered
 * card this gives the same numbers.
 */
export function summarise(devices: DeviceHealth[], thresholds: Thresholds): Summary {
  const summary = { ...EMPTY_SUMMARY };
  for (const d of devices) {
    if (d.snoozedUntil) {
      summary.snoozed += 1;
      continue;
    }
    if (d.severity === 'critical') summary.critical += 1;
    if (d.severity === 'warning') summary.warning += 1;
    if (d.severity !== 'ok') summary.attention += 1;
    if (d.battery) {
      summary.batteryDevices += 1;
      const battery = batterySeverity(d.battery, thresholds);
      if (battery !== 'ok') summary.lowBatteries += 1;
      if (battery === 'critical') summary.criticalBatteries += 1;
    }
    if (d.isOffline) summary.offline += 1;
    if (d.isQuiet) summary.quiet += 1;
    if (d.isNotProvided) summary.notProvided += 1;
  }
  return summary;
}

/** Short and plain. Reads well in a screen reader too. */
export function headline(summary: Summary, t: Translator = EN): string {
  if (summary.attention === 0) return `✅ ${t.t('headline.ok')}`;
  return `⚠️ ${t.tn('headline.attention', summary.attention)}`;
}

/** "2 low batteries · 1 offline · 3 quiet", or an empty string when all is well. */
export function breakdown(summary: Summary, t: Translator = EN): string {
  const parts: string[] = [];
  if (summary.lowBatteries > 0) parts.push(t.tn('breakdown.low', summary.lowBatteries));
  if (summary.offline > 0) parts.push(t.tn('breakdown.offline', summary.offline));
  if (summary.quiet > 0) parts.push(t.tn('breakdown.quiet', summary.quiet));
  if (summary.notProvided > 0) {
    parts.push(t.tn('breakdown.not_provided', summary.notProvided));
  }
  return parts.join(' · ');
}
