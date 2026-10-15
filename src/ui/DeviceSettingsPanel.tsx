/**
 * Per-device settings, edited in the card editor but stored by the
 * integration.
 *
 * Pick a device (any device in the house, or a battery sensor that has no
 * device), then change its display name, area, battery type and count,
 * rechargeable, quiet hours or notification policy. Every change is sent
 * straight to `pulse_check.set_device_settings`; the next snapshot from
 * the subscription shows it saved. Nothing lands in the card's YAML, so
 * every card and every notification sees the same settings.
 *
 * React note: text fields keep a local draft while typing and save on
 * blur (or Enter), so each keystroke is not a service call. Selects and
 * checkboxes save immediately.
 */
import { useMemo, useState } from 'react';
import {
  callPulseCheck,
  NOTIFY_POLICIES,
  type DeviceSettings,
  type NotifyPolicy,
} from '../card/snapshot';
import { BATTERY_TYPE_GROUPS, isKnownBatteryType, OTHER_BATTERY_TYPE } from '../core/batteryTypes';
import {
  deviceLabel,
  listDevices,
  listOrphanBatteryEntities,
  type DeviceOption,
} from '../core/registryOptions';
import type { HassLike, HassBox } from '../core/types';
import { DevicePicker } from './DevicePicker';
import { useSnapshot } from './useSnapshot';

interface Props {
  /** For the device picker and area list (registries). */
  hass: HassLike | undefined;
  /** For the subscription and service calls. */
  hassBox: HassBox;
}

const POLICY_LABELS: Record<NotifyPolicy, string> = {
  instant: 'Instantly, with reminders',
  daily: 'In the daily digest',
  weekly: 'In the weekly digest',
  none: 'Never',
};

/**
 * A text or number field that saves when the user leaves it. The parent
 * keys each one by its saved value, so a save (or a new device) remounts
 * it with a fresh draft instead of syncing state in an effect.
 */
function DraftField({
  label,
  value,
  placeholder,
  type = 'text',
  min,
  step,
  unit,
  onSave,
}: {
  label: string;
  value: string;
  placeholder?: string;
  type?: 'text' | 'number';
  min?: number;
  step?: string;
  unit?: string;
  onSave: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const commit = () => {
    if (draft !== value) onSave(draft);
  };
  return (
    <label className="inline">
      <span>{label}</span>
      <input
        type={type}
        aria-label={label}
        placeholder={placeholder}
        min={min}
        step={step}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
          }
        }}
      />
      {unit && <span>{unit}</span>}
    </label>
  );
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
        <DraftField
          key={value ?? ''}
          label="Other battery type"
          value={value ?? ''}
          placeholder="e.g. 2CR5"
          onSave={(text) => {
            onChange(text.trim() === '' ? undefined : text.trim());
          }}
        />
      )}
    </span>
  );
}

