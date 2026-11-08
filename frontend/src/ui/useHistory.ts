/**
 * `useHistory`: sparkline history for the battery entities on screen,
 * fetched from the integration: all of them once and then every few hours,
 * and in between only the ones that newly appear.
 *
 * React notes:
 *  - The full refresh is one effect with a timer. It does not depend on
 *    which batteries are on screen, so it is not restarted when that changes.
 *  - A second effect re-runs when the *set of battery entities* changes
 *    (`key`), not on every snapshot, and fetches only what is not loaded
 *    yet. A battery flapping unavailable/available (leaving and rejoining
 *    the list) costs nothing: its history is still in the map.
 *  - `useRef` holds values that survive re-renders without causing one:
 *    the latest requests (so the timer callback reads fresh ones), and the
 *    set of requests already fetched or in flight.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { loadHistories, type HistoryRequest } from '../card/snapshot';
import type { BatteryHistory } from '../core/drain';
import type { HassBox } from '../core/types';

export type HistoryMap = ReadonlyMap<string, BatteryHistory>;

export const REFRESH_MS = 6 * 60 * 60 * 1000;

export type { HistoryRequest };

/** One request as a string: the same battery over another window is another request. */
function requestKey(request: HistoryRequest): string {
  return `${request.entityId}@${String(request.days)}`;
}

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
  // Requests fetched or in flight, so a battery is not asked for twice.
  const fetched = useRef(new Set<string>());

  // Stable key: the entity ids and their windows decide *when* to look for new ones.
  const key = requests.map(requestKey).sort().join('|');
  const canFetch = enabled && key !== '' && typeof hassBox.latest?.callWS === 'function';

  // Fetch `wanted` in one request and merge the answer into the map.
  // Entries for batteries no longer on screen stay; they are small, and
  // come in handy if the battery comes back.
  // React note: `useCallback` keeps the same function between renders
  // (until `hassBox` changes, which it does not), so the effects below that
  // list it as a dependency do not re-run on every render.
  const load = useCallback(
    (wanted: readonly HistoryRequest[]) => {
      const hass = hassBox.latest;
      if (!hass || wanted.length === 0) return;
      const keys = wanted.map(requestKey);
      for (const k of keys) fetched.current.add(k);
      loadHistories(hass, wanted).then(
        (found) => {
          // The setter's function form merges into the newest map, even if
          // another fetch landed in the meantime.
          setHistories((previous) => new Map([...(previous ?? []), ...found]));
        },
        (err: unknown) => {
          // Keep what is on screen; forget these so a later change retries them.
          console.warn('Pulse Check: could not load battery history', err);
          for (const k of keys) fetched.current.delete(k);
        },
      );
    },
    [hassBox],
  );

  // Every sparkline on screen, now and every few hours (batteries drain).
  useEffect(() => {
    if (!canFetch) return;
    const refresh = () => {
      fetched.current.clear();
      load(latest.current);
    };
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => {
      clearInterval(timer);
    };
  }, [canFetch, load]);

  // Between refreshes, only the batteries that are not loaded yet.
  useEffect(() => {
    if (!canFetch) return;
    load(latest.current.filter((r) => !fetched.current.has(requestKey(r))));
  }, [key, canFetch, load]);

  return histories;
}
