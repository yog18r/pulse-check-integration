/**
 * Grouping a sorted device list into sections: by area, integration or
 * device type. Items keep their order within each group; groups are
 * ordered by label, with the catch-all group ("No area", "Other") last.
 */
import { EN, type Translator } from '../i18n';
import { deviceTypeLabel } from './deviceType';
import type { DeviceHealth } from './types';

export const GROUP_BYS = ['none', 'area', 'integration', 'device_type'] as const;
export type GroupBy = (typeof GROUP_BYS)[number];

export interface DeviceGroup {
  key: string;
  label: string;
  items: DeviceHealth[];
}

export interface GroupLabels {
  /** "zwave_js" -> "Z-Wave". Defaults to the raw platform id. */
  integration?: (platform: string) => string;
}

function keyAndLabel(
  device: DeviceHealth,
  by: Exclude<GroupBy, 'none'>,
  labels: GroupLabels,
  t: Translator,
): [string, string, boolean] {
  switch (by) {
    case 'area':
      return device.area !== undefined
        ? [`area:${device.area}`, device.area, false]
        : ['area:', t.t('group.no_area'), true];
    case 'integration':
      return [
        `integration:${device.integration}`,
        (labels.integration ?? ((p) => p))(device.integration),
        device.integration === 'unknown',
      ];
    case 'device_type':
      return [
        `type:${device.deviceType}`,
        deviceTypeLabel(device.deviceType, t),
        device.deviceType === 'other',
      ];
  }
}

export function groupDevices(
  devices: DeviceHealth[],
  by: GroupBy,
  labels: GroupLabels = {},
  t: Translator = EN,
): DeviceGroup[] {
  if (by === 'none') return [{ key: 'all', label: '', items: devices }];

  const groups = new Map<string, DeviceGroup & { last: boolean }>();
  for (const device of devices) {
    const [key, label, last] = keyAndLabel(device, by, labels, t);
    let group = groups.get(key);
    if (!group) {
      group = { key, label, items: [], last };
      groups.set(key, group);
    }
    group.items.push(device);
  }
  return [...groups.values()]
    .sort((a, b) => Number(a.last) - Number(b.last) || a.label.localeCompare(b.label, t.language))
    .map(({ key, label, items }) => ({ key, label, items }));
}
