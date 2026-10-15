/**
 * Selecting and ordering devices for each tab.
 *
 *  Batteries tab      every device with a battery reading, lowest first.
 *  Connectivity tab   only devices with a problem: offline first, then the
 *                     quietest. Healthy devices are left out, because a list
 *                     of 80 fine devices hides the 3 that matter.
 */
import type { BatterySort } from '../card/config';
import type { DrainEstimate } from './drain';
import { batterySeverity, SEVERITY_RANK, type Thresholds } from './thresholds';
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

/** Battery history (points + optional drain estimate) keyed by battery entity id. */
export type DrainMap = ReadonlyMap<string, { estimate?: DrainEstimate | undefined }>;

/** Days left for "replace soon": the history's fit, else the integration's own estimate. */
function daysLeftFor(device: DeviceHealth, drains: DrainMap | undefined): number | undefined {
  const id = device.battery?.entityId;
  const fitted = id ? drains?.get(id)?.estimate?.daysLeft : undefined;
  return fitted ?? device.daysLeft;
}

export function batteryList(
  devices: DeviceHealth[],
  thresholds: Thresholds,
  sort: BatterySort = 'level',
  drains?: DrainMap,
): DeviceHealth[] {
  const useDrain = sort === 'replace_soon';

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

      // "Replace soon": fewest days left first. Devices without an estimate
      // come after those with one, ordered by level.
      if (useDrain) {
        const da = daysLeftFor(a, drains);
        const db = daysLeftFor(b, drains);
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
