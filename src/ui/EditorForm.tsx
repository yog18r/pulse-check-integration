/**
 * The visual config editor's form.
 *
 * Two halves:
 *  - Presentation options edit the *raw* CardConfig (what ends up in the
 *    user's YAML), so leaving a field blank means "use the default" and the
 *    YAML stays minimal. Every change is reported upward immediately; Home
 *    Assistant shows a live preview of the card as the user types.
 *  - Per-device settings (DeviceSettingsPanel) are saved by the integration
 *    through its services and never touch the YAML.
 *
 * Thresholds, quiet rules and filters are not here at all: they live in
 * the integration's own Configure dialog.
 *
 * React note: these are "controlled inputs". The input's value comes from
 * props, and typing calls `onChange` to produce a new config object, which
 * flows back down as the new value. One-way data flow, no hidden state.
 */
import {
  BATTERY_SORTS,
  DEFAULT_CONFIG,
  resolveConfig,
  TAB_IDS,
  type BatterySort,
  type CardConfig,
  type TabId,
} from '../card/config';
import { GROUP_BYS, type GroupBy } from '../core/grouping';
import type { HassLike, HassBox } from '../core/types';
import { DeviceSettingsPanel } from './DeviceSettingsPanel';

interface Props {
  config: CardConfig;
  onChange: (config: CardConfig) => void;
  /** Lets the device picker offer real device names. */
  hass?: HassLike | undefined;
  hassBox: HassBox;
}

const TAB_LABELS: Record<TabId, string> = {
  batteries: 'Batteries',
  connectivity: 'Connectivity',
  actions: 'Actions',
};

const GROUP_LABELS: Record<GroupBy, string> = {
  none: 'No grouping',
  area: 'Area',
  integration: 'Integration',
  device_type: 'Device type',
};

function parseNumber(text: string): number | undefined {
  if (text.trim() === '') return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

export function EditorForm({ config, onChange, hass, hassBox }: Props) {
  /** Set one key, dropping it entirely when the value is undefined. */
  function set<K extends keyof CardConfig>(key: K, value: CardConfig[K] | undefined) {
    // Rebuild without the key, then add it back only if it has a value, so
    // cleared fields disappear from the YAML instead of lingering as null.
    const entries = Object.entries(config).filter(([k]) => k !== key);
    if (value !== undefined) entries.push([key, value]);
    onChange(Object.fromEntries(entries));
  }

  // Validate exactly like the card does, so the editor can warn early.
  let error: string | null = null;
  try {
    resolveConfig(config);
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
  }

  const shownTabs: TabId[] = config.show_tabs ?? DEFAULT_CONFIG.show_tabs;

  function toggleTab(tab: TabId, on: boolean) {
    const next = TAB_IDS.filter((t) => (t === tab ? on : shownTabs.includes(t)));
    set('show_tabs', next.length > 0 ? next : undefined);
    if (config.default_tab && !next.includes(config.default_tab)) set('default_tab', undefined);
  }

  return (
    <form
      className="editor"
      onSubmit={(e) => {
        e.preventDefault();
      }}
    >
      <label className="field">
        <span>Title</span>
        <input
          type="text"
          value={config.title ?? ''}
          placeholder="No title"
          onChange={(e) => {
            set('title', e.target.value === '' ? undefined : e.target.value);
          }}
        />
      </label>

      <fieldset className="field">
        <legend>Tabs</legend>
        <div className="checks">
          {TAB_IDS.map((tab) => (
            <label key={tab} className="check">
              <input
                type="checkbox"
                checked={shownTabs.includes(tab)}
                onChange={(e) => {
                  toggleTab(tab, e.target.checked);
                }}
              />
              {TAB_LABELS[tab]}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid2">
        <label className="field">
          <span>Default tab</span>
          <select
            value={config.default_tab ?? shownTabs[0] ?? 'batteries'}
            onChange={(e) => {
              set('default_tab', e.target.value as TabId);
            }}
          >
            {shownTabs.map((tab) => (
              <option key={tab} value={tab}>
                {TAB_LABELS[tab]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Group by</span>
          <select
            value={config.group_by ?? 'none'}
            onChange={(e) => {
              const v = e.target.value as GroupBy;
              set('group_by', v === 'none' ? undefined : v);
            }}
          >
            {GROUP_BYS.map((g) => (
              <option key={g} value={g}>
                {GROUP_LABELS[g]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid2">
        <label className="field">
          <span>Battery order</span>
          <select
            value={config.battery_sort ?? 'level'}
            onChange={(e) => {
              const v = e.target.value as BatterySort;
              set('battery_sort', v === 'level' ? undefined : v);
            }}
          >
            {BATTERY_SORTS.map((s) => (
              <option key={s} value={s}>
                {s === 'level' ? 'Lowest level first' : 'Soonest to run out first'}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Rows per tab</span>
          <input
            type="number"
            min={1}
            value={typeof config.max_rows === 'number' ? config.max_rows : ''}
            placeholder="12"
            disabled={config.max_rows === 'all'}
            onChange={(e) => {
              const n = parseNumber(e.target.value);
              set('max_rows', n !== undefined && n >= 1 ? Math.floor(n) : undefined);
            }}
          />
        </label>
      </div>

      <div className="checks">
        <label className="check">
          <input
            type="checkbox"
            checked={config.max_rows === 'all'}
            onChange={(e) => {
              set('max_rows', e.target.checked ? 'all' : undefined);
            }}
          />
          Show all rows
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={config.show_sparklines ?? true}
            onChange={(e) => {
              set('show_sparklines', e.target.checked ? undefined : false);
            }}
          />
          Trend sparklines
        </label>
        <label className="inline">
          <span>over</span>
          <input
            type="number"
            aria-label="Sparkline days"
            min={1}
            max={365}
            placeholder="14"
            value={config.sparkline_days ?? ''}
            onChange={(e) => {
              const n = parseNumber(e.target.value);
              set(
                'sparkline_days',
                n !== undefined && n >= 1 ? Math.min(365, Math.floor(n)) : undefined,
              );
            }}
          />
          <span>days</span>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={config.problems_only ?? false}
            onChange={(e) => {
              set('problems_only', e.target.checked ? true : undefined);
            }}
          />
          Batteries tab: problems only
        </label>
      </div>

      <p className="note">
        Thresholds, quiet rules, filters and notifications are set in the integration: Settings →
        Devices &amp; services → Pulse Check → Configure.
      </p>

      <DeviceSettingsPanel hass={hass} hassBox={hassBox} />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
