/**
 * Severity from a battery reading or from connectivity, for colouring rows.
 *
 * The integration already decided each device's overall `severity`. The
 * Batteries tab colours rows by the battery alone, though, and the
 * Connectivity tab by connectivity alone, so those two small rules live
 * here as well. The thresholds come from the integration's snapshot, so
 * the card can never disagree with the server.
 *
 *   critical  battery at/below critical %, or a binary "low battery"
 *   warning   battery at/below warning %
 *   ok        everything else, including anything charging
 */
import type { BatteryReading, DeviceHealth, Severity } from './types';

/** The two numbers these rules need. */
export interface Thresholds {
  battery_warning: number;
  battery_critical: number;
}

/** Order used for comparing and sorting severities. Higher = worse. */
export const SEVERITY_RANK: Record<Severity, number> = { ok: 0, warning: 1, critical: 2 };

export function batterySeverity(
  battery: BatteryReading | undefined,
  thresholds: Thresholds,
): Severity {
  if (!battery) return 'ok';
  if (battery.isCharging) return 'ok'; // it is being dealt with
  if (battery.isLow) return 'critical';
  if (battery.level === undefined) return 'ok'; // binary sensor saying "not low"
  if (battery.level <= thresholds.battery_critical) return 'critical';
  if (battery.level <= thresholds.battery_warning) return 'warning';
  return 'ok';
}

export function connectivitySeverity(
  isOffline: boolean,
  isQuiet: boolean,
  isNotProvided = false,
): Severity {
  if (isOffline) return 'critical';
  if (isQuiet || isNotProvided) return 'warning';
  return 'ok';
}

/** Whether a device belongs on the Connectivity tab: offline, quiet or not provided. */
export function hasConnectivityProblem(
  d: Pick<DeviceHealth, 'isOffline' | 'isQuiet' | 'isNotProvided'>,
): boolean {
  return d.isOffline || d.isQuiet || d.isNotProvided === true;
}
