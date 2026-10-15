import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../../src/card/config';
import { analyseDevices } from '../../src/core/analyse';
import { deviceTypeLabel } from '../../src/core/deviceType';
import { FIXED_NOW, hass } from '../fixtures/hass';

describe('classifyDevice', () => {
  const byName = new Map(
    analyseDevices(hass, DEFAULT_CONFIG, { now: FIXED_NOW }).map((d) => [d.name, d.deviceType]),
  );

  it('classifies the fixture devices by their primary entities', () => {
    expect(byName.get('Front Door Sensor')).toBe('contact');
    expect(byName.get('Living Room Motion')).toBe('motion');
    expect(byName.get('Bedroom Temp & Humidity')).toBe('climate');
    expect(byName.get('Garage Multisensor')).toBe('motion'); // motion beats temperature
    expect(byName.get('Front Door Lock')).toBe('lock');
    expect(byName.get('Office Plug')).toBe('switch');
    expect(byName.get('Pixel 9')).toBe('phone');
    expect(byName.get('Dog Collar Tracker')).toBe('phone'); // a tracker with a battery
    expect(byName.get('Mr Roboto')).toBe('vacuum');
    expect(byName.get('Garage Lights')).toBe('light');
    expect(byName.get('Plant Monitor')).toBe('other');
    expect(byName.get('TV Remote Battery')).toBe('other');
  });

  it('has a label for every type', () => {
    expect(deviceTypeLabel('cover')).toBe('Covers and blinds');
    expect(deviceTypeLabel('other')).toBe('Other');
  });
});