export function DeviceSettingsPanel({ hass, hassBox }: Props) {
  const { status, snapshot } = useSnapshot(hassBox, hassBox.latest?.connection);
  const [selectedId, setSelectedId] = useState<string>('');

  // Real devices plus battery sensors that have no device, so a cloud or
  // template sensor can be renamed or typed like anything else.
  const options = useMemo<DeviceOption[]>(
    () => (hass ? [...listDevices(hass), ...listOrphanBatteryEntities(hass)] : []),
    [hass],
  );
  const areaNames = useMemo(
    () =>
      hass
        ? Object.values(hass.areas)
            .map((a) => a.name)
            .sort((a, b) => a.localeCompare(b))
        : [],
    [hass],
  );

  const settingsMap = snapshot?.deviceSettings ?? {};
  const edited = Object.keys(settingsMap);
  const selected = options.find((o) => o.id === selectedId);
  const settings: DeviceSettings = settingsMap[selectedId] ?? {};
  const registryArea = selected?.area;

  function save(patch: Record<string, unknown>) {
    void callPulseCheck(hassBox.latest, 'set_device_settings', {
      device_id: selectedId,
      ...patch,
    });
  }

  return (
    <fieldset className="field">
      <legend>Per-device settings</legend>
      <p className="hint">
        Stored by the Pulse Check integration, so every card and notification uses them. Battery
        type and count feed the Actions tab; tick rechargeable for devices you charge rather than
        replace.
      </p>

      {status === 'missing' && (
        <p className="note">
          The Pulse Check integration is not set up, so there is nothing to edit.
        </p>
      )}
      {status === 'error' && <p className="note">Could not reach the Pulse Check integration.</p>}

      {edited.length > 0 && (
        <div className="checks" aria-label="Devices with settings">
          {edited.map((id) => {
            const option = options.find((o) => o.id === id);
            return (
              <button
                key={id}
                type="button"
                className="chip"
                aria-pressed={id === selectedId}
                onClick={() => {
                  setSelectedId(id);
                }}
              >
                {option ? option.name : id}
              </button>
            );
          })}
        </div>
      )}

      <div className="settingsline">
        <DevicePicker
          value={selectedId}
          options={options}
          onChange={setSelectedId}
          placeholder="Search devices to edit…"
        />
      </div>

      {selectedId !== '' && status === 'ready' && (
        <div
          className="settingsrow"
          aria-label={`Settings for ${selected ? deviceLabel(selected) : selectedId}`}
        >
          <div className="settingsline namearea">
            <DraftField
              key={`name:${selectedId}:${settings.name ?? ''}`}
              label="Display name"
              value={settings.name ?? ''}
              placeholder={selected?.name ?? 'Display name (optional)'}
              onSave={(name) => {
                save({ name: name.trim() });
              }}
            />
            <label className="inline">
              <span>Area</span>
              <select
                aria-label="Area"
                title="Area shown on the card. Pre-filled from the device registry; pick another to override."
                value={settings.area ?? registryArea ?? ''}
                onChange={(e) => {
                  const chosen = e.target.value;
                  // Choosing the registry's own area means "no override".
                  save({ area: chosen === registryArea ? '' : chosen });
                }}
              >
                <option value="">No area</option>
                {areaNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
                {settings.area !== undefined && !areaNames.includes(settings.area) && (
                  <option value={settings.area}>{settings.area} ?</option>
                )}
              </select>
            </label>
          </div>
          <div className="settingsline details">
            <BatteryTypeField
              key={`type:${selectedId}:${settings.battery_type ?? ''}`}
              value={settings.battery_type}
              onChange={(type) => {
                save({ battery_type: type ?? '' });
              }}
            />
            <DraftField
              key={`count:${selectedId}:${String(settings.battery_count ?? '')}`}
              label="Battery count"
              type="number"
              min={1}
              placeholder="1"
              value={settings.battery_count !== undefined ? String(settings.battery_count) : ''}
              onSave={(text) => {
                const n = Number(text);
                save({ battery_count: text.trim() === '' || !(n >= 1) ? '' : Math.floor(n) });
              }}
            />
            <label className="check">
              <input
                type="checkbox"
                checked={settings.rechargeable === true}
                onChange={(e) => {
                  save({ rechargeable: e.target.checked });
                }}
              />
              Rechargeable
            </label>
            <DraftField
              key={`quiet:${selectedId}:${String(settings.quiet_threshold_hours ?? '')}`}
              label="Quiet hours"
              type="number"
              min={0.01}
              step="any"
              placeholder="hours"
              unit="h"
              value={
                settings.quiet_threshold_hours !== undefined
                  ? String(settings.quiet_threshold_hours)
                  : ''
              }
              onSave={(text) => {
                const n = Number(text);
                save({ quiet_threshold_hours: text.trim() === '' || !(n > 0) ? '' : n });
              }}
            />
            <label className="inline">
              <span>Notify</span>
              <select
                aria-label="Notification policy"
                value={settings.notify_policy ?? ''}
                onChange={(e) => {
                  save({ notify_policy: e.target.value });
                }}
              >
                <option value="">Default for its severity</option>
                {NOTIFY_POLICIES.map((p) => (
                  <option key={p} value={p}>
                    {POLICY_LABELS[p]}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      )}
    </fieldset>
  );
}
