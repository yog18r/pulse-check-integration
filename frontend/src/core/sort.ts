/**
 * Selecting and ordering devices for each tab.
 *
 *  Batteries tab      every device with a battery reading, lowest first.
 *  Connectivity tab   only devices with a problem: offline first, then the
 *                     quietest. Healthy devices are left out, because a list
 *                     of 80 fine devices hides the 3 that matter.
 */
import type { SortOrder } from '../card/config';
import {
  batterySeverity,
  hasConnectivityProblem,
  SEVERITY_RANK,
  type Thresholds,
} from './thresholds';
import type { DeviceHealth, Estimate } from './types';

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

/** Battery history (points + optional estimate) keyed by battery entity id. */
export type DrainMap = ReadonlyMap<string, { estimate?: Estimate | undefined }>;

/** The estimate to sort by: the fetched history's if any, else the device's own. */
export function estimateFor(device: DeviceHealth, drains?: DrainMap): Estimate | undefined {
  const id = device.battery?.entityId;
  return (id ? drains?.get(id)?.estimate : undefined) ?? device.estimate;
}

export function batteryList(
  devices: DeviceHealth[],
  thresholds: Thresholds,
  sort: SortOrder = 'level',
  drains?: DrainMap,
): DeviceHealth[] {
  return devices
    .filter((d) => d.battery !== undefined)
    .sort((a, b) => {
      // Worst battery severity first: a critical battery is urgent whatever
      // the trend says.
      const sev =
        SEVERITY_RANK[batterySeverity(b.battery, thresholds)] -
        SEVERITY_RANK[batterySeverity(a.battery, thresholds)];
      if (sev !== 0) return sev;

      // A charging device is being dealt with: after the others in its band.
      const charging =
        Number(a.battery?.isCharging ?? false) - Number(b.battery?.isCharging ?? false);
      if (charging !== 0) return charging;

      if (sort === 'name') return byName(a, b);

      // "Replace soon": fewest days left first, whatever the basis. Devices
      // without an estimate follow, ordered by level. Nothing is invented.
      if (sort === 'replace_soon') {
        const da = estimateFor(a, drains)?.daysLeft;
        const db = estimateFor(b, drains)?.daysLeft;
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
    .filter((d) => hasConnectivityProblem(d) && !d.snoozedUntil)
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
