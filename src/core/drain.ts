/**
 * Battery drain estimation: "about 12 days left".
 *
 * Given a handful of (time, level) samples from the recorder, fit a straight
 * line through them and read the slope in % per day. Divide the current
 * level by that rate and you have a rough time to empty.
 *
 * Deliberately conservative:
 *  - needs at least 3 samples spanning at least 2 days
 *  - a flat or rising line (phones on charge, noisy sensors) gives no estimate
 *  - the result is a rough order of magnitude, shown as "~12d", never "11.7 days"
 *
 * Pure function, so it is trivial to unit test with made-up numbers.
 */

export interface DrainPoint {
  /** Milliseconds since epoch. */
  time: number;
  /** Battery level in percent. */
  level: number;
}

export interface DrainEstimate {
  /** Percentage points lost per day. Always positive. */
  ratePerDay: number;
  /** Days until the battery reaches 0% at the current rate. */
  daysLeft: number;
  /** How many samples the fit used, so the UI can hedge on thin data. */
  samples: number;
}

const DAY_MS = 24 * 60 * 60 * 1000;
export const MIN_SAMPLES = 3;
export const MIN_SPAN_DAYS = 2;
/** Slopes shallower than this are indistinguishable from noise. */
export const MIN_RATE_PER_DAY = 0.1;

/** Least-squares slope of level against time, in % per day. */
function slopePerDay(points: DrainPoint[]): number {
  const n = points.length;
  const meanT = points.reduce((s, p) => s + p.time, 0) / n;
  const meanL = points.reduce((s, p) => s + p.level, 0) / n;
  let num = 0;
  let den = 0;
  for (const p of points) {
    const dt = p.time - meanT;
    num += dt * (p.level - meanL);
    den += dt * dt;
  }
  if (den === 0) return 0;
  return (num / den) * DAY_MS; // per ms -> per day
}

export function estimateDrain(
  rawPoints: DrainPoint[],
  currentLevel: number,
): DrainEstimate | undefined {
  const points = rawPoints
    .filter((p) => Number.isFinite(p.time) && Number.isFinite(p.level))
    .sort((a, b) => a.time - b.time);
  if (points.length < MIN_SAMPLES) return undefined;

  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last) return undefined;
  if (last.time - first.time < MIN_SPAN_DAYS * DAY_MS) return undefined;

  const slope = slopePerDay(points);
  const ratePerDay = -slope;
  if (ratePerDay < MIN_RATE_PER_DAY) return undefined; // flat, rising or noise

  return {
    ratePerDay,
    daysLeft: Math.max(0, currentLevel / ratePerDay),
    samples: points.length,
  };
}

/** "~12d", "~3w", "~4mo": rough on purpose. */
export function formatDaysLeft(days: number): string {
  if (days < 1) return 'under a day';
  if (days < 14) return `~${String(Math.round(days))}d`;
  if (days < 60) return `~${String(Math.round(days / 7))}w`;
  if (days < 365) return `~${String(Math.round(days / 30))}mo`;
  return '1y+';
}
