/**
 * Option lists for the visual editor's device picker, derived from the
 * registries.
 *
 * The editor gets the same `hass` object as the card, so instead of asking
 * users to paste device ids it can offer a searchable list of what actually
 * exists in their instance. Pure functions, unit tested.
 */
import { ORPHAN_PREFIX, type HassDeviceRegistryEntry, type HassLike } from './types';

/** Pulse Check's own platform. Its entities are never watched, so never offered. */
export const OWN_INTEGRATION = 'pulse_check';

/**
 * Disabled devices were switched off deliberately by the user, and the
 * integration skips them. "Service" devices (Sun, AdGuard Home, Backup)
 * are watched like any other, so they are offered too.
 */
export function isDisabledDevice(device: HassDeviceRegistryEntry): boolean {
  return device.disabled_by !== null;
}

export interface IntegrationOption {
  /** The platform id used in config, e.g. "zwave_js". */
  id: string;
  /** How many entities that integration provides; useful for sorting and display. */
  entityCount: number;
}

export interface DeviceOption {
  id: string;
  name: string;
  area?: string;
  /** Dominant integration, so two devices with the same name can be told apart. */
  integration?: string;
}

/** Every integration that provides at least one entity, most entities first. */
export function listIntegrations(hass: HassLike): IntegrationOption[] {
  const counts = new Map<string, number>();
  for (const entity of Object.values(hass.entities)) {
    if (!entity.platform) continue;
    counts.set(entity.platform, (counts.get(entity.platform) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([id, entityCount]) => ({ id, entityCount }))
    .sort((a, b) => b.entityCount - a.entityCount || a.id.localeCompare(b.id));
}

/**
 * Every device the integration can watch, services included, alphabetical
 * by display name. Left out: disabled devices, and Pulse Check's own
 * device (a service device whose entities are all Pulse Check's).
 */
export function listDevices(hass: HassLike): DeviceOption[] {
  // One pass over entities to learn each device's integration.
  const platforms = new Map<string, Map<string, number>>();
  for (const entity of Object.values(hass.entities)) {
    if (!entity.device_id || !entity.platform) continue;
    let perDevice = platforms.get(entity.device_id);
    if (!perDevice) {
      perDevice = new Map();
      platforms.set(entity.device_id, perDevice);
    }
    perDevice.set(entity.platform, (perDevice.get(entity.platform) ?? 0) + 1);
  }

  const options: DeviceOption[] = [];
  for (const device of Object.values(hass.devices)) {
    if (isDisabledDevice(device)) continue;
    const counts = platforms.get(device.id);
    // Only Pulse Check's own sensors: the integration ignores those, so
    // this is Pulse Check's own device. (It also attaches sensors to the
    // devices it watches; those have entities of their own too.)
    if (counts?.size === 1 && counts.has(OWN_INTEGRATION)) continue;
    const name = device.name_by_user ?? device.name ?? device.id;
    const option: DeviceOption = { id: device.id, name };

    const area = device.area_id ? hass.areas[device.area_id]?.name : undefined;
    if (area) option.area = area;

    if (counts) {
      // Pulse Check's own sensors never decide which integration a device is:
      // a device with one battery sensor and both of them would read as ours.
      const [best] = [...counts.entries()]
        .filter(([platform]) => platform !== OWN_INTEGRATION)
        .sort((a, b) => b[1] - a[1]);
      if (best) option.integration = best[0];
    }
    options.push(option);
  }

  return options.sort(
    (a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.id.localeCompare(b.id),
  );
}

/**
 * Entities that have no device: template sensors, automations, scripts,
 * cloud and some custom integrations' entities. The integration watches
 * each as a pseudo-device keyed `entity:<entity_id>` (for its battery, or
 * for being unavailable), so the picker offers them under that id.
 *
 * Entities without a `unique_id` (YAML template sensors, some MQTT ones)
 * never reach the registry at all and exist only in `hass.states`; they
 * count as device-less too. Disabled entities are not offered: Home
 * Assistant leaves them out of `hass.entities` and they have no state.
 * Config entities (settings
 * such as an inverter's minimum charge) are left out: the integration
 * draws no conclusion from them.
 */
export function listOrphanEntities(hass: HassLike): DeviceOption[] {
  const options: DeviceOption[] = [];
  const offer = (entityId: string, platform?: string) => {
    const state = hass.states[entityId];
    if (!state) return;
    const friendly = state.attributes.friendly_name;
    const option: DeviceOption = {
      id: ORPHAN_PREFIX + entityId,
      name: typeof friendly === 'string' && friendly !== '' ? friendly : entityId,
    };
    if (platform) option.integration = platform;
    options.push(option);
  };

  for (const entity of Object.values(hass.entities)) {
    if (entity.device_id !== undefined || entity.entity_category === 'config') continue;
    if (entity.platform === OWN_INTEGRATION) continue;
    offer(entity.entity_id, entity.platform);
  }
  for (const entityId of Object.keys(hass.states)) {
    if (!(entityId in hass.entities)) offer(entityId);
  }
  return options.sort(
    (a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.id.localeCompare(b.id),
  );
}

/** "Front Door Lock (Hallway · zwave_js)" style label for a dropdown. */
export function deviceLabel(option: DeviceOption): string {
  const extra = [option.area, option.integration].filter(Boolean).join(' · ');
  return extra ? `${option.name} (${extra})` : option.name;
}
