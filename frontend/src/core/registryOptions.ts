/**
 * Option lists for the visual editor's device picker, derived from the
 * registries.
 *
 * The editor gets the same `hass` object as the card, so instead of asking
 * users to paste device ids it can offer a searchable list of what actually
 * exists in their instance. Pure functions, unit tested.
 */
import { ORPHAN_PREFIX, type HassDeviceRegistryEntry, type HassLike } from './types';

/**
 * Devices we never offer:
 *  - "service" devices are virtual (Sun, Forecast, Backup...)
 *  - disabled devices were switched off deliberately by the user
 */
export function isIgnorableDevice(device: HassDeviceRegistryEntry): boolean {
  return device.entry_type === 'service' || device.disabled_by !== null;
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

/** Every real device (no service or disabled ones), alphabetical by display name. */
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
    if (isIgnorableDevice(device)) continue;
    const name = device.name_by_user ?? device.name ?? device.id;
    const option: DeviceOption = { id: device.id, name };

    const area = device.area_id ? hass.areas[device.area_id]?.name : undefined;
    if (area) option.area = area;

    const counts = platforms.get(device.id);
    if (counts) {
      const [best] = [...counts.entries()].sort((a, b) => b[1] - a[1]);
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
 * Battery sensors that have no device (template, cloud and some custom
 * integrations). The card shows them as pseudo-devices keyed
 * `entity:<entity_id>`, so the picker offers them under that id.
 *
 * Entities without a `unique_id` (YAML template sensors, some MQTT ones)
 * never reach the registry at all and exist only in `hass.states`; they
 * count as device-less too.
 */
export function listOrphanBatteryEntities(hass: HassLike): DeviceOption[] {
  const options: DeviceOption[] = [];
  const offer = (entityId: string, platform?: string) => {
    const state = hass.states[entityId];
    if (!state) return;
    const isBattery =
      state.attributes.device_class === 'battery' || 'battery_level' in state.attributes;
    if (!isBattery) return;
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
    offer(entity.entity_id, entity.platform);
  }
  for (const entityId of Object.keys(hass.states)) {
    if (!(entityId in hass.entities)) offer(entityId);
  }
  return options.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
}

/** "Front Door Lock (Hallway · zwave_js)" style label for a dropdown. */
export function deviceLabel(option: DeviceOption): string {
  const extra = [option.area, option.integration].filter(Boolean).join(' · ');
  return extra ? `${option.name} (${extra})` : option.name;
}
