/**
 * A list of rows capped at `maxRows`, with a "show N more" control.
 *
 * Generic over the item type: the parent decides how to render each item.
 * This keeps the capping logic in one place for both tabs.
 *
 * React note: `<T,>` is how you write a generic component in a .tsx file
 * (the trailing comma stops the parser reading `<T>` as a JSX tag).
 */
import { useState, type ReactNode } from 'react';
import { useT } from './i18n';

interface Props<T> {
  items: T[];
  maxRows: number | 'all';
  renderRow: (item: T) => ReactNode;
  /** Something that changes when the list's identity changes, to collapse again. */
  resetKey?: string;
}

export function RowList<T>({ items, maxRows, renderRow, resetKey = '' }: Props<T>) {
  const t = useT();
  const [expandedFor, setExpandedFor] = useState<string | null>(null);
  const expanded = expandedFor === resetKey;

  const cap = maxRows === 'all' ? items.length : maxRows;
  const visible = expanded ? items : items.slice(0, cap);
  const hidden = items.length - visible.length;

  return (
    <>
      <ul className="rows">{visible.map(renderRow)}</ul>
      {(hidden > 0 || (expanded && items.length > cap)) && (
        <button
          type="button"
          className="footerbutton"
          aria-expanded={expanded}
          onClick={() => {
            setExpandedFor(expanded ? null : resetKey);
          }}
        >
          {expanded ? t.t('rows.show_less') : t.tn('rows.show_more', hidden)}
        </button>
      )}
    </>
  );
}
