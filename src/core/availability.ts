/**
 * Availability and "last heard from".
 *
 *  - A device is OFFLINE when every one of its primary entities is
 *    `unavailable`. Primary means no `entity_category`; diagnostic and
 *    config entities (signal strength, firmware, identify buttons) are
 *    ignored because integrations often leave those available even when
 *    the hardware is gone, or vice versa.
 *  - A device's LAST HEARD timestamp is the newest `last_updated` across
 *    all of its entities.
 *  - A device is QUIET when that timestamp is older than a threshold.
 *
 * Limitation: the frontend only receives `last_updated`, which moves when
 * state or attributes change. A sensor that keeps reporting the same value
 * looks quiet even though the device is alive. See the README.
 */
import type { HassEntityRegistryEntry, HassEntityState } from './types';

export const UNAVAILABLE = 'unavailable';

export function isPrimary(entity: HassEntityRegistryEntry): boolean {
  return entity.entity_category === undefined;
}

/**
 * Decide whether a device is offline from its registry entries and states.
 *
 * @param entities registry entries belonging to the device
 * @param states   matching state objects (entities with no state are skipped)
 */
export function detectOffline(
  entities: HassEntityRegistryEntry[],
  states: Record<string, HassEntityState>,
): boolean {
  // Prefer primary entities. If the device only has diagnostic/config
  // entities, fall back to judging by all of them.
  const primary = entities.filter(isPrimary);
  const candidates = primary.length > 0 ? primary : entities;

  const withState = candidates
    .map((e) => states[e.entity_id])
    .filter((s): s is HassEntityState => s !== undefined);

  if (withState.length === 0) return false; // nothing to judge by
  return withState.every((s) => s.state === UNAVAILABLE);
}

/** Parse an ISO timestamp defensively. Returns undefined for garbage. */
export function parseTimestamp(value: unknown): Date | undefined {
  if (typeof value !== 'string' || value === '') return undefined;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/** The newest `last_updated` among the given states, or undefined if none parse. */
export function detectLastHeard(states: HassEntityState[]): Date | undefined {
  let latest: Date | undefined;
  for (const s of states) {
    const d = parseTimestamp(s.last_updated);
    if (d && (!latest || d > latest)) latest = d;
  }
  return latest;
}

/** True when `lastHeard` is more than `thresholdHours` before `now`. */
export function isQuiet(lastHeard: Date | undefined, now: Date, thresholdHours: number): boolean {
  if (!lastHeard) return false; // unknown is not the same as quiet
  const ageMs = now.getTime() - lastHeard.getTime();
  return ageMs > thresholdHours * 60 * 60 * 1000;
}
