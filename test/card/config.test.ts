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
    expect(resolved.device_settings[0]?.battery_type).toBe('CR2032');
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

  it('validates exclude_entities and quiet_scope', () => {
    expect(resolveConfig({ exclude_entities: ['sensor.a'] }).exclude_entities).toEqual([
      'sensor.a',
    ]);
    expect(() => resolveConfig({ exclude_entities: 'sensor.a' })).toThrow(/list of strings/);
    expect(resolveConfig({}).quiet_scope).toBe('battery');
    expect(resolveConfig({ quiet_scope: 'all' }).quiet_scope).toBe('all');
    expect(() => resolveConfig({ quiet_scope: 'everything' })).toThrow(/quiet_scope/);
  });

  it('validates battery_sort', () => {
    expect(resolveConfig({}).battery_sort).toBe('level');
    expect(resolveConfig({ battery_sort: 'replace_soon' }).battery_sort).toBe('replace_soon');
    expect(() => resolveConfig({ battery_sort: 'random' })).toThrow(/battery_sort/);
  });

  it('accepts the actions tab, and "shopping" as its old name', () => {
    const resolved = resolveConfig({ show_tabs: ['batteries', 'actions'], default_tab: 'actions' });
    expect(resolved.show_tabs).toEqual(['batteries', 'actions']);
    expect(resolved.default_tab).toBe('actions');
    const legacy = resolveConfig({ show_tabs: ['shopping'], default_tab: 'shopping' });
    expect(legacy.show_tabs).toEqual(['actions']);
    expect(legacy.default_tab).toBe('actions');
  });

  it('parses device_settings with count and rechargeable, merging legacy device_overrides', () => {
    const resolved = resolveConfig({
      device_overrides: [
        { device_id: 'old', battery_type: 'AA' },
        { device_id: 'both', battery_type: 'AAA' },
      ],
      device_settings: [
        { device_id: 'both', battery_type: 'CR2032', battery_count: 2, rechargeable: false },
        { device_id: 'blind', rechargeable: true, battery_type: 'Built-in rechargeable' },
      ],
    });
    expect(resolved.device_settings).toEqual([
      { device_id: 'old', battery_type: 'AA' },
      { device_id: 'both', battery_type: 'CR2032', battery_count: 2, rechargeable: false },
      { device_id: 'blind', rechargeable: true, battery_type: 'Built-in rechargeable' },
    ]);
    expect(() =>
      resolveConfig({ device_settings: [{ device_id: 'a', battery_count: 0 }] }),
    ).toThrow(/battery_count/);
    expect(() =>
      resolveConfig({ device_settings: [{ device_id: 'a', rechargeable: 'yes' }] }),
    ).toThrow(/rechargeable/);
  });

  it('validates max_rows, sparklines and the new filters', () => {
    expect(resolveConfig({}).max_rows).toBe(12);
    expect(resolveConfig({ max_rows: 'all' }).max_rows).toBe('all');
    expect(resolveConfig({ max_rows: 30 }).max_rows).toBe(30);
    expect(() => resolveConfig({ max_rows: 0 })).toThrow(/max_rows/);
    expect(() => resolveConfig({ max_rows: 2.5 })).toThrow(/max_rows/);
    expect(() => resolveConfig({ max_rows: 'lots' })).toThrow(/max_rows/);
    expect(resolveConfig({}).show_sparklines).toBe(true);
    expect(resolveConfig({ show_sparklines: false }).show_sparklines).toBe(false);
    expect(() => resolveConfig({ show_sparklines: 'yes' })).toThrow(/show_sparklines/);
    expect(resolveConfig({ include_areas: ['Office'] }).include_areas).toEqual(['Office']);
    expect(() => resolveConfig({ exclude_areas: 'Office' })).toThrow(/exclude_areas/);
    expect(() => resolveConfig({ include_integrations: [1] })).toThrow(/include_integrations/);
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
