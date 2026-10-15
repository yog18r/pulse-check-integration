/**
 * Card-level view filters: which of the integration's devices THIS card
 * shows. They are distinct from the integration's own exclusions (set in
 * its Configure dialog), which decide what is monitored at all. With one
 * shared integration, a per-room card or a locks-only card is a matter of
 * these lists.
 *
 * Values match names or ids, case-insensitively. An empty list means "all".
 */
import { deviceTypeLabel } from './deviceType';
import type { DeviceHealth } from './types';

export interface ViewFilters {
  /** Area names or ids. */
  areas: string[];
  /** Integration platforms, e.g. "zwave_js". */
  integrations: string[];
  /** Device types, e.g. "lock", or their labels. */
  device_types: string[];
}

export const NO_FILTERS: ViewFilters = { areas: [], integrations: [], device_types: [] };

const lower = (value: string) => value.trim().toLowerCase();

function wanted(list: string[]): Set<string> {
  return new Set(list.map(lower));
}

/**
 * Keep the devices the filters allow.
 *
 * `areaNames` maps area ids to names (from `hass.areas`), so a filter may
 * use either; the device list itself only carries names.
 */
export function filterDevices(
  devices: DeviceHealth[],
  filters: ViewFilters,
  areaNames: Record<string, string> = {},
): DeviceHealth[] {
  const areas = wanted(filters.areas);
  const integrations = wanted(filters.integrations);
  const types = wanted(filters.device_types);
  if (areas.size === 0 && integrations.size === 0 && types.size === 0) return devices;

  // Ids typed in the filter are turned into names once, up front.
  for (const [id, name] of Object.entries(areaNames)) {
    if (areas.has(lower(id))) areas.add(lower(name));
  }

  return devices.filter((d) => {
    if (areas.size > 0 && (d.area === undefined || !areas.has(lower(d.area)))) return false;
    if (integrations.size > 0 && !integrations.has(lower(d.integration))) return false;
    if (
      types.size > 0 &&
      !types.has(d.deviceType) &&
      !types.has(lower(deviceTypeLabel(d.deviceType)))
    ) {
      return false;
    }
    return true;
  });
}
