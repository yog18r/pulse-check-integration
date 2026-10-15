/**
 * The 💤 control at the end of a row: snooze for 1/7/30 days, or unsnooze.
 *
 * Kept outside the row's main <button> because buttons can't nest. Opens
 * a small inline menu; closes on choice, Escape or blur.
 */
import { useState } from 'react';
import { useT } from './i18n';

/** Options offered in the menu, in days. */
export const SNOOZE_CHOICES_DAYS = [1, 7, 30] as const;

interface Props {
  deviceName: string;
  snoozedUntil?: Date | undefined;
  onSnooze: (days: number) => void;
  onUnsnooze: () => void;
}

export function SnoozeMenu({ deviceName, snoozedUntil, onSnooze, onUnsnooze }: Props) {
  const t = useT();
  const [open, setOpen] = useState(false);

  if (snoozedUntil) {
    return (
      <button
        type="button"
        className="snooze"
        title={t.t('snooze.until_title', { date: snoozedUntil.toLocaleDateString(t.language) })}
        aria-label={t.t('snooze.unsnooze_label', { name: deviceName })}
        onClick={onUnsnooze}
      >
        💤
      </button>
    );
  }

  return (
    <span
      className="snoozewrap"
      onBlur={(e) => {
        // Close when focus leaves the whole control, not just one button.
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false);
      }}
    >
      <button
        type="button"
        className="snooze"
        title={t.t('snooze.title')}
        aria-label={t.t('snooze.label', { name: deviceName })}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => {
          setOpen((o) => !o);
        }}
      >
        💤
      </button>
      {open && (
        <span className="menu" role="menu">
          {SNOOZE_CHOICES_DAYS.map((days) => (
            <button
              key={days}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onSnooze(days);
              }}
            >
              {t.tn('snooze.days', days)}
            </button>
          ))}
        </span>
      )}
    </span>
  );
}
