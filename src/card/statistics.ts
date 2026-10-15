/**
 * Fetching battery history from Home Assistant's recorder.
 *
 * The frontend `hass` object only holds the current state. For drain rates
 * we need the past, so we ask the recorder for daily averages of each
 * battery sensor over the websocket:
 *
 *   { type: "recorder/statistics_during_period", statistic_ids, period: "day", types: ["mean"] }
 *
 * This is the same call the HA history graphs use. Long-term statistics
 * exist for any sensor with `state_class: measurement`, which battery
 * sensors have. Sensors without statistics simply come back empty and get
 * no estimate.
 *
 * Nothing here is React. The hook in `src/ui/useDrainEstimates.ts` calls
 * `loadDrains` and caches the answer.
 */
import { estimateDrain, type DrainEstimate, type DrainPoint } from '../core/drain';
import type { HassLike } from '../core/types';

export const HISTORY_DAYS = 14;

/** One row of the recorder's answer. `start` is epoch ms in current HA, ISO in older. */
interface StatisticsRow {
  start: number | string;
  end?: number | string;
  mean?: number | null;
}

type StatisticsResponse = Record<string, StatisticsRow[] | undefined>;

export interface BatteryEntity {
  entityId: string;
  level: number;
}

/** What we know about one battery's past: the daily points, and a fit if one was possible. */
export interface BatteryHistory {
  /** Daily means over the window plus the live reading, oldest first. */
  points: DrainPoint[];
  estimate?: DrainEstimate;
}

function toMillis(value: number | string): number {
  return typeof value === 'number' ? value : new Date(value).getTime();
}

/** Convert the recorder's rows into the points `estimateDrain` wants. */
export function rowsToPoints(rows: StatisticsRow[]): DrainPoint[] {
  const points: DrainPoint[] = [];
  for (const row of rows) {
    if (row.mean === null || row.mean === undefined) continue;
    points.push({ time: toMillis(row.start), level: row.mean });
  }
  return points;
}

/**
 * Fetch history for the given battery sensors and estimate each one's drain.
 * Resolves to an empty map (never rejects) when the recorder is unavailable,
 * so callers can treat "no data" and "no recorder" the same way.
 */
export async function loadDrains(
  hass: HassLike,
  batteries: BatteryEntity[],
  now: Date = new Date(),
): Promise<Map<string, BatteryHistory>> {
  const result = new Map<string, BatteryHistory>();
  if (!hass.callWS || batteries.length === 0) return result;

  const start = new Date(now.getTime() - HISTORY_DAYS * 24 * 60 * 60 * 1000);
  let response: StatisticsResponse;
  try {
    response = await hass.callWS<StatisticsResponse>({
      type: 'recorder/statistics_during_period',
      start_time: start.toISOString(),
      end_time: now.toISOString(),
      statistic_ids: batteries.map((b) => b.entityId),
      period: 'day',
      types: ['mean'],
    });
  } catch (err) {
    console.warn('[pulse-check-card] could not load battery statistics', err);
    return result;
  }

  for (const battery of batteries) {
    const rows = response[battery.entityId];
    if (!rows) continue;
    // Append the live reading as the final point. Daily statistics lag by
    // an hour or more, so without this a battery that just fell off a cliff
    // would look flat until the recorder caught up.
    const points = [...rowsToPoints(rows), { time: now.getTime(), level: battery.level }].sort(
      (a, b) => a.time - b.time,
    );
    if (points.length < 2) continue; // only the live point: nothing to draw or fit
    const history: BatteryHistory = { points };
    const estimate = estimateDrain(points, battery.level);
    if (estimate) history.estimate = estimate;
    result.set(battery.entityId, history);
  }
  return result;
}
