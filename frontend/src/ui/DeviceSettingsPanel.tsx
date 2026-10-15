/**
 * Per-device settings, edited in the card editor but stored by the
 * integration.
 *
 * Pick a device (any device in the house, or a battery sensor that has no
 * device), then change its display name, area, battery type and count,
 * rechargeable, quiet hours, trend window or notification policy. Every
 * change is sent straight to `pulse_check.set_device_settings`; the next
 * snapshot from the subscription shows it saved. Nothing lands in the
 * card's YAML, so every card and every notification sees the same
 * settings. That also means Home Assistant's own Save button in the
 * dialog has nothing to do with these fields, which the panel says.
 *
 * React note: text fields keep a local draft while typing and save on
 * blur (or Enter), so each keystroke is not a service call. Selects and
 * checkboxes save immediately.
 */
import { useEffect, useMemo, useState } from 'react';
import { callPulseCheck, NOTIFY_POLICIES, type DeviceSettings } from '../card/snapshot';
import {
  BATTERY_TYPE_GROUPS,
  batteryTypeLabel,
  isKnownBatteryType,
  OTHER_BATTERY_TYPE,
} from '../core/batteryTypes';
import {
  deviceLabel,
  listDevices,
  listOrphanBatteryEntities,
  type DeviceOption,
} from '../core/registryOptions';
import type { HassBox, HassLike } from '../core/types';
import { DevicePicker } from './DevicePicker';
import { useT } from './i18n';
import { useSnapshot } from './useSnapshot';

interface Props {
  /** For the device picker and area list (registries). */
  hass: HassLike | undefined;
  /** For the subscription and service calls. */
  hassBox: HassBox;
}

/** How long "Saved to Pulse Check" stays on screen. */
const FEEDBACK_MS = 3000;

