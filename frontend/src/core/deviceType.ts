/**
 * Device types, as the integration classifies them, with display labels.
 *
 * The classification itself (a device with a `lock` entity is a lock, one
 * with a motion `binary_sensor` is a motion sensor...) runs on the server;
 * the card only groups and labels.
 */

import { EN, type Translator } from '../i18n';

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

/** "Locks", "Motion sensors": a group heading, in the user's language. */
export function deviceTypeLabel(type: DeviceType, t: Translator = EN): string {
  return t.t(`type.${type}`);
}
