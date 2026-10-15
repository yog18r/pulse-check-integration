/**
 * The shopping list: which batteries to buy, grouped by type.
 *
 * A device is on the list when its battery is at or below the warning
 * threshold, or its binary sensor says "low". The battery type comes from
 * the user's `device_overrides` (there is no reliable way to know that a
 * sensor takes a CR2032 from Home Assistant's data). Devices with no type
 * configured are grouped under "unknown" so they still show up.
 */
import type { ResolvedConfig } from '../card/config';
import { batterySeverity } from './thresholds';
import type { DeviceHealth } from './types';

export const UNKNOWN_BATTERY_TYPE = 'Unknown type';

export interface ShoppingGroup {
  batteryType: string;
  /** True for the catch-all group, so the UI can explain how to set types. */
  isUnknown: boolean;
  devices: DeviceHealth[];
}

export function batteryTypeFor(device: DeviceHealth, config: ResolvedConfig): string | undefined {
  const override = config.device_overrides.find((o) => o.device_id === device.deviceId);
  const type = override?.battery_type?.trim();
  return type === undefined || type === '' ? undefined : type;
}

export function shoppingList(devices: DeviceHealth[], config: ResolvedConfig): ShoppingGroup[] {
  const groups = new Map<string, ShoppingGroup>();

  for (const device of devices) {
    if (!device.battery || batterySeverity(device.battery, config) === 'ok') continue;
    const type = batteryTypeFor(device, config) ?? UNKNOWN_BATTERY_TYPE;
    let group = groups.get(type);
    if (!group) {
      group = { batteryType: type, isUnknown: type === UNKNOWN_BATTERY_TYPE, devices: [] };
      groups.set(type, group);
    }
    group.devices.push(device);
  }

  return [...groups.values()]
    .map((g) => ({
      ...g,
      devices: [...g.devices].sort((a, b) => a.name.localeCompare(b.name)),
    }))
    .sort((a, b) => {
      if (a.isUnknown !== b.isUnknown) return a.isUnknown ? 1 : -1; // unknown last
      return a.batteryType.localeCompare(b.batteryType);
    });
}
