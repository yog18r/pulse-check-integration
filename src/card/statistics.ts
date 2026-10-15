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
 * exist for any sensor with `state_class: measurement`. Battery sensors
 * from custom integrations often lack it, so those fall back to raw history
 * (see below).
 *
 * Nothing here is React. The hook in `src/ui/useDrainEstimates.ts` calls
 * `loadDrains` and caches the answer.
 */
import { parseNumeric } from '../core/battery';
import { estimateDrain, type DrainEstimate, type DrainPoint } from '../core/drain';
import type { HassLike } from '../core/types';

/** Days of history the drain estimate is fitted over, whatever the sparkline shows. */
export const HISTORY_DAYS = 14;
/** Windows this short get hourly points so the line has some shape. */
export const HOURLY_MAX_DAYS = 3;

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
  /** Sparkline window in days. Defaults to HISTORY_DAYS. */
  days?: number;
}

/** What we know about one battery's past: the points to draw, and a fit if one was possible. */
export interface BatteryHistory {
  /** Points over the requested window plus the live reading, oldest first. */
  points: DrainPoint[];
  /** The window those points cover, in days. */
  days: number;
  /** Fitted over the last HISTORY_DAYS only, so a year-long window doesn't dilute it. */
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

/* ---- raw history fallback ------------------------------------------- */

/**
 * One row of `history/history_during_period`. With minimal_response the
 * websocket API sends compressed keys: `s` state, `lu` last_updated as
 * epoch seconds. Older servers may send the long names on the first row.
 */
interface HistoryRow {
  s?: string;
  state?: string;
  lu?: number;
  last_updated?: string;
}

type HistoryResponse = Record<string, HistoryRow[] | undefined>;

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Collapse raw state changes into one point per UTC day (the mean of the
 * numeric states that day), the same shape the statistics API gives us.
 * Non-numeric states (unavailable, unknown) are skipped.
 */
export function historyToDailyPoints(rows: HistoryRow[]): DrainPoint[] {
  const sums = new Map<number, { total: number; count: number }>();
  for (const row of rows) {
    const level = parseNumeric(row.s ?? row.state);
    if (level === undefined) continue;
    const time =
      typeof row.lu === 'number'
        ? row.lu * 1000
        : row.last_updated
          ? new Date(row.last_updated).getTime()
          : Number.NaN;
    if (!Number.isFinite(time)) continue;
    const day = Math.floor(time / DAY_MS) * DAY_MS;
    const bucket = sums.get(day) ?? { total: 0, count: 0 };
    bucket.total += level;
    bucket.count += 1;
    sums.set(day, bucket);
  }
  return [...sums.entries()]
    .map(([day, { total, count }]) => ({ time: day, level: total / count }))
    .sort((a, b) => a.time - b.time);
}

/**
 * Sensors without long-term statistics (no `state_class: measurement`,
 * common in custom integrations) still have raw history. Fetch it for just
 * those entities, with the lightest options the API offers.
 */
async function loadRawHistory(
  hass: HassLike,
  entityIds: string[],
  start: Date,
  now: Date,
): Promise<Map<string, DrainPoint[]>> {
  const result = new Map<string, DrainPoint[]>();
  if (!hass.callWS || entityIds.length === 0) return result;
  try {
    const response = await hass.callWS<HistoryResponse>({
      type: 'history/history_during_period',
      start_time: start.toISOString(),
      end_time: now.toISOString(),
      entity_ids: entityIds,
      minimal_response: true,
      no_attributes: true,
      significant_changes_only: true,
    });
    for (const id of entityIds) {
      const rows = response[id];
      if (rows && rows.length > 0) result.set(id, historyToDailyPoints(rows));
    }
  } catch (err) {
    console.warn('[pulse-check-card] could not load raw battery history', err);
  }
  return result;
}

/**
 * Fetch history for the given battery sensors and estimate each one's drain.
 * Long-term statistics first (cheap, pre-aggregated); raw history as a
 * fallback for numeric sensors the recorder has no statistics for.
 * Resolves to an empty map (never rejects) when the recorder is unavailable,
 * so callers can treat "no data" and "no recorder" the same way.
 */
async function fetchStatistics(
  hass: HassLike,
  entityIds: string[],
  start: Date,
  now: Date,
  period: 'hour' | 'day',
): Promise<StatisticsResponse | undefined> {
  if (!hass.callWS || entityIds.length === 0) return {};
  try {
    return await hass.callWS<StatisticsResponse>({
      type: 'recorder/statistics_during_period',
      start_time: start.toISOString(),
      end_time: now.toISOString(),
      statistic_ids: entityIds,
      period,
      types: ['mean'],
    });
  } catch (err) {
    console.warn('[pulse-check-card] could not load battery statistics', err);
    return undefined;
  }
}

export async function loadDrains(
  hass: HassLike,
  batteries: BatteryEntity[],
  now: Date = new Date(),
): Promise<Map<string, BatteryHistory>> {
  const result = new Map<string, BatteryHistory>();
  if (!hass.callWS || batteries.length === 0) return result;

  // One daily request covering the longest window anyone asked for (never
  // less than the fit needs), then one hourly request for the short windows.
  const longest = Math.max(HISTORY_DAYS, ...batteries.map((b) => b.days ?? HISTORY_DAYS));
  const start = new Date(now.getTime() - longest * DAY_MS);
  const response = await fetchStatistics(
    hass,
    batteries.map((b) => b.entityId),
    start,
    now,
    'day',
  );
  if (!response) return result;

  const shortIds = batteries
    .filter((b) => (b.days ?? HISTORY_DAYS) <= HOURLY_MAX_DAYS)
    .map((b) => b.entityId);
  const hourly =
    (await fetchStatistics(
      hass,
      shortIds,
      new Date(now.getTime() - HOURLY_MAX_DAYS * DAY_MS),
      now,
      'hour',
    )) ?? {};

  // Anything the statistics API had nothing for, and that is a plain sensor
  // (attributes on e.g. a vacuum entity are not in no_attributes history).
  const missing = batteries
    .filter((b) => !response[b.entityId]?.length && b.entityId.startsWith('sensor.'))
    .map((b) => b.entityId);
  const raw = await loadRawHistory(hass, missing, start, now);

  for (const battery of batteries) {
    const days = battery.days ?? HISTORY_DAYS;
    const rows = response[battery.entityId];
    const daily = rows?.length ? rowsToPoints(rows) : raw.get(battery.entityId);
    if (!daily) continue;
    const livePoint = { time: now.getTime(), level: battery.level };

    // The fit always looks at the last HISTORY_DAYS of daily points plus the
    // live reading. Daily statistics lag by an hour or more, so without the
    // live point a battery that just fell off a cliff would look flat.
    const fitFrom = now.getTime() - HISTORY_DAYS * DAY_MS;
    const fitPoints = [...daily.filter((p) => p.time >= fitFrom), livePoint].sort(
      (a, b) => a.time - b.time,
    );

    // The drawing uses the requested window: hourly points when it is short.
    const windowFrom = now.getTime() - days * DAY_MS;
    const hourlyRows = hourly[battery.entityId];
    const source = days <= HOURLY_MAX_DAYS && hourlyRows?.length ? rowsToPoints(hourlyRows) : daily;
    const points = [...source.filter((p) => p.time >= windowFrom), livePoint].sort(
      (a, b) => a.time - b.time,
    );
    if (points.length < 2 && fitPoints.length < 2) continue; // only the live point

    const history: BatteryHistory = { points, days };
    const estimate = estimateDrain(fitPoints, battery.level);
    if (estimate) history.estimate = estimate;
    result.set(battery.entityId, history);
  }
  return result;
}
