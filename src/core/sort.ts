/**
 * Selecting and ordering devices for each tab.
 *
 *  Batteries tab      every device with a battery reading, lowest first.
 *  Connectivity tab   only devices with a problem: offline first, then the
 *                     quietest. Healthy devices are left out, because a list
 *                     of 80 fine devices hides the 3 that matter.
 */
import type { ResolvedConfig } from '../card/config';
import type { DrainEstimate } from './drain';
import { batterySeverity, SEVERITY_RANK } from './thresholds';
import type { DeviceHealth } from './types';

/**
 * A level we can sort by even when the reading is binary.
 * "low" sorts to the very top, "not low" to the bottom.
 */
export function sortableBatteryLevel(device: DeviceHealth): number {
  const b = device.battery;
  if (!b) return Number.POSITIVE_INFINITY;
  if (b.level !== undefined) return b.isLow ? Math.min(b.level, 0) : b.level;
  return b.isLow ? -1 : 101;
}

function byName(a: DeviceHealth, b: DeviceHealth): number {
  return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
}

/** Drain estimates keyed by the battery entity id they were computed for. */
export type DrainMap = ReadonlyMap<string, DrainEstimate>;

function drainFor(device: DeviceHealth, drains: DrainMap | undefined): DrainEstimate | undefined {
  const id = device.battery?.entityId;
  return id ? drains?.get(id) : undefined;
}

export function batteryList(
  devices: DeviceHealth[],
  config: ResolvedConfig,
  drains?: DrainMap,
): DeviceHealth[] {
  const useDrain = config.battery_sort === 'replace_soon' && drains !== undefined;

  return devices
    .filter((d) => d.battery !== undefined)
    .sort((a, b) => {
      // Worst battery severity first: a critical battery is urgent whatever
      // the trend says.
      const sev =
        SEVERITY_RANK[batterySeverity(b.battery, config)] -
        SEVERITY_RANK[batterySeverity(a.battery, config)];
      if (sev !== 0) return sev;

      // A charging device is being dealt with: after the others in its band.
      const charging =
        Number(a.battery?.isCharging ?? false) - Number(b.battery?.isCharging ?? false);
      if (charging !== 0) return charging;

      // "Replace soon": fewest days left first. Devices without an estimate
      // come after those with one, ordered by level.
      if (useDrain) {
        const da = drainFor(a, drains)?.daysLeft;
        const db = drainFor(b, drains)?.daysLeft;
        if (da !== undefined && db !== undefined && da !== db) return da - db;
        if (da !== undefined && db === undefined) return -1;
        if (da === undefined && db !== undefined) return 1;
      }

      const level = sortableBatteryLevel(a) - sortableBatteryLevel(b);
      if (level !== 0) return level;
      return byName(a, b);
    });
}

export function connectivityList(devices: DeviceHealth[]): DeviceHealth[] {
  return devices
    .filter((d) => (d.isOffline || d.isQuiet) && !d.snoozedUntil)
    .sort((a, b) => {
      // Offline before quiet.
      if (a.isOffline !== b.isOffline) return a.isOffline ? -1 : 1;
      // Oldest contact first. Unknown timestamps go last.
      const ta = a.lastHeard?.getTime() ?? Number.POSITIVE_INFINITY;
      const tb = b.lastHeard?.getTime() ?? Number.POSITIVE_INFINITY;
      if (ta !== tb) return ta - tb;
      return byName(a, b);
    });
}
