import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG, type ResolvedConfig } from '../../src/card/config';
import {
  batterySeverity,
  connectivitySeverity,
  extrasSeverity,
  resolveQuietThreshold,
  worstSeverity,
} from '../../src/core/thresholds';

const config: ResolvedConfig = {
  ...DEFAULT_CONFIG,
  integration_thresholds: { zwave_js: 48 },
  device_overrides: [{ device_id: 'special', quiet_threshold_hours: 72 }],
};

describe('resolveQuietThreshold', () => {
  it('uses the global default when nothing more specific matches', () => {
    expect(resolveQuietThreshold(config, 'zha', 'dev1')).toBe(24);
  });

  it('prefers the integration override over the global default', () => {
    expect(resolveQuietThreshold(config, 'zwave_js', 'dev1')).toBe(48);
  });

  it('prefers the device override over everything', () => {
    expect(resolveQuietThreshold(config, 'zwave_js', 'special')).toBe(72);
  });
});

describe('batterySeverity', () => {
  const reading = (level: number) => ({
    level,
    isLow: false,
    source: 'sensor' as const,
    entityId: 'sensor.x',
  });

  it('is ok with no battery', () => {
    expect(batterySeverity(undefined, config)).toBe('ok');
  });

  it('uses inclusive thresholds (at the number counts)', () => {
    expect(batterySeverity(reading(15), config)).toBe('critical');
    expect(batterySeverity(reading(16), config)).toBe('warning');
    expect(batterySeverity(reading(30), config)).toBe('warning');
    expect(batterySeverity(reading(31), config)).toBe('ok');
  });

  it('never flags a charging device, whatever its level', () => {
    expect(batterySeverity({ ...reading(5), isCharging: true }, config)).toBe('ok');
    expect(
      batterySeverity({ isLow: true, isCharging: true, source: 'binary', entityId: 'b' }, config),
    ).toBe('ok');
  });

  it('treats a binary "low" as critical and binary "not low" as ok', () => {
    expect(batterySeverity({ isLow: true, source: 'binary', entityId: 'b' }, config)).toBe(
      'critical',
    );
    expect(batterySeverity({ isLow: false, source: 'binary', entityId: 'b' }, config)).toBe('ok');
  });
});

describe('connectivitySeverity / extrasSeverity / worstSeverity', () => {
  it('offline is critical, quiet is warning', () => {
    expect(connectivitySeverity(true, true)).toBe('critical');
    expect(connectivitySeverity(false, true)).toBe('warning');
    expect(connectivitySeverity(false, false)).toBe('ok');
  });

  it('extras can escalate', () => {
    expect(extrasSeverity([])).toBe('ok');
    expect(extrasSeverity([{ label: 'Node', value: 'asleep' }])).toBe('ok');
    expect(extrasSeverity([{ label: 'Node', value: 'dead', severity: 'critical' }])).toBe(
      'critical',
    );
  });

  it('worstSeverity picks the highest rank', () => {
    expect(worstSeverity()).toBe('ok');
    expect(worstSeverity('ok', 'warning', 'ok')).toBe('warning');
    expect(worstSeverity('warning', 'critical')).toBe('critical');
  });
});
