/**
 * Grouping: turn HA's flat entity list into one group per physical device.
 *
 * HA's registries are keyed the other way round from what we want. Entities
 * point at their device (`entity.device_id`), so we walk every entity once
 * and bucket it by device. Entities with no device at all get a synthetic
 * group of their own so a lone template battery sensor is still visible.
 */
import type {
  HassDeviceRegistryEntry,
  HassEntityRegistryEntry,
  HassEntityState,
  HassLike,
} from './types';

/** All the raw material about one device, before any analysis. */
export interface DeviceGroup {
  /** Registry id, or `entity:<entity_id>` for an entity with no device. */
  deviceId: string;
  /** Null for synthetic single-entity groups. */
  device: HassDeviceRegistryEntry | null;
  entities: HassEntityRegistryEntry[];
  /** States for the entities above, in the same order, skipping any without a state. */
  states: HassEntityState[];
}

/** Prefix used for the synthetic id of a device-less entity. */
export const ORPHAN_PREFIX = 'entity:';

/**
 * Devices we never want to show:
 *  - "service" devices are virtual (Sun, Forecast, Backup...)
 *  - disabled devices were switched off deliberately by the user
 */
export function isIgnorableDevice(device: HassDeviceRegistryEntry): boolean {
  return device.entry_type === 'service' || device.disabled_by !== null;
}

export function collectDeviceGroups(hass: HassLike): DeviceGroup[] {
  // Map<string, T> is like a Record but keeps insertion order and has a nicer API.
  const groups = new Map<string, DeviceGroup>();

  for (const entity of Object.values(hass.entities)) {
    const state = hass.states[entity.entity_id];

    let key: string;
    let device: HassDeviceRegistryEntry | null;

    if (entity.device_id !== undefined) {
      const registryDevice = hass.devices[entity.device_id];
      // An entity can reference a device id that isn't in the registry we
      // were given (stale registry, partial fixture). Treat as orphan.
      if (registryDevice === undefined) {
        key = ORPHAN_PREFIX + entity.entity_id;
        device = null;
      } else {
        if (isIgnorableDevice(registryDevice)) continue;
        key = registryDevice.id;
        device = registryDevice;
      }
    } else {
      key = ORPHAN_PREFIX + entity.entity_id;
      device = null;
    }

    let group = groups.get(key);
    if (!group) {
      group = { deviceId: key, device, entities: [], states: [] };
      groups.set(key, group);
    }
    group.entities.push(entity);
    if (state) group.states.push(state);
  }

  return [...groups.values()];
}

/**
 * The integration ("platform") for a device. Most devices have one; a few
 * mix in helpers (e.g. a `template` sensor attached to a Zigbee device), so
 * we take the most common platform among the device's entities.
 */
export function dominantIntegration(entities: HassEntityRegistryEntry[]): string {
  const counts = new Map<string, number>();
  for (const e of entities) {
    const p = e.platform ?? 'unknown';
    counts.set(p, (counts.get(p) ?? 0) + 1);
  }
  let best = 'unknown';
  let bestCount = -1;
  for (const [platform, count] of counts) {
    if (count > bestCount) {
      best = platform;
      bestCount = count;
    }
  }
  return best;
}

/** Human-facing name for a group: the user's rename, then the device name, then the entity's. */
export function displayName(group: DeviceGroup): string {
  if (group.device) {
    return group.device.name_by_user ?? group.device.name ?? group.deviceId;
  }
  const first = group.states[0] ?? null;
  const friendly = first?.attributes.friendly_name;
  if (typeof friendly === 'string' && friendly !== '') return friendly;
  return group.entities[0]?.entity_id ?? group.deviceId;
}

/** Area name for a group: the device's area, else the first entity's own area. */
export function areaName(group: DeviceGroup, hass: HassLike): string | undefined {
  const areaId = group.device?.area_id ?? group.entities.find((e) => e.area_id)?.area_id;
  if (!areaId) return undefined;
  return hass.areas[areaId]?.name;
}
