/**
 * The action list: what to actually do about each low battery.
 *
 *   replace   "Replace 2 × AA in Kitchen Mini Switch"
 *   charge    "Charge Office 1 Large"  (rechargeable: true in device_settings)
 *
 * plus a shopping summary: how many of each battery type to buy, totalled
 * across the devices that need replacing.
 *
 * A device is on the list when its battery is at or below the warning
 * threshold or its binary sensor says "low", unless it is charging or
 * snoozed. Battery type, count and rechargeable come from the user's
 * `device_settings`; Home Assistant has no reliable way to know them.
 */
import type { DeviceSettings, ResolvedConfig } from '../card/config';
import { settingsForDevice } from './settings';
import { batterySeverity } from './thresholds';
import type { DeviceHealth, Severity } from './types';

export const UNKNOWN_BATTERY_TYPE = 'Unknown type';

export type ActionKind = 'replace' | 'charge';

export interface ActionItem {
  kind: ActionKind;
  device: DeviceHealth;
  severity: Severity;
  /** Battery type, or UNKNOWN_BATTERY_TYPE when not configured. */
  batteryType: string;
  /** Cells to replace (1 when not configured). Meaningless for "charge". */
  count: number;
  /** "Replace 2 × AA in Kitchen Mini Switch" */
  label: string;
}

export interface ShoppingLine {
  batteryType: string;
  /** Total cells across every device needing this type. */
  count: number;
  devices: number;
}

export interface ActionList {
  replace: ActionItem[];
  charge: ActionItem[];
  /** Totals for the "to buy" summary, biggest first, unknown last. */
  shopping: ShoppingLine[];
}

export function settingsFor(
  device: DeviceHealth,
  config: ResolvedConfig,
): DeviceSettings | undefined {
  return settingsForDevice(config, device.deviceId);
}

export function needsAttention(device: DeviceHealth, config: ResolvedConfig): boolean {
  if (!device.battery || device.snoozedUntil) return false;
  return batterySeverity(device.battery, config) !== 'ok';
}

function describe(kind: ActionKind, device: DeviceHealth, type: string, count: number): string {
  if (kind === 'charge') return `Charge ${device.name}`;
  if (type === UNKNOWN_BATTERY_TYPE) return `Replace the battery in ${device.name}`;
  const what = count > 1 ? `${String(count)} × ${type}` : type;
  return `Replace ${what} in ${device.name}`;
}

export function actionList(devices: DeviceHealth[], config: ResolvedConfig): ActionList {
  const replace: ActionItem[] = [];
  const charge: ActionItem[] = [];

  for (const device of devices) {
    if (!needsAttention(device, config) || !device.battery) continue;
    const settings = settingsFor(device, config);
    const kind: ActionKind = settings?.rechargeable ? 'charge' : 'replace';
    const trimmedType = settings?.battery_type?.trim();
    const batteryType =
      trimmedType === undefined || trimmedType === '' ? UNKNOWN_BATTERY_TYPE : trimmedType;
    const count = settings?.battery_count ?? 1;
    const item: ActionItem = {
      kind,
      device,
      severity: batterySeverity(device.battery, config),
      batteryType,
      count,
      label: describe(kind, device, batteryType, count),
    };
    (kind === 'charge' ? charge : replace).push(item);
  }

  // Worst first within each list, then by name for stability.
  const rank: Record<Severity, number> = { critical: 0, warning: 1, ok: 2 };
  const order = (a: ActionItem, b: ActionItem) =>
    rank[a.severity] - rank[b.severity] || a.device.name.localeCompare(b.device.name);
  replace.sort(order);
  charge.sort(order);

  const totals = new Map<string, ShoppingLine>();
  for (const item of replace) {
    const line = totals.get(item.batteryType) ?? {
      batteryType: item.batteryType,
      count: 0,
      devices: 0,
    };
    line.count += item.count;
    line.devices += 1;
    totals.set(item.batteryType, line);
  }
  const shopping = [...totals.values()].sort((a, b) => {
    const ua = a.batteryType === UNKNOWN_BATTERY_TYPE;
    const ub = b.batteryType === UNKNOWN_BATTERY_TYPE;
    if (ua !== ub) return ua ? 1 : -1;
    return b.count - a.count || a.batteryType.localeCompare(b.batteryType);
  });

  return { replace, charge, shopping };
}
