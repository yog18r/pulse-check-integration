/**
 * Header summary: the one-line verdict at the top of the card, plus a
 * breakdown of what kind of trouble it is.
 */
import type { ResolvedConfig } from '../card/config';
import { batterySeverity } from './thresholds';
import type { DeviceHealth } from './types';

export interface Summary {
  /** Devices that are warning or critical. */
  attention: number;
  critical: number;
  warning: number;
  /** Battery-powered devices seen. */
  batteryDevices: number;
  /** Battery-powered devices at or below the warning threshold (or binary low). */
  lowBatteries: number;
  offline: number;
  quiet: number;
}

export function summarise(devices: DeviceHealth[], config: ResolvedConfig): Summary {
  const summary: Summary = {
    attention: 0,
    critical: 0,
    warning: 0,
    batteryDevices: 0,
    lowBatteries: 0,
    offline: 0,
    quiet: 0,
  };
  for (const d of devices) {
    if (d.severity === 'critical') summary.critical += 1;
    if (d.severity === 'warning') summary.warning += 1;
    if (d.severity !== 'ok') summary.attention += 1;
    if (d.battery) {
      summary.batteryDevices += 1;
      if (batterySeverity(d.battery, config) !== 'ok') summary.lowBatteries += 1;
    }
    if (d.isOffline) summary.offline += 1;
    if (d.isQuiet) summary.quiet += 1;
  }
  return summary;
}

/** Playful but clear. Reads well in a screen reader too. */
export function headline(summary: Summary): string {
  if (summary.attention === 0) return '🎉 All devices are feeling great';
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
