import { describe, expect, it } from 'vitest';
import { ConfigError, DEFAULT_CONFIG, resolveConfig } from '../../src/card/config';

describe('resolveConfig', () => {
  it('applies every default for an empty config', () => {
    expect(resolveConfig({ type: 'custom:pulse-check-card' })).toEqual(DEFAULT_CONFIG);
    expect(DEFAULT_CONFIG.title).toBe(''); // no title row unless the user sets one
  });

  it('keeps valid user values', () => {
    const resolved = resolveConfig({
      title: 'Health',
      show_tabs: ['connectivity', 'actions'],
      default_tab: 'actions',
      max_rows: 'all',
      sort: 'replace_soon',
      group_by: 'area',
      areas: ['Kitchen', 'hallway'],
      integrations: ['zha'],
      device_types: ['lock'],
      problems_only: true,
      show_sparklines: false,
      sparkline_days: 30,
    });
    expect(resolved).toEqual({
      title: 'Health',
      show_tabs: ['connectivity', 'actions'],
      default_tab: 'actions',
      max_rows: 'all',
      sort: 'replace_soon',
      group_by: 'area',
      areas: ['Kitchen', 'hallway'],
      integrations: ['zha'],
      device_types: ['lock'],
      problems_only: true,
      show_sparklines: false,
      sparkline_days: 30,
    });
  });

  it('rejects a non-object config', () => {
    expect(() => resolveConfig(null)).toThrow(ConfigError);
    expect(() => resolveConfig('nope')).toThrow(/YAML mapping/);
  });

  it('rejects bad values with helpful messages', () => {
    expect(() => resolveConfig({ title: 3 })).toThrow(/"title" must be text/);
    expect(() => resolveConfig({ show_tabs: [] })).toThrow(/show_tabs/);
    expect(() => resolveConfig({ show_tabs: ['batteries'], default_tab: 'actions' })).toThrow(
      /not in "show_tabs"/,
    );
    expect(() => resolveConfig({ max_rows: 0 })).toThrow(/max_rows/);
    expect(() => resolveConfig({ sort: 'random' })).toThrow(/level, name, replace_soon/);
    expect(() => resolveConfig({ areas: 'Kitchen' })).toThrow(/"areas" must be a list/);
    expect(() => resolveConfig({ group_by: 'colour' })).toThrow(/none, area, integration/);
    expect(() => resolveConfig({ problems_only: 'yes' })).toThrow(/true or false/);
    expect(() => resolveConfig({ sparkline_days: 400 })).toThrow(/1 to 365/);
  });

  it('picks a sensible default tab when batteries is hidden', () => {
    expect(resolveConfig({ show_tabs: ['actions', 'connectivity'] }).default_tab).toBe('actions');
    expect(resolveConfig({ show_tabs: ['batteries', 'batteries'] }).show_tabs).toEqual([
      'batteries',
    ]);
  });

  it('still accepts the older battery_sort spelling', () => {
    expect(resolveConfig({ battery_sort: 'replace_soon' }).sort).toBe('replace_soon');
    expect(resolveConfig({ battery_sort: 'level', sort: 'name' }).sort).toBe('name');
  });

  it('ignores the analysis keys that used to exist', () => {
    // Old YAML keeps working; the integration owns these now.
    const resolved = resolveConfig({ battery_warning: 40, device_settings: [], exclude_areas: [] });
    expect(resolved).toEqual(DEFAULT_CONFIG);
  });
});
