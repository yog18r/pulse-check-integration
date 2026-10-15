/**
 * Battery level as a coloured bar plus a percentage. For binary sensors
 * (no percentage) we show the word "Low" or "OK" instead of a bar.
 *
 * Accessibility: the bar is a `meter` so screen readers announce the value.
 */
import type { BatteryReading, Severity } from '../core/types';
import { useT } from './i18n';

interface Props {
  battery: BatteryReading;
  severity: Severity;
}

export function BatteryBar({ battery, severity }: Props) {
  const t = useT();
  if (battery.level === undefined) {
    return (
      <span className="label" data-severity={severity}>
        {battery.isLow ? t.t('battery.low') : t.t('battery.ok')}
      </span>
    );
  }

  const pct = battery.level;
  return (
    <div className="battery">
      <div
        className="bar"
        role="meter"
        aria-label={t.t('battery.level')}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div className="fill" data-severity={severity} style={{ width: `${String(pct)}%` }} />
      </div>
      <span className="label" data-severity={severity}>
        {pct}%
      </span>
    </div>
  );
}
