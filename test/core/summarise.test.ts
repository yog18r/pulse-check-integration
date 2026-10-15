import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../../src/card/config';
import { analyseDevices } from '../../src/core/analyse';
import { breakdown, headline, summarise } from '../../src/core/summarise';
import { FIXED_NOW, hass } from '../fixtures/hass';

describe('summarise', () => {
  it('counts the fixture correctly', () => {
    const devices = analyseDevices(hass, DEFAULT_CONFIG, { now: FIXED_NOW });
    const s = summarise(devices, DEFAULT_CONFIG);
    // critical: z2m motion 12%, lock offline, smoke alarm binary low, orphan 9%
    expect(s.critical).toBe(4);
    // warning: zha temp (28% + quiet), zwave multi (quiet)
    expect(s.warning).toBe(2);
    expect(s.attention).toBe(6);
    expect(s.offline).toBe(1);
    expect(s.quiet).toBe(2);
    expect(s.batteryDevices).toBe(10);
    // low: smoke alarm (binary), orphan 9%, motion 12%, zha 28%
    expect(s.lowBatteries).toBe(4);
  });
});

describe('headline and breakdown', () => {
  const base = {
    critical: 0,
    warning: 0,
    batteryDevices: 0,
    lowBatteries: 0,
    offline: 0,
    quiet: 0,
  };

  it('celebrates when nothing needs attention', () => {
    expect(headline({ ...base, attention: 0 })).toMatch(/🎉/);
    expect(breakdown({ ...base, attention: 0 })).toBe('');
  });

  it('uses singular and plural correctly', () => {
    expect(headline({ ...base, attention: 1 })).toBe('⚠️ 1 device needs attention');
    expect(headline({ ...base, attention: 3 })).toBe('⚠️ 3 devices need attention');
    expect(breakdown({ ...base, attention: 1, lowBatteries: 1 })).toBe('1 low battery');
    expect(breakdown({ ...base, attention: 6, lowBatteries: 4, offline: 1, quiet: 2 })).toBe(
      '4 low batteries · 1 offline · 2 quiet',
    );
  });
});
