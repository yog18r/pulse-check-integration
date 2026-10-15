/**
 * Device type classification, so views can group "all the locks" together.
 *
 * Home Assistant has no "kind of device" field. The nearest thing is what
 * a device's primary entities are: a device with a `lock` entity is a lock,
 * one with a `binary_sensor` of class `motion` is a motion sensor. When a
 * device has several kinds of entity the more specific one wins, in the
 * order of `RULES` below: a lock with a door sensor is still a lock.
 *
 * Mirrored by the integration's `core/device_type.py`; both are checked
 * against the shared golden file.
 */
import type { HassEntityRegistryEntry, HassEntityState } from './types';

export const DEVICE_TYPES = [
  'lock',
  'cover',
  'vacuum',
  'phone',
  'media',
  'remote',
  'climate',
  'motion',
  'contact',
  'light',
  'switch',
  'other',
] as const;
export type DeviceType = (typeof DEVICE_TYPES)[number];

const MOTION_CLASSES = new Set(['motion', 'occupancy', 'presence', 'moving']);
const CONTACT_CLASSES = new Set(['door', 'window', 'opening', 'garage_door', 'vibration']);
const CLIMATE_CLASSES = new Set(['temperature', 'humidity']);

/** [type, domain, device classes] in priority order; null means any device class. */
const RULES: readonly (readonly [DeviceType, string, ReadonlySet<string> | null])[] = [
  ['lock', 'lock', null],
  ['cover', 'cover', null],
  ['vacuum', 'vacuum', null],
  ['media', 'media_player', null],
  ['remote', 'remote', null],
  ['climate', 'climate', null],
  ['motion', 'binary_sensor', MOTION_CLASSES],
  ['contact', 'binary_sensor', CONTACT_CLASSES],
  ['light', 'light', null],
  ['switch', 'switch', null],
  ['climate', 'sensor', CLIMATE_CLASSES],
];

export function classifyDevice(
  entities: HassEntityRegistryEntry[],
  states: HassEntityState[],
  integration: string,
): DeviceType {
  if (integration === 'mobile_app') return 'phone';
  const byId = new Map(states.map((s) => [s.entity_id, s]));
  const primary = entities.filter((e) => e.entity_category === undefined);
  const candidates = primary.length > 0 ? primary : entities;

  const kinds = candidates.map((e) => {
    const domain = e.entity_id.split('.', 1)[0] ?? '';
    const deviceClass = byId.get(e.entity_id)?.attributes.device_class;
    return { domain, deviceClass: typeof deviceClass === 'string' ? deviceClass : undefined };
  });

  const hasTracker = kinds.some((k) => k.domain === 'device_tracker');
  const hasBatteryAttribute = candidates.some(
    (e) => byId.get(e.entity_id)?.attributes.battery_level !== undefined,
  );
  if (hasTracker && hasBatteryAttribute) return 'phone';

  for (const [type, domain, classes] of RULES) {
    for (const kind of kinds) {
      if (kind.domain !== domain) continue;
      if (classes === null || (kind.deviceClass !== undefined && classes.has(kind.deviceClass))) {
        return type;
      }
    }
  }
  return 'other';
}

const LABELS: Record<DeviceType, string> = {
  lock: 'Locks',
  cover: 'Covers and blinds',
  vacuum: 'Vacuums',
  phone: 'Phones and trackers',
  media: 'Media players',
  remote: 'Remotes',
  climate: 'Climate',
  motion: 'Motion sensors',
  contact: 'Contact sensors',
  light: 'Lights',
  switch: 'Switches',
  other: 'Other',
};

export function deviceTypeLabel(type: DeviceType): string {
  return LABELS[type];
}
