/**
 * The two repeating-row sections of the visual editor:
 *
 *   integration_thresholds   { platform: hours }
 *   device_overrides         [{ device_id, quiet_threshold_hours?, battery_type? }]
 *
 * When the editor has a `hass`, the platform and device pickers are
 * dropdowns of what actually exists in the instance. Without one (never in
 * HA, but possible in tests) they fall back to plain text inputs.
 *
 * React note: these are controlled components too. They never keep their
 * own copy of the rows; every edit calls `onChange` with the new value and
 * the parent re-renders them with it.
 */
import type { DeviceOverride } from '../card/config';
import { deviceLabel, listDevices, listIntegrations } from '../core/registryOptions';
import type { HassLike } from '../core/types';

/* ------------------------------------------------------------------------ */
/* Integration thresholds                                                   */
/* ------------------------------------------------------------------------ */

interface IntegrationRowsProps {
  value: Record<string, number>;
  defaultHours: number;
  hass: HassLike | undefined;
  onChange: (value: Record<string, number> | undefined) => void;
}

export function IntegrationThresholdRows({
  value,
  defaultHours,
  hass,
  onChange,
}: IntegrationRowsProps) {
  const rows = Object.entries(value);
  const known = hass ? listIntegrations(hass).map((o) => o.id) : [];
  const used = new Set(rows.map(([platform]) => platform));
  const unused = known.filter((id) => !used.has(id));

  function emit(next: [string, number][]) {
    onChange(next.length > 0 ? Object.fromEntries(next) : undefined);
  }

  function update(index: number, platform: string, hours: number) {
    emit(rows.map((row, i) => (i === index ? [platform, hours] : row)));
  }

  return (
    <fieldset className="field">
      <legend>Per-integration quiet thresholds</legend>
      {rows.length === 0 && <p className="hint">None. The global threshold applies everywhere.</p>}
      {rows.map(([platform, hours], index) => (
        <div key={index} className="listrow">
          {known.length > 0 ? (
            <select
              aria-label="Integration"
              value={platform}
              onChange={(e) => {
                update(index, e.target.value, hours);
              }}
            >
              {!known.includes(platform) && <option value={platform}>{platform}</option>}
              {known.map((id) => (
                <option key={id} value={id} disabled={id !== platform && used.has(id)}>
                  {id}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              aria-label="Integration"
              value={platform}
              placeholder="zwave_js"
              onChange={(e) => {
                update(index, e.target.value, hours);
              }}
            />
          )}
          <input
            type="number"
            aria-label="Hours"
            min={0}
            value={hours}
            onChange={(e) => {
              update(index, platform, Number(e.target.value));
            }}
          />
          <span className="unit">h</span>
          <button
            type="button"
            className="remove"
            aria-label={`Remove ${platform}`}
            onClick={() => {
              emit(rows.filter((_, i) => i !== index));
            }}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        className="add"
        disabled={known.length > 0 && unused.length === 0}
        onClick={() => {
          emit([...rows, [unused[0] ?? '', defaultHours]]);
        }}
      >
        + Add integration
      </button>
    </fieldset>
  );
}

/* ------------------------------------------------------------------------ */
/* Device overrides                                                         */
/* ------------------------------------------------------------------------ */

interface DeviceRowsProps {
  value: DeviceOverride[];
  hass: HassLike | undefined;
  onChange: (value: DeviceOverride[] | undefined) => void;
}

function parseOptionalNumber(text: string): number | undefined {
  if (text.trim() === '') return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

export function DeviceOverrideRows({ value, hass, onChange }: DeviceRowsProps) {
  const devices = hass ? listDevices(hass) : [];
  const used = new Set(value.map((o) => o.device_id));
  const unused = devices.filter((d) => !used.has(d.id));

  function emit(next: DeviceOverride[]) {
    onChange(next.length > 0 ? next : undefined);
  }

  // `undefined` in a patch means "clear this field", which Partial<> does
  // not allow under exactOptionalPropertyTypes, hence the explicit type.
  interface OverridePatch {
    device_id?: string;
    quiet_threshold_hours?: number | undefined;
    battery_type?: string | undefined;
  }

  function update(index: number, patch: OverridePatch) {
    emit(
      value.map((row, i) => {
        if (i !== index) return row;
        const next: DeviceOverride = { device_id: patch.device_id ?? row.device_id };
        const hours =
          'quiet_threshold_hours' in patch
            ? patch.quiet_threshold_hours
            : row.quiet_threshold_hours;
        if (hours !== undefined) next.quiet_threshold_hours = hours;
        const type = 'battery_type' in patch ? patch.battery_type : row.battery_type;
        if (type !== undefined && type !== '') next.battery_type = type;
        return next;
      }),
    );
  }

  return (
    <fieldset className="field">
      <legend>Per-device overrides</legend>
      {value.length === 0 && (
        <p className="hint">None. Add one to set a quiet threshold or battery type for a device.</p>
      )}
      {value.map((row, index) => {
        const knownDevice = devices.some((d) => d.id === row.device_id);
        return (
          <div key={index} className="listrow device">
            {devices.length > 0 ? (
              <select
                aria-label="Device"
                value={row.device_id}
                onChange={(e) => {
                  update(index, { device_id: e.target.value });
                }}
              >
                {!knownDevice && (
                  <option value={row.device_id}>{row.device_id || 'Choose a device'}</option>
                )}
                {devices.map((d) => (
                  <option
                    key={d.id}
                    value={d.id}
                    disabled={d.id !== row.device_id && used.has(d.id)}
                  >
                    {deviceLabel(d)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                aria-label="Device id"
                value={row.device_id}
                placeholder="device id"
                onChange={(e) => {
                  update(index, { device_id: e.target.value });
                }}
              />
            )}
            <input
              type="number"
              aria-label="Quiet hours"
              min={0}
              placeholder="quiet h"
              value={row.quiet_threshold_hours ?? ''}
              onChange={(e) => {
                update(index, { quiet_threshold_hours: parseOptionalNumber(e.target.value) });
              }}
            />
            <input
              type="text"
              aria-label="Battery type"
              placeholder="e.g. CR2032"
              value={row.battery_type ?? ''}
              onChange={(e) => {
                update(index, { battery_type: e.target.value });
              }}
            />
            <button
              type="button"
              className="remove"
              aria-label="Remove device override"
              onClick={() => {
                emit(value.filter((_, i) => i !== index));
              }}
            >
              ✕
            </button>
          </div>
        );
      })}
      <button
        type="button"
        className="add"
        disabled={devices.length > 0 && unused.length === 0}
        onClick={() => {
          emit([...value, { device_id: unused[0]?.id ?? '' }]);
        }}
      >
        + Add device
      </button>
    </fieldset>
  );
}

/* ------------------------------------------------------------------------ */
/* Checkbox groups (areas, integrations)                                    */
/* ------------------------------------------------------------------------ */

export interface CheckOption {
  id: string;
  label: string;
}

interface CheckboxGroupProps {
  legend: string;
  hint?: string;
  options: CheckOption[];
  /** Currently selected ids (or names; matching is case-insensitive). */
  value: string[];
  onChange: (value: string[] | undefined) => void;
}

/**
 * A list of checkboxes backed by a string[] config value. Values the user
 * typed in YAML that aren't among the options are kept as extra checked
 * entries, so switching to the visual editor never silently drops them.
 */
export function CheckboxGroup({ legend, hint, options, value, onChange }: CheckboxGroupProps) {
  const lower = (s: string) => s.trim().toLowerCase();
  const selected = new Set(value.map(lower));
  const known = new Set(options.map((o) => lower(o.id)).concat(options.map((o) => lower(o.label))));
  const extras = value.filter((v) => !known.has(lower(v)));

  function toggle(id: string, on: boolean) {
    const next = value.filter((v) => lower(v) !== lower(id));
    if (on) next.push(id);
    onChange(next.length > 0 ? next : undefined);
  }

  return (
    <fieldset className="field">
      <legend>{legend}</legend>
      {hint && <p className="hint">{hint}</p>}
      <div className="checks">
        {options.map((o) => (
          <label key={o.id} className="check">
            <input
              type="checkbox"
              checked={selected.has(lower(o.id)) || selected.has(lower(o.label))}
              onChange={(e) => {
                toggle(o.id, e.target.checked);
              }}
            />
            {o.label}
          </label>
        ))}
        {extras.map((v) => (
          <label key={`extra:${v}`} className="check" title="From YAML; not found in this instance">
            <input
              type="checkbox"
              checked
              onChange={() => {
                toggle(v, false);
              }}
            />
            {v} ?
          </label>
        ))}
      </div>
    </fieldset>
  );
}
