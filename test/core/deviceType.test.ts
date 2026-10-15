import { describe, expect, it } from 'vitest';
import { DEVICE_TYPES, deviceTypeLabel, isDeviceType } from '../../src/core/deviceType';

describe('device types', () => {
  it('has a label for every type the integration can send', () => {
    for (const type of DEVICE_TYPES) expect(deviceTypeLabel(type)).not.toBe('');
    expect(deviceTypeLabel('cover')).toBe('Covers and blinds');
    expect(deviceTypeLabel('other')).toBe('Other');
  });

  it('recognises known types and nothing else', () => {
    expect(isDeviceType('lock')).toBe(true);
    expect(isDeviceType('spaceship')).toBe(false);
    expect(isDeviceType(42)).toBe(false);
  });
});
