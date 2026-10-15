import { describe, expect, it } from 'vitest';
import { parseSnapshot } from '../../src/card/snapshot';
import { deviceTypeLabel } from '../../src/core/deviceType';
import { groupDevices } from '../../src/core/grouping';
import { batteryList } from '../../src/core/sort';
import { SNAPSHOT_PAYLOAD } from '../fixtures/snapshot';

const snapshot = parseSnapshot(SNAPSHOT_PAYLOAD);
const devices = batteryList(snapshot.devices, snapshot.config);

describe('groupDevices', () => {
  it('none: one unlabelled group with everything in order', () => {
    const groups = groupDevices(devices, 'none');
    expect(groups).toHaveLength(1);
    expect(groups[0]?.label).toBe('');
    expect(groups[0]?.items).toBe(devices);
  });

  it('area: alphabetical, devices without an area last', () => {
    const groups = groupDevices(devices, 'area');
    expect(groups.map((g) => g.label)).toEqual([
      'Bedroom',
      'Garage',
      'Hallway',
      'Kitchen',
      'Living Room',
      'No area',
    ]);
    expect(groups.at(-1)!.items.map((d) => d.name)).toEqual(
      expect.arrayContaining(['TV Remote Battery', 'Pixel 9', 'Dog Collar Tracker']),
    );
  });

  it('integration: uses the label function', () => {
    const groups = groupDevices(devices, 'integration', { integration: (p) => p.toUpperCase() });
    expect(groups.map((g) => g.label)).toContain('ZWAVE_JS');
  });

  it('device_type: human labels, Other last, order within a group preserved', () => {
    const groups = groupDevices(devices, 'device_type');
    expect(groups.at(-1)?.label).toBe('Other');
    const motion = groups.find((g) => g.label === deviceTypeLabel('motion'))!;
    // batteryList put the 12% sensor before the 55% one; grouping keeps that.
    expect(motion.items.map((d) => d.name)).toEqual(['Living Room Motion', 'Garage Multisensor']);
  });
});
