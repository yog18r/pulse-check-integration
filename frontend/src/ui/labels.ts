/**
 * Human-friendly labels for integration platforms. Anything not listed is
 * shown title-cased, so unknown integrations still look reasonable. Brand
 * names stay as they are; "Phone" and "Unknown" are words, so they are
 * translated.
 */
import { EN, type Translator } from '../i18n';

const LABELS: Record<string, string> = {
  zha: 'ZHA',
  mqtt: 'MQTT',
  zwave_js: 'Z-Wave',
  esphome: 'ESPHome',
  shelly: 'Shelly',
  matter: 'Matter',
  bluetooth: 'Bluetooth',
  bthome: 'BTHome',
  xiaomi_ble: 'Xiaomi BLE',
  hue: 'Hue',
  tuya: 'Tuya',
  template: 'Template',
};

export function integrationLabel(platform: string, t: Translator = EN): string {
  if (platform === 'mobile_app') return t.t('integration.phone');
  if (platform === 'unknown') return t.t('integration.unknown');
  const known = LABELS[platform];
  if (known) return known;
  return platform
    .split('_')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}
