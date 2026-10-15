/**
 * `useLastReported`: on-demand `last_reported` lookups for the entities of
 * devices currently flagged quiet.
 *
 * Rate limiting lives here, in one place:
 *  - an entity is asked about at most once per LAST_REPORTED_REFRESH_MS
 *  - a round runs when the candidate set changes or the interval elapses
 *  - the module-level cache survives the card being re-mounted (HA does
 *    that when you edit a dashboard), so re-opening a view costs nothing
 *
 * Remember: this talks to Home Assistant's server, never to devices.
 */
import { useEffect, useRef, useState } from 'react';
import { LAST_REPORTED_REFRESH_MS, loadLastReported } from '../card/lastReported';
import type { HassLike } from '../core/types';

const cache = new Map<string, Date>();
const fetchedAt = new Map<string, number>();

/** Which of these ids are due for a lookup? */
function dueIds(ids: readonly string[], now: number): string[] {
  return ids.filter((id) => now - (fetchedAt.get(id) ?? 0) >= LAST_REPORTED_REFRESH_MS);
}

export function useLastReported(
  hass: HassLike,
  candidateIds: readonly string[],
): ReadonlyMap<string, Date> {
  // A new Map instance per update, so consumers' memoisation sees a change.
  const [snapshot, setSnapshot] = useState<ReadonlyMap<string, Date>>(() => new Map(cache));

  const latestHass = useRef(hass);
  useEffect(() => {
    latestHass.current = hass;
  });

  const key = [...candidateIds].sort().join('|');
  const canFetch = typeof hass.callApi === 'function' && key !== '';

  useEffect(() => {
    if (!canFetch) return;
    let cancelled = false;

    const run = () => {
      const ids = dueIds(key.split('|'), Date.now());
      if (ids.length === 0) return;
      const started = Date.now();
      for (const id of ids) fetchedAt.set(id, started);
      void loadLastReported(latestHass.current, ids).then((fresh) => {
        if (cancelled || fresh.size === 0) return;
        for (const [id, d] of fresh) cache.set(id, d);
        setSnapshot(new Map(cache));
      });
    };

    run();
    const timer = setInterval(run, LAST_REPORTED_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [key, canFetch]);

  return snapshot;
}
