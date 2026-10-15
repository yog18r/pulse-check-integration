/**
 * The visual config editor's form.
 *
 * Edits the *raw* CardConfig (what ends up in the user's YAML), not the
 * resolved one, so that leaving a field blank means "use the default" and
 * the YAML stays minimal. Every change is reported upward immediately;
 * Home Assistant shows a live preview of the card as the user types.
 *
 * React note: these are "controlled inputs". The input's value comes from
 * props, and typing calls `onChange` to produce a new config object, which
 * flows back down as the new value. One-way data flow, no hidden state.
 */
import {
  BATTERY_SORTS,
  QUIET_SCOPES,
  resolveConfig,
  TAB_IDS,
  type BatterySort,
  type CardConfig,
  type QuietScope,
  type TabId,
} from '../card/config';

interface Props {
  config: CardConfig;
  onChange: (config: CardConfig) => void;
}

const TAB_LABELS: Record<TabId, string> = {
  batteries: 'Batteries',
  connectivity: 'Connectivity',
  shopping: 'Shopping list',
};

/** "a, b ,c" -> ["a", "b", "c"]; blank -> undefined so the key is dropped. */
function parseList(text: string): string[] | undefined {
  const items = text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  return items.length > 0 ? items : undefined;
}

function parseNumber(text: string): number | undefined {
  if (text.trim() === '') return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

export function EditorForm({ config, onChange }: Props) {
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

  const shownTabs: TabId[] = config.show_tabs ?? ['batteries', 'connectivity'];

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
          placeholder="Pulse Check"
          onChange={(e) => {
            set('title', e.target.value || undefined);
          }}
        />
      </label>

      <div className="grid2">
        <label className="field">
          <span>Battery warning (%)</span>
          <input
            type="number"
            min={0}
            max={100}
            value={config.battery_warning ?? ''}
            placeholder="30"
            onChange={(e) => {
              set('battery_warning', parseNumber(e.target.value));
            }}
          />
        </label>
        <label className="field">
          <span>Battery critical (%)</span>
          <input
            type="number"
            min={0}
            max={100}
            value={config.battery_critical ?? ''}
            placeholder="15"
            onChange={(e) => {
              set('battery_critical', parseNumber(e.target.value));
            }}
          />
        </label>
      </div>

      <div className="grid2">
        <label className="field">
          <span>Quiet after (hours)</span>
          <input
            type="number"
            min={0}
            value={config.quiet_threshold_hours ?? ''}
            placeholder="24"
            onChange={(e) => {
              set('quiet_threshold_hours', parseNumber(e.target.value));
            }}
          />
        </label>
        <label className="field">
          <span>Quiet applies to</span>
          <select
            value={config.quiet_scope ?? 'battery'}
            onChange={(e) => {
              const v = e.target.value as QuietScope;
              set('quiet_scope', v === 'battery' ? undefined : v);
            }}
          >
            {QUIET_SCOPES.map((s) => (
              <option key={s} value={s}>
                {s === 'battery' ? 'Battery devices only' : 'All devices'}
              </option>
            ))}
          </select>
        </label>
      </div>

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
        <span>Exclude integrations</span>
        <input
          type="text"
          value={(config.exclude_integrations ?? []).join(', ')}
          placeholder="mobile_app, music_assistant"
          onChange={(e) => {
            set('exclude_integrations', parseList(e.target.value));
          }}
        />
      </label>

      <label className="field">
        <span>Exclude devices (ids)</span>
        <input
          type="text"
          value={(config.exclude_devices ?? []).join(', ')}
          placeholder="device id, device id"
          onChange={(e) => {
            set('exclude_devices', parseList(e.target.value));
          }}
        />
      </label>

      <label className="field">
        <span>Exclude entities</span>
        <input
          type="text"
          value={(config.exclude_entities ?? []).join(', ')}
          placeholder="sensor.inverter_min_soc"
          onChange={(e) => {
            set('exclude_entities', parseList(e.target.value));
          }}
        />
      </label>

      <p className="note">
        Per-integration thresholds, per-device overrides and battery types are set in the YAML
        editor (<code>integration_thresholds</code>, <code>device_overrides</code>).
      </p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
