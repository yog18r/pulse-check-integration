/**
 * Human-friendly labels for integration platforms. Anything not listed is
 * shown title-cased, so unknown integrations still look reasonable.
 */
const LABELS: Record<string, string> = {
  zha: 'ZHA',
  mqtt: 'MQTT',
  zwave_js: 'Z-Wave',
  esphome: 'ESPHome',
  shelly: 'Shelly',
  matter: 'Matter',
  mobile_app: 'Phone',
  bluetooth: 'Bluetooth',
  bthome: 'BTHome',
  xiaomi_ble: 'Xiaomi BLE',
  hue: 'Hue',
  tuya: 'Tuya',
  template: 'Template',
  unknown: 'Unknown',
};

export function integrationLabel(platform: string): string {
  const known = LABELS[platform];
  if (known) return known;
  return platform
    .split('_')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}
