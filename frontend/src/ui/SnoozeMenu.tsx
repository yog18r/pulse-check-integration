/**
 * The 💤 control at the end of a row: snooze for 1/7/30 days, or unsnooze.
 *
 * Kept outside the row's main <button> because buttons can't nest. Opens
 * a small menu; closes on choice, Escape or blur.
 *
 * The menu is a popover (the HTML `popover` attribute). The browser draws a
 * popover in the "top layer", above everything on the page, so neither the
 * card's rounded, clipped corners nor a dashboard container can cut it off
 * when the row is the last one in the card. A popover is positioned against
 * the window, not the row, so `usePlacement` keeps it next to the 💤 button,
 * below it or, when there is no room below, above it. Where popovers are not
 * supported the menu falls back to the old inline position under the button.
 *
 * React note: `useRef` gives stable handles on the two DOM elements, and
 * `useLayoutEffect` runs after React has put the menu in the DOM but before
 * the browser paints, so the menu never flashes in the wrong place.
 */
import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { useT } from './i18n';

/** Options offered in the menu, in days. */
export const SNOOZE_CHOICES_DAYS = [1, 7, 30] as const;

/** Space between the button and the menu, and the menu and the window edge. */
const GAP = 4;
const EDGE = 8;

/**
 * Whether this browser can show popovers. Checked once: a browser that
 * cannot would otherwise keep a popover element hidden for good, so the
 * attribute is only set where it works.
 */
const SUPPORTS_POPOVER =
  typeof HTMLElement !== 'undefined' && typeof HTMLElement.prototype.showPopover === 'function';

interface Props {
  deviceName: string;
  snoozedUntil?: Date | undefined;
  onSnooze: (days: number) => void;
  onUnsnooze: () => void;
}

/** Put the menu next to its button: right-aligned, below if it fits, else above. */
function place(menu: HTMLElement, button: HTMLElement): void {
  const anchor = button.getBoundingClientRect();
  const height = menu.offsetHeight;
  const fitsBelow = anchor.bottom + GAP + height <= window.innerHeight - EDGE;
  const top = fitsBelow ? anchor.bottom + GAP : Math.max(EDGE, anchor.top - GAP - height);
  const left = Math.max(EDGE, anchor.right - menu.offsetWidth);
  menu.style.top = `${String(top)}px`;
  menu.style.left = `${String(left)}px`;
}

/**
 * While `open`, show the menu as a popover and keep it beside its button.
 *
 * Home Assistant scrolls its dashboards inside shadow roots, where scroll
 * events never reach this card, so the position is refreshed on every
 * animation frame while the menu is open instead. That is a few rectangle
 * reads per frame, and only while a menu is showing.
 */
function usePlacement(
  open: boolean,
  menuRef: RefObject<HTMLSpanElement | null>,
  buttonRef: RefObject<HTMLButtonElement | null>,
): void {
  useLayoutEffect(() => {
    const menu = menuRef.current;
    const button = buttonRef.current;
    if (!open || !menu || !button || !SUPPORTS_POPOVER) return;
    menu.showPopover();
    let frame = 0;
    const follow = () => {
      place(menu, button);
      frame = requestAnimationFrame(follow);
    };
    follow();
    return () => {
      cancelAnimationFrame(frame);
      if (menu.matches(':popover-open')) menu.hidePopover();
    };
  }, [open, menuRef, buttonRef]);
}

export function SnoozeMenu({ deviceName, snoozedUntil, onSnooze, onUnsnooze }: Props) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLSpanElement>(null);
  usePlacement(open, menuRef, buttonRef);

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
        ref={buttonRef}
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
        <span
          ref={menuRef}
          className="menu"
          role="menu"
          popover={SUPPORTS_POPOVER ? 'manual' : undefined}
        >
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
