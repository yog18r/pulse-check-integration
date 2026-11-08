/**
 * `useHistory`: sparkline history for the battery entities on screen,
 * fetched from the integration in one request, once and then every few hours.
 *
 * React notes:
 *  - The effect only re-runs when the *set of battery entities* changes
 *    (`key`), not on every snapshot. Snapshots arrive every few seconds;
 *    refetching history that often would hammer the recorder.
 *  - `useRef` holds the latest inputs without triggering re-renders, so the
 *    timer callback always reads fresh values.
 */
import { useEffect, useRef, useState } from 'react';
import { loadHistories, type HistoryRequest } from '../card/snapshot';
import type { BatteryHistory } from '../core/drain';
import type { HassBox } from '../core/types';

export type HistoryMap = ReadonlyMap<string, BatteryHistory>;

export const REFRESH_MS = 6 * 60 * 60 * 1000;

export type { HistoryRequest };

export function useHistory(
  hassBox: HassBox,
  requests: HistoryRequest[],
  enabled: boolean,
): HistoryMap | undefined {
  const [histories, setHistories] = useState<HistoryMap | undefined>(undefined);
  const latest = useRef(requests);
  useEffect(() => {
    latest.current = requests;
  });

  // Stable key: the entity ids and their windows decide *when* to refetch.
  const key = requests
    .map((r) => `${r.entityId}@${String(r.days)}`)
    .sort()
    .join('|');
  const canFetch = enabled && key !== '' && typeof hassBox.latest?.callWS === 'function';

  useEffect(() => {
    if (!canFetch) return;
    let cancelled = false;

    const run = () => {
      const hass = hassBox.latest;
      if (!hass) return;
      // One request for every sparkline on screen. A battery the
      // integration does not know is simply missing from the answer.
      void loadHistories(hass, latest.current)
        .catch(() => new Map<string, BatteryHistory>())
        .then((map) => {
          if (!cancelled) setHistories(map);
        });
    };

    run();
    const timer = setInterval(run, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [hassBox, key, canFetch]);

  return histories;
}