interface Feedback {
  kind: 'saved' | 'error';
  text: string;
}

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
  grow = false,
  onSave,
}: {
  label: string;
  value: string;
  placeholder?: string;
  type?: 'text' | 'number';
  min?: number;
  step?: string;
  unit?: string;
  /** Take the remaining width of the line (text fields). */
  grow?: boolean;
  onSave: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const commit = () => {
    if (draft !== value) onSave(draft);
  };
  return (
    <label className={grow ? 'inline grow' : 'inline'}>
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
  const t = useT();
  const known = value !== undefined && isKnownBatteryType(value);
  const [other, setOther] = useState(value !== undefined && !known);
  const selectValue = other ? OTHER_BATTERY_TYPE : (value ?? '');

  return (
    <span className="typefield">
      <select
        aria-label={t.t('settings.battery_type')}
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
        <option value="">{t.t('settings.battery_type_placeholder')}</option>
        {BATTERY_TYPE_GROUPS.map((g) => (
          <optgroup key={g.label} label={t.t(g.label)}>
            {g.types.map((type) => (
              <option key={type} value={type}>
                {batteryTypeLabel(type, t)}
              </option>
            ))}
          </optgroup>
        ))}
        <option value={OTHER_BATTERY_TYPE}>{t.t('settings.other')}</option>
      </select>
      {other && (
        <DraftField
          key={value ?? ''}
          label={t.t('settings.other_type')}
          value={value ?? ''}
          placeholder={t.t('settings.other_example')}
          onSave={(text) => {
            onChange(text.trim() === '' ? undefined : text.trim());
          }}
        />
      )}
    </span>
  );
}

export function DeviceSettingsPanel({ hass, hassBox }: Props) {
  const t = useT();
  const { status, snapshot } = useSnapshot(hassBox, hassBox.latest?.connection);
  const [selectedId, setSelectedId] = useState<string>('');
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  // "Saved" fades after a few seconds; an error stays until the next save.
  useEffect(() => {
    if (feedback?.kind !== 'saved') return;
    const timer = setTimeout(() => {
      setFeedback(null);
    }, FEEDBACK_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [feedback]);

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
            .sort((a, b) => a.localeCompare(b, t.language))
        : [],
    [hass, t],
  );

  const settingsMap = snapshot?.deviceSettings ?? {};
  const edited = Object.keys(settingsMap);
  const selected = options.find((o) => o.id === selectedId);
  const settings: DeviceSettings = settingsMap[selectedId] ?? {};
  const registryArea = selected?.area;
  const keyFor = (field: string, value: string | number | undefined) =>
    `${field}:${selectedId}:${value === undefined ? '' : String(value)}`;

  function save(patch: Record<string, unknown>) {
    callPulseCheck(hassBox.latest, 'set_device_settings', {
      device_id: selectedId,
      ...patch,
    }).then(
      () => {
        setFeedback({ kind: 'saved', text: t.t('settings.saved') });
      },
      (err: unknown) => {
        const reason = err instanceof Error ? err.message : String(err);
        setFeedback({ kind: 'error', text: t.t('settings.not_saved', { reason }) });
      },
    );
  }

  return (
    <fieldset className="field">
      <legend>{t.t('settings.legend')}</legend>
      <p className="hint">{t.t('settings.hint')}</p>

      {status === 'missing' && <p className="note">{t.t('settings.missing')}</p>}
      {status === 'error' && <p className="note">{t.t('settings.error')}</p>}

      {edited.length > 0 && (
        <div className="checks" aria-label={t.t('settings.edited')}>
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
                  setFeedback(null);
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
          onChange={(id) => {
            setSelectedId(id);
            setFeedback(null);
          }}
          placeholder={t.t('settings.search')}
        />
      </div>

      {selectedId !== '' && status === 'ready' && (
        <div
          className="settingsrow"
          aria-label={t.t('settings.for', {
            name: selected ? deviceLabel(selected) : selectedId,
          })}
        >
          <div className="settingsline">
            <DraftField
              key={keyFor('name', settings.name)}
              label={t.t('settings.name')}
              grow
              value={settings.name ?? ''}
              placeholder={selected?.name ?? t.t('settings.name_placeholder')}
              onSave={(name) => {
                save({ name: name.trim() });
              }}
            />
            <label className="inline grow">
              <span>{t.t('settings.area')}</span>
              <select
                aria-label={t.t('settings.area')}
                title={t.t('settings.area_title')}
                value={settings.area ?? registryArea ?? ''}
                onChange={(e) => {
                  const chosen = e.target.value;
                  // Choosing the registry's own area means "no override".
                  save({ area: chosen === registryArea ? '' : chosen });
                }}
              >
                <option value="">{t.t('settings.no_area')}</option>
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

          <div className="settingsline">
            <BatteryTypeField
              key={keyFor('type', settings.battery_type)}
              value={settings.battery_type}
              onChange={(type) => {
                save({ battery_type: type ?? '' });
              }}
            />
            <DraftField
              key={keyFor('count', settings.battery_count)}
              label={t.t('settings.count')}
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
              {t.t('settings.rechargeable')}
            </label>
          </div>

          <div className="settingsline">
            <DraftField
              key={keyFor('quiet', settings.quiet_threshold_hours)}
              label={t.t('settings.quiet')}
              type="number"
              min={0.01}
              step="any"
              placeholder={t.t('settings.hours')}
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
            <DraftField
              key={keyFor('trend', settings.sparkline_days)}
              label={t.t('settings.trend')}
              type="number"
              min={1}
              placeholder={t.t('settings.card_default')}
              unit="d"
              value={settings.sparkline_days !== undefined ? String(settings.sparkline_days) : ''}
              onSave={(text) => {
                const n = Number(text);
                save({
                  sparkline_days:
                    text.trim() === '' || !(n >= 1) ? '' : Math.min(365, Math.floor(n)),
                });
              }}
            />
            <label className="inline">
              <span>{t.t('settings.notify')}</span>
              <select
                aria-label={t.t('settings.policy')}
                value={settings.notify_policy ?? ''}
                onChange={(e) => {
                  save({ notify_policy: e.target.value });
                }}
              >
                <option value="">{t.t('settings.policy_default')}</option>
                {NOTIFY_POLICIES.map((p) => (
                  <option key={p} value={p}>
                    {t.t(`policy.${p}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {feedback && (
            <p className="feedback" role="status" data-kind={feedback.kind}>
              {feedback.kind === 'saved' ? '✓ ' : '⚠ '}
              {feedback.text}
            </p>
          )}
        </div>
      )}
    </fieldset>
  );
}
