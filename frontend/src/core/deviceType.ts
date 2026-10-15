/**
 * Device types, as the integration classifies them, with display labels.
 *
 * The classification itself (a device with a `lock` entity is a lock, one
 * with a motion `binary_sensor` is a motion sensor...) runs on the server;
 * the card only groups and labels.
 */

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

export function isDeviceType(value: unknown): value is DeviceType {
  return typeof value === 'string' && (DEVICE_TYPES as readonly string[]).includes(value);
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
