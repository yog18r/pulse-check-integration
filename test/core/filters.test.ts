import { describe, expect, it } from 'vitest';
import { parseSnapshot } from '../../src/card/snapshot';
import { filterDevices, NO_FILTERS } from '../../src/core/filters';
import { SNAPSHOT_PAYLOAD } from '../fixtures/snapshot';

const { devices } = parseSnapshot(SNAPSHOT_PAYLOAD);
const names = (list: typeof devices) => list.map((d) => d.name).sort();

describe('filterDevices', () => {
  it('shows everything without filters', () => {
    expect(filterDevices(devices, NO_FILTERS)).toBe(devices);
  });

  it('areas match names or ids, case-insensitively; devices without an area drop out', () => {
    const byName = filterDevices(devices, { ...NO_FILTERS, areas: ['bedroom', 'GARAGE'] });
    expect(names(byName)).toEqual([
      'Bedroom Temp & Humidity',
      'Garage Lights',
      'Garage Multisensor',
      'Window Sensor',
    ]);
    const byId = filterDevices(
      devices,
      { ...NO_FILTERS, areas: ['living_room'] },
      { living_room: 'Living Room' },
    );
    expect(names(byId)).toEqual(['Living Room Motion', 'Mr Roboto']);
    expect(names(filterDevices(devices, { ...NO_FILTERS, areas: ['Nowhere'] }))).toEqual([]);
  });

  it('integrations and device types narrow the list too, and combine', () => {
    expect(names(filterDevices(devices, { ...NO_FILTERS, integrations: ['ZHA'] }))).toEqual([
      'Bedroom Temp & Humidity',
      'Hallway Smoke Alarm',
    ]);
    expect(
      names(filterDevices(devices, { ...NO_FILTERS, device_types: ['lock', 'Motion sensors'] })),
    ).toEqual(['Front Door Lock', 'Garage Multisensor', 'Living Room Motion']);
    expect(
      names(
        filterDevices(devices, { areas: ['Garage'], integrations: ['zwave_js'], device_types: [] }),
      ),
    ).toEqual(['Garage Multisensor']);
  });
});
