/**
 * The two repeating-row sections of the visual editor:
 *
 *   integration_thresholds   { platform: hours }
 *   device_settings          [{ device_id, quiet_threshold_hours?, battery_type?,
 *                               battery_count?, rechargeable? }]
 *
 * When the editor has a `hass`, the platform and device pickers are
 * dropdowns of what actually exists in the instance. Without one (never in
 * HA, but possible in tests) they fall back to plain text inputs.
 *
 * React note: these are controlled components too. They never keep their
 * own copy of the rows; every edit calls `onChange` with the new value and
 * the parent re-renders them with it.
 */
import { useState } from 'react';
import type { DeviceSettings } from '../card/config';
import { BATTERY_TYPE_GROUPS, isKnownBatteryType, OTHER_BATTERY_TYPE } from '../core/batteryTypes';
import { listDevices, listIntegrations } from '../core/registryOptions';
import type { HassLike } from '../core/types';
import { DevicePicker } from './DevicePicker';

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
/* Per-device settings                                                      */
/* ------------------------------------------------------------------------ */

interface DeviceRowsProps {
  value: DeviceSettings[];
  hass: HassLike | undefined;
  onChange: (value: DeviceSettings[] | undefined) => void;
}

function parseOptionalNumber(text: string): number | undefined {
  if (text.trim() === '') return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

// `undefined` in a patch means "clear this field", which Partial<> does
// not allow under exactOptionalPropertyTypes, hence the explicit type.
interface SettingsPatch {
  device_id?: string;
  quiet_threshold_hours?: number | undefined;
  battery_type?: string | undefined;
  battery_count?: number | undefined;
  rechargeable?: boolean | undefined;
}

function applyPatch(row: DeviceSettings, patch: SettingsPatch): DeviceSettings {
  const next: DeviceSettings = { device_id: patch.device_id ?? row.device_id };
  const hours =
    'quiet_threshold_hours' in patch ? patch.quiet_threshold_hours : row.quiet_threshold_hours;
  if (hours !== undefined) next.quiet_threshold_hours = hours;
  const type = 'battery_type' in patch ? patch.battery_type : row.battery_type;
  if (type !== undefined && type !== '') next.battery_type = type;
  const count = 'battery_count' in patch ? patch.battery_count : row.battery_count;
  if (count !== undefined && count >= 1) next.battery_count = Math.floor(count);
  const rechargeable = 'rechargeable' in patch ? patch.rechargeable : row.rechargeable;
  if (rechargeable) next.rechargeable = true;
  return next;
}

/** Battery type dropdown with an "Other…" escape hatch into free text. */
function BatteryTypeField({
  value,
  onChange,
}: {
  value: string | undefined;
  onChange: (type: string | undefined) => void;
}) {
  const known = value !== undefined && isKnownBatteryType(value);
  const [other, setOther] = useState(value !== undefined && !known);
  const selectValue = other ? OTHER_BATTERY_TYPE : (value ?? '');

  return (
    <span className="typefield">
      <select
        aria-label="Battery type"
        value={selectValue}
        onChange={(e) => {
          const v = e.target.value;
          if (v === OTHER_BATTERY_TYPE) {
            setOther(true);
            onChange(undefined);
          } else {
            setOther(false);
            onChange(v === '' ? undefined : v);
          }
        }}
      >
        <option value="">Battery type…</option>
        {BATTERY_TYPE_GROUPS.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </optgroup>
        ))}
        <option value={OTHER_BATTERY_TYPE}>Other…</option>
      </select>
      {other && (
        <input
          type="text"
          aria-label="Other battery type"
          placeholder="e.g. 2CR5"
          value={value ?? ''}
          onChange={(e) => {
            onChange(e.target.value === '' ? undefined : e.target.value);
          }}
        />
      )}
    </span>
  );
}

export function DeviceSettingsRows({ value, hass, onChange }: DeviceRowsProps) {
  const devices = hass ? listDevices(hass) : [];
  const used = new Set(value.map((o) => o.device_id));
  const unused = devices.filter((d) => !used.has(d.id));

  function emit(next: DeviceSettings[]) {
    onChange(next.length > 0 ? next : undefined);
  }

  function update(index: number, patch: SettingsPatch) {
    emit(value.map((row, i) => (i === index ? applyPatch(row, patch) : row)));
  }

  return (
    <fieldset className="field">
      <legend>Per-device settings</legend>
      <p className="hint">
        Battery type and count feed the Actions tab; tick rechargeable for devices you charge rather
        than replace. Quiet hours overrides the threshold for that one device.
      </p>
      {value.map((row, index) => (
        <div key={index} className="settingsrow">
          <div className="settingsline">
            {devices.length > 0 ? (
              <DevicePicker
                value={row.device_id}
                options={devices}
                disabledIds={used}
                onChange={(id) => {
                  update(index, { device_id: id });
                }}
              />
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
            <button
              type="button"
              className="remove"
              aria-label="Remove device settings"
              onClick={() => {
                emit(value.filter((_, i) => i !== index));
              }}
            >
              ✕
            </button>
          </div>
          <div className="settingsline details">
            <BatteryTypeField
              value={row.battery_type}
              onChange={(type) => {
                update(index, { battery_type: type });
              }}
            />
            <label className="inline">
              <span>×</span>
              <input
                type="number"
                aria-label="Battery count"
                min={1}
                placeholder="1"
                value={row.battery_count ?? ''}
                onChange={(e) => {
                  update(index, { battery_count: parseOptionalNumber(e.target.value) });
                }}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={row.rechargeable === true}
                onChange={(e) => {
                  update(index, { rechargeable: e.target.checked });
                }}
              />
              Rechargeable
            </label>
            <label className="inline">
              <span>Quiet</span>
              <input
                type="number"
                aria-label="Quiet hours"
                min={0}
                placeholder="hours"
                value={row.quiet_threshold_hours ?? ''}
                onChange={(e) => {
                  update(index, { quiet_threshold_hours: parseOptionalNumber(e.target.value) });
                }}
              />
              <span>h</span>
            </label>
          </div>
        </div>
      ))}
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
