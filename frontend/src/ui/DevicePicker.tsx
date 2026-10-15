/**
 * A searchable device picker: type to filter hundreds of devices by name,
 * area or integration, then click or press Enter to choose.
 *
 * Implemented as a plain text input plus a listbox rather than a <select>,
 * because native selects can't be filtered and are painful with long
 * lists. Keyboard: ArrowUp/Down move, Enter picks, Escape closes.
 *
 * React note: this component owns some *local* state (the query text,
 * whether the list is open, which item is highlighted) but the chosen
 * device id still lives in the parent and arrives via props. Local UI
 * state in the component, data in the parent: a common split.
 */
import { useId, useState } from 'react';
import { deviceLabel, type DeviceOption } from '../core/registryOptions';
import { useT } from './i18n';

interface Props {
  value: string;
  options: DeviceOption[];
  /** Ids already used by other rows; shown but not selectable. */
  disabledIds?: ReadonlySet<string>;
  onChange: (deviceId: string) => void;
  placeholder?: string;
}

const MAX_RESULTS = 40;

function matches(option: DeviceOption, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === '') return true;
  const haystack = `${option.name} ${option.area ?? ''} ${option.integration ?? ''}`.toLowerCase();
  return q.split(/\s+/).every((word) => haystack.includes(word));
}

export function DevicePicker({ value, options, disabledIds, onChange, placeholder }: Props) {
  const t = useT();
  const [query, setQuery] = useState<string | null>(null); // null = not editing
  const [highlight, setHighlight] = useState(0);
  const listId = useId();

  const selected = options.find((o) => o.id === value);
  const editing = query !== null;
  const results = editing ? options.filter((o) => matches(o, query)).slice(0, MAX_RESULTS) : [];

  function choose(option: DeviceOption | undefined) {
    if (!option || disabledIds?.has(option.id)) return;
    onChange(option.id);
    setQuery(null);
  }

  return (
    <span className="picker">
      <input
        type="text"
        role="combobox"
        aria-expanded={editing}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-label={t.t('picker.device')}
        placeholder={placeholder ?? t.t('picker.search')}
        value={editing ? query : selected ? deviceLabel(selected) : value}
        onFocus={() => {
          setQuery('');
          setHighlight(0);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setHighlight(0);
        }}
        onBlur={() => {
          // Let a click on a result land before closing.
          setTimeout(() => {
            setQuery(null);
          }, 150);
        }}
        onKeyDown={(e) => {
          if (!editing) return;
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, results.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === 'Enter') {
            e.preventDefault();
            choose(results[highlight]);
          } else if (e.key === 'Escape') {
            setQuery(null);
          }
        }}
      />
      {editing && (
        <ul className="results" id={listId} role="listbox">
          {results.length === 0 && <li className="noresults">{t.t('picker.none')}</li>}
          {results.map((o, i) => {
            const disabled = disabledIds?.has(o.id) === true && o.id !== value;
            return (
              <li
                key={o.id}
                role="option"
                aria-selected={o.id === value}
                aria-disabled={disabled}
                className={i === highlight ? 'active' : undefined}
                onMouseDown={(e) => {
                  e.preventDefault(); // keep focus on the input until we choose
                  if (!disabled) choose(o);
                }}
                onMouseEnter={() => {
                  setHighlight(i);
                }}
              >
                <span className="pname">{o.name}</span>
                {(o.area ?? o.integration) && (
                  <span className="pmeta">
                    {[o.area, o.integration].filter(Boolean).join(' · ')}
                  </span>
                )}
              </li>
            );
          })}
          {options.length > MAX_RESULTS && results.length === MAX_RESULTS && (
            <li className="noresults">{t.t('picker.more')}</li>
          )}
        </ul>
      )}
    </span>
  );
}
