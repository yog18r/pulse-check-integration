/**
 * On-demand `last_reported` lookup.
 *
 * The frontend's `last_updated` only moves when a value changes, so a
 * sensor that keeps reporting the same temperature looks silent. HA's
 * server records a separate `last_reported` that moves on every report,
 * and its REST API exposes it: GET /api/states/<entity_id>.
 *
 * This asks Home Assistant's own server what it already knows. Nothing is
 * sent to any device, so it cannot affect a device's battery. We still keep
 * it modest: only entities of devices currently flagged quiet, at most a
 * few dozen per round, and each entity at most once per refresh interval.
 */
import { parseTimestamp } from '../core/availability';
import type { HassLike } from '../core/types';

/** How often a given entity may be asked about. */
export const LAST_REPORTED_REFRESH_MS = 5 * 60 * 1000;
/** Cap per round, so a huge quiet list can't fire hundreds of requests. */
export const MAX_LOOKUPS_PER_ROUND = 40;

interface RestState {
  entity_id?: string;
  last_reported?: string;
  last_updated?: string;
}

/**
 * Fetch `last_reported` for the given entities. Resolves to whatever could
 * be fetched; individual failures are skipped, and the function never
 * rejects.
 */
export async function loadLastReported(
  hass: HassLike,
  entityIds: readonly string[],
): Promise<Map<string, Date>> {
  const result = new Map<string, Date>();
  const callApi = hass.callApi;
  if (!callApi || entityIds.length === 0) return result;

  const batch = entityIds.slice(0, MAX_LOOKUPS_PER_ROUND);
  const settled = await Promise.allSettled(
    batch.map((id) => callApi<RestState>('GET', `states/${encodeURIComponent(id)}`)),
  );

  settled.forEach((outcome, i) => {
    const id = batch[i];
    if (!id || outcome.status !== 'fulfilled') return;
    const d = parseTimestamp(outcome.value.last_reported ?? outcome.value.last_updated);
    if (d) result.set(id, d);
  });
  return result;
}
