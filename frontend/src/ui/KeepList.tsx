/**
 * A tick-to-keep list for the card's view filters.
 *
 * Everything ticked means "show all" and writes no key at all; unticking
 * writes the list of what is still ticked. Values from YAML that match
 * none of the options (a renamed area, a typo) are shown as extra ticked
 * entries with a "?", so switching to the visual editor never silently
 * drops them.
 */
export interface KeepOption {
  id: string;
  label: string;
}

interface Props {
  legend: string;
  hint?: string;
  options: KeepOption[];
  /** The YAML list, if any. Undefined (or empty) means everything. */
  value: string[] | undefined;
  onChange: (value: string[] | undefined) => void;
}

const lower = (v: string) => v.trim().toLowerCase();

export function KeepList({ legend, hint, options, value, onChange }: Props) {
  const list = value ?? [];
  const all = list.length === 0;
  const wanted = new Set(list.map(lower));
  const known = new Set(options.flatMap((o) => [lower(o.id), lower(o.label)]));
  const kept = (o: KeepOption) => all || wanted.has(lower(o.id)) || wanted.has(lower(o.label));
  const strays = list.filter((v) => !known.has(lower(v)));

  function toggle(id: string, on: boolean) {
    const next = options.filter((o) => (o.id === id ? on : kept(o))).map((o) => o.id);
    next.push(...strays);
    // Everything ticked again: drop the key rather than listing it all.
    onChange(
      next.length === options.length + strays.length && strays.length === 0 ? undefined : next,
    );
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
              checked={kept(o)}
              onChange={(e) => {
                toggle(o.id, e.target.checked);
              }}
            />
            {o.label}
          </label>
        ))}
        {strays.map((v) => (
          <label key={`stray:${v}`} className="check" title="From YAML; not found in this instance">
            <input
              type="checkbox"
              checked
              onChange={() => {
                const next = list.filter((x) => x !== v);
                onChange(next.length > 0 ? next : undefined);
              }}
            />
            {v} ?
          </label>
        ))}
      </div>
    </fieldset>
  );
}
