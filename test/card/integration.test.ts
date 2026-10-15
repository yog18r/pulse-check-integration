import { describe, expect, it, vi } from 'vitest';
import {
  callPulseCheck,
  integrationFingerprint,
  parseDevice,
  readIntegration,
} from '../../src/card/integration';
import type { HassLike } from '../../src/core/types';
import golden from '../fixtures/golden.json';
import { hass as fixtureHass } from '../fixtures/hass';

/** A hass whose only interesting entity is the integration's sensor. */
function hassWithSensor(attributes: Record<string, unknown>, state = '4'): HassLike {
  return {
    ...fixtureHass,
    states: {
      ...fixtureHass.states,
      'sensor.pulse_check_attention': {
        entity_id: 'sensor.pulse_check_attention',
        state,
        attributes,
        last_changed: '2026-10-15T10:00:00.000Z',
        last_updated: '2026-10-15T10:00:00.000Z',
      },
    },
  };
}

const goldenDevices = golden.cases[0]!.devices;

describe('parseDevice', () => {
  it('turns the golden JSON back into DeviceHealth, dates included', () => {
    const raw = goldenDevices.find((d) => d.name === 'Living Room Motion')!;
    const device = parseDevice({
      ...raw,
      daysLeft: 6.1,
      unusual: 'draining 3× faster than usual',
    })!;
    expect(device.deviceId).toBe('dev_z2m_motion');
    expect(device.severity).toBe('critical');
    expect(device.deviceType).toBe('motion');
    expect(device.battery).toEqual({
      level: 12,
      isLow: false,
      source: 'sensor',
      entityId: 'sensor.living_room_motion_battery',
    });
    expect(device.lastHeard?.toISOString()).toBe('2026-10-15T09:20:00.000Z');
    expect(device.extras).toEqual([{ label: 'LQI', value: '45', severity: 'ok' }]);
    expect(device.daysLeft).toBe(6.1);
    expect(device.unusual).toBe('draining 3× faster than usual');
  });

  it('rejects entries that are not devices and tolerates odd fields', () => {
    expect(parseDevice(null)).toBeUndefined();
    expect(parseDevice({ name: 'x' })).toBeUndefined();
    expect(
      parseDevice({ deviceId: 'a', name: 'A', integration: 'zha', severity: 'bad' }),
    ).toBeUndefined();
    const minimal = parseDevice({ deviceId: 'a', name: 'A', integration: 'zha', severity: 'ok' })!;
    expect(minimal.deviceType).toBe('other');
    expect(minimal.extras).toEqual([]);
    expect(minimal.entityIds).toEqual([]);
    expect(minimal.quietThresholdHours).toBe(24);
  });
});

describe('readIntegration', () => {
  it('reads every device from the sensor attribute', () => {
    const source = readIntegration(
      hassWithSensor({ devices: goldenDevices, computed_at: '2026-10-15T10:00:00.000Z' }),
      'sensor.pulse_check_attention',
    )!;
    expect(source.devices).toHaveLength(goldenDevices.length);
    expect(source.computedAt?.toISOString()).toBe('2026-10-15T10:00:00.000Z');
  });

  it('is undefined when the sensor is missing or unavailable', () => {
    expect(readIntegration(fixtureHass, 'sensor.pulse_check_attention')).toBeUndefined();
    expect(
      readIntegration(
        hassWithSensor({ devices: [] }, 'unavailable'),
        'sensor.pulse_check_attention',
      ),
    ).toBeUndefined();
  });

  it('fingerprints the sensor only', () => {
    const h = hassWithSensor({ devices: [] });
    expect(integrationFingerprint(h, 'sensor.pulse_check_attention')).toBe(
      '4\u00012026-10-15T10:00:00.000Z',
    );
    expect(integrationFingerprint(fixtureHass, 'sensor.pulse_check_attention')).toBe('');
  });
});

describe('callPulseCheck', () => {
  it('calls the integration service when hass can', async () => {
    const callService = vi.fn().mockResolvedValue(undefined);
    await callPulseCheck({ ...fixtureHass, callService }, 'snooze', { device_id: 'x', days: 7 });
    expect(callService).toHaveBeenCalledWith('pulse_check', 'snooze', { device_id: 'x', days: 7 });
    await expect(
      callPulseCheck(fixtureHass, 'unsnooze', { device_id: 'x' }),
    ).resolves.toBeUndefined();
  });
});
