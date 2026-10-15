/**
 * Looking up a device's `device_settings` entry.
 *
 * Entries are keyed by device id. A battery sensor with no device behind it
 * (a template or cloud sensor) is identified by its entity id instead, so
 * `device_id: sensor.inverter_soc` and `device_id: entity:sensor.inverter_soc`
 * both match the synthetic group the core builds for it.
 */
import type { DeviceSettings, ResolvedConfig } from '../card/config';
import { ORPHAN_PREFIX } from './group';

export function settingsForDevice(
  config: ResolvedConfig,
  deviceId: string,
): DeviceSettings | undefined {
  const bareEntity = deviceId.startsWith(ORPHAN_PREFIX)
    ? deviceId.slice(ORPHAN_PREFIX.length)
    : undefined;
  return config.device_settings.find(
    (s) => s.device_id === deviceId || (bareEntity !== undefined && s.device_id === bareEntity),
  );
}
