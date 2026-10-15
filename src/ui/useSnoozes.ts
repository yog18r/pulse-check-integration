/**
 * `useSnoozes`: the snooze map as React state, mirrored to localStorage.
 *
 * React note: `useCallback` returns the same function object between
 * renders as long as its dependencies don't change. That matters because
 * the functions are passed down as props; a new function every render
 * would make every row re-render for nothing.
 */
import { useCallback, useState } from 'react';
import {
  loadSnoozes,
  saveSnoozes,
  snoozeUntil,
  withoutSnooze,
  withSnooze,
  type SnoozeMap,
} from '../card/snoozeStore';

export interface SnoozeControls {
  snoozes: SnoozeMap;
  snooze: (deviceId: string, days: number) => void;
  unsnooze: (deviceId: string) => void;
}

export function useSnoozes(): SnoozeControls {
  // Lazy initialiser: the function runs once, on first render only.
  const [snoozes, setSnoozes] = useState<SnoozeMap>(() => loadSnoozes(new Date()));

  const snooze = useCallback((deviceId: string, days: number) => {
    setSnoozes((current) => {
      const next = withSnooze(current, deviceId, snoozeUntil(new Date(), days));
      saveSnoozes(next);
      return next;
    });
  }, []);

  const unsnooze = useCallback((deviceId: string) => {
    setSnoozes((current) => {
      const next = withoutSnooze(current, deviceId);
      saveSnoozes(next);
      return next;
    });
  }, []);

  return { snoozes, snooze, unsnooze };
}
