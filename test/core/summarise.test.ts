import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../../src/card/config';
import { analyseDevices } from '../../src/core/analyse';
import { headline, summarise } from '../../src/core/summarise';
import { FIXED_NOW, hass } from '../fixtures/hass';

describe('summarise', () => {
  it('counts the fixture correctly', () => {
    const devices = analyseDevices(hass, DEFAULT_CONFIG, { now: FIXED_NOW });
    const s = summarise(devices);
    // critical: z2m motion 12%, lock offline, smoke alarm binary low, orphan 9%
    expect(s.critical).toBe(4);
    // warning: zha temp (28% + quiet), zwave multi (quiet), shelly plug (quiet)
    expect(s.warning).toBe(3);
    expect(s.attention).toBe(7);
    expect(s.offline).toBe(1);
    expect(s.quiet).toBe(3);
    expect(s.batteryDevices).toBe(10);
  });
});

describe('headline', () => {
  const base = { critical: 0, warning: 0, batteryDevices: 0, offline: 0, quiet: 0 };

  it('celebrates when nothing needs attention', () => {
    expect(headline({ ...base, attention: 0 })).toMatch(/🎉/);
  });

  it('uses singular and plural correctly', () => {
    expect(headline({ ...base, attention: 1 })).toBe('⚠️ 1 device needs attention');
    expect(headline({ ...base, attention: 3 })).toBe('⚠️ 3 devices need attention');
  });
});
