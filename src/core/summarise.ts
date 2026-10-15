/**
 * Header summary: the one-line verdict at the top of the card.
 */
import type { DeviceHealth } from './types';

export interface Summary {
  /** Devices that are warning or critical. */
  attention: number;
  critical: number;
  warning: number;
  /** Battery-powered devices seen, and how many are warning/critical on battery. */
  batteryDevices: number;
  offline: number;
  quiet: number;
}

export function summarise(devices: DeviceHealth[]): Summary {
  const summary: Summary = {
    attention: 0,
    critical: 0,
    warning: 0,
    batteryDevices: 0,
    offline: 0,
    quiet: 0,
  };
  for (const d of devices) {
    if (d.severity === 'critical') summary.critical += 1;
    if (d.severity === 'warning') summary.warning += 1;
    if (d.severity !== 'ok') summary.attention += 1;
    if (d.battery) summary.batteryDevices += 1;
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
