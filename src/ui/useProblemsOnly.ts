/**
 * `useProblemsOnly`: the Batteries tab's "problems only" switch.
 *
 * Starts from the card config (`problems_only`), then remembers the user's
 * last choice in this browser, like snoozes. Falls back to plain state when
 * storage is unavailable.
 */
import { useCallback, useState } from 'react';

export const PROBLEMS_ONLY_KEY = 'pulse-check-card:problems-only';

function readStored(): boolean | undefined {
  try {
    const raw = localStorage.getItem(PROBLEMS_ONLY_KEY);
    return raw === null ? undefined : raw === 'true';
  } catch {
    return undefined;
  }
}

export function useProblemsOnly(initial: boolean): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => readStored() ?? initial);

  const set = useCallback((next: boolean) => {
    setValue(next);
    try {
      localStorage.setItem(PROBLEMS_ONLY_KEY, String(next));
    } catch {
      // Storage blocked: the switch still works for this page load.
    }
  }, []);

  return [value, set];
}
