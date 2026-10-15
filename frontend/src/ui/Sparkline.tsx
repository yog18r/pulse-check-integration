/**
 * A tiny inline SVG trend line: 14 days of battery level at a glance.
 *
 * The vertical scale hugs the data (with a little padding) rather than
 * running 0-100, so a slow 5% decline is visible as a slope instead of a
 * flat line. The colour follows the row's severity like the bar does.
 *
 * Decorative: screen readers get the numbers from the bar and the text, so
 * the SVG is aria-hidden and only carries a tooltip.
 */
import type { DrainPoint } from '../core/drain';
import type { Severity } from '../core/types';
import { useT } from './i18n';

interface Props {
  points: DrainPoint[];
  severity: Severity;
  /** Window length for the tooltip; computed from the points when absent. */
  days?: number | undefined;
  width?: number;
  height?: number;
}

export function Sparkline({ points: rawPoints, severity, days, width = 48, height = 16 }: Props) {
  const t = useT();
  // Never let one bad sample (NaN from an odd integration) break the path.
  const points = rawPoints.filter((p) => Number.isFinite(p.time) && Number.isFinite(p.level));
  if (points.length < 2) return null;

  const times = points.map((p) => p.time);
  const levels = points.map((p) => p.level);
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const lo = Math.max(0, Math.min(...levels) - 3);
  const hi = Math.min(100, Math.max(...levels) + 3);
  const spanT = t1 - t0 || 1;
  const spanL = hi - lo || 1;

  const pad = 1.5;
  const x = (t: number) => pad + ((t - t0) / spanT) * (width - 2 * pad);
  const y = (l: number) => height - pad - ((l - lo) / spanL) * (height - 2 * pad);
  const d = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.time).toFixed(1)} ${y(p.level).toFixed(1)}`)
    .join(' ');

  const first = levels[0] ?? 0;
  const last = levels[levels.length - 1] ?? 0;
  const span = days ?? Math.round((t1 - t0) / 86_400_000);
  const ends = { first: Math.round(first), last: Math.round(last) };
  const title = span < 1 ? t.t('spark.title_day', ends) : t.tn('spark.title', span, ends);

  return (
    <svg
      className="spark"
      data-severity={severity}
      width={width}
      height={height}
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      aria-hidden="true"
    >
      <title>{title}</title>
      <path d={d} fill="none" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
