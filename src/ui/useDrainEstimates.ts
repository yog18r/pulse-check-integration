/**
 * `useDrainEstimates`: load battery drain estimates once, then refresh every
 * few hours. Returns `undefined` until the first answer arrives.
 *
 * React notes:
 *  - The effect only re-runs when the *set of battery entities* changes
 *    (`key`), not on every `hass` update. HA replaces `hass` several times a
 *    second; refetching history that often would hammer the recorder.
 *  - `useRef` holds the latest `hass` and levels without triggering
 *    re-renders, so the timer callback always reads fresh values.
 */
import { useEffect, useRef, useState } from 'react';
import { type BatteryEntity, type BatteryHistory, loadDrains } from '../card/statistics';
import type { HassLike } from '../core/types';

export type DrainMap = ReadonlyMap<string, BatteryHistory>;

export const REFRESH_MS = 6 * 60 * 60 * 1000;

export function useDrainEstimates(
  hass: HassLike,
  batteries: BatteryEntity[],
): DrainMap | undefined {
  const [drains, setDrains] = useState<DrainMap | undefined>(undefined);

  // Keep the newest inputs where the timer can see them.
  const latest = useRef({ hass, batteries });
  useEffect(() => {
    latest.current = { hass, batteries };
  });

  // Stable key: the entity ids and their windows decide *when* to refetch.
  const key = batteries
    .map((b) => `${b.entityId}@${String(b.days ?? '')}`)
    .sort()
    .join('|');
  const canFetch = typeof hass.callWS === 'function' && key !== '';

  useEffect(() => {
    if (!canFetch) return;
    let cancelled = false;

    const run = () => {
      const { hass: h, batteries: b } = latest.current;
      void loadDrains(h, b).then((map) => {
        if (!cancelled) setDrains(map);
      });
    };

    run();
    const timer = setInterval(run, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [key, canFetch]);

  return drains;
}
