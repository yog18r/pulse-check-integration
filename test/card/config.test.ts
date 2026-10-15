import { describe, expect, it } from 'vitest';
import { ConfigError, DEFAULT_CONFIG, resolveConfig } from '../../src/card/config';

describe('resolveConfig', () => {
  it('applies every default for an empty config', () => {
    expect(resolveConfig({ type: 'custom:pulse-check-card' })).toEqual(DEFAULT_CONFIG);
  });

  it('keeps valid user values', () => {
    const resolved = resolveConfig({
      title: 'Health',
      battery_warning: 40,
      battery_critical: 20,
      quiet_threshold_hours: 12,
      integration_thresholds: { zwave_js: 48 },
      device_overrides: [{ device_id: 'abc', quiet_threshold_hours: 72, battery_type: 'CR2032' }],
      exclude_integrations: ['mobile_app'],
      exclude_devices: ['xyz'],
      show_tabs: ['connectivity'],
      default_tab: 'connectivity',
    });
    expect(resolved.title).toBe('Health');
    expect(resolved.battery_warning).toBe(40);
    expect(resolved.integration_thresholds).toEqual({ zwave_js: 48 });
    expect(resolved.device_overrides[0]?.battery_type).toBe('CR2032');
    expect(resolved.show_tabs).toEqual(['connectivity']);
    expect(resolved.default_tab).toBe('connectivity');
  });

  it('rejects a non-object config', () => {
    expect(() => resolveConfig(null)).toThrow(ConfigError);
    expect(() => resolveConfig('nope')).toThrow(/YAML mapping/);
  });

  it('rejects non-numeric and out-of-range thresholds with helpful messages', () => {
    expect(() => resolveConfig({ battery_warning: '30' })).toThrow(/must be a number/);
    expect(() => resolveConfig({ battery_warning: 130 })).toThrow(/between 0 and 100/);
    expect(() => resolveConfig({ quiet_threshold_hours: 0 })).toThrow(/quiet_threshold_hours/);
  });

  it('rejects critical above warning', () => {
    expect(() => resolveConfig({ battery_warning: 10, battery_critical: 20 })).toThrow(
      /must not be higher/,
    );
  });

  it('validates integration_thresholds and device_overrides shapes', () => {
    expect(() => resolveConfig({ integration_thresholds: [1] })).toThrow(/mapping/);
    expect(() => resolveConfig({ integration_thresholds: { zha: 'soon' } })).toThrow(
      /integration_thresholds.zha/,
    );
    expect(() => resolveConfig({ device_overrides: 'abc' })).toThrow(/must be a list/);
    expect(() => resolveConfig({ device_overrides: [{}] })).toThrow(/device_overrides\[0\]/);
    expect(() =>
      resolveConfig({ device_overrides: [{ device_id: 'a', battery_type: 3 }] }),
    ).toThrow(/battery_type/);
  });

  it('validates tabs', () => {
    expect(() => resolveConfig({ show_tabs: [] })).toThrow(/non-empty/);
    expect(() => resolveConfig({ show_tabs: ['weather'] })).toThrow(/show_tabs/);
    expect(() => resolveConfig({ default_tab: 'weather' })).toThrow(/default_tab/);
    expect(() => resolveConfig({ show_tabs: ['batteries'], default_tab: 'connectivity' })).toThrow(
      /not in "show_tabs"/,
    );
  });

  it('falls back to the first shown tab when the default tab is hidden', () => {
    expect(resolveConfig({ show_tabs: ['connectivity'] }).default_tab).toBe('connectivity');
  });

  it('de-duplicates show_tabs', () => {
    expect(resolveConfig({ show_tabs: ['batteries', 'batteries'] }).show_tabs).toEqual([
      'batteries',
    ]);
  });
});
