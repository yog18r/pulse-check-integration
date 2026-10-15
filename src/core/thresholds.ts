/**
 * Thresholds and severity.
 *
 * Resolution order for the quiet threshold, most specific wins:
 *   device override  >  integration override  >  global default
 *
 * Severity rules for a device:
 *   critical  offline, battery at/below critical %, binary "low battery", or an
 *             enhancer says so (e.g. a dead Z-Wave node)
 *   warning   battery at/below warning %, or quiet
 *   ok        everything else
 */
import type { ResolvedConfig } from '../card/config';
import type { BatteryReading, EnhancerExtra, Severity } from './types';

/** Order used for comparing and sorting severities. Higher = worse. */
export const SEVERITY_RANK: Record<Severity, number> = { ok: 0, warning: 1, critical: 2 };

export function worstSeverity(...severities: Severity[]): Severity {
  let worst: Severity = 'ok';
  for (const s of severities) {
    if (SEVERITY_RANK[s] > SEVERITY_RANK[worst]) worst = s;
  }
  return worst;
}

export function resolveQuietThreshold(
  config: ResolvedConfig,
  integration: string,
  deviceId: string,
): number {
  const override = config.device_overrides.find((o) => o.device_id === deviceId);
  if (override?.quiet_threshold_hours !== undefined) return override.quiet_threshold_hours;

  const perIntegration = config.integration_thresholds[integration];
  if (perIntegration !== undefined) return perIntegration;

  return config.quiet_threshold_hours;
}

export function batterySeverity(
  battery: BatteryReading | undefined,
  config: ResolvedConfig,
): Severity {
  if (!battery) return 'ok';
  if (battery.isCharging) return 'ok'; // it is being dealt with
  if (battery.isLow) return 'critical';
  if (battery.level === undefined) return 'ok'; // binary sensor saying "not low"
  if (battery.level <= config.battery_critical) return 'critical';
  if (battery.level <= config.battery_warning) return 'warning';
  return 'ok';
}

export function connectivitySeverity(isOffline: boolean, isQuiet: boolean): Severity {
  if (isOffline) return 'critical';
  if (isQuiet) return 'warning';
  return 'ok';
}

export function extrasSeverity(extras: EnhancerExtra[]): Severity {
  return worstSeverity(...extras.map((e) => e.severity ?? 'ok'));
}
