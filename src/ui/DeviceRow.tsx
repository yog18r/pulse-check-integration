/**
 * One device in a list. Both tabs use this; `mode` picks what the right-hand
 * status column emphasises.
 *
 * The whole row is a <button>, so it is keyboard reachable and announced
 * as clickable. Tapping it opens the device in Home Assistant.
 */
import { formatDaysLeft, type DrainEstimate } from '../core/drain';
import { formatHours, formatRelative } from '../core/time';
import type { DeviceHealth, Severity } from '../core/types';
import { BatteryBar } from './BatteryBar';
import { IntegrationBadge } from './IntegrationBadge';

interface Props {
  device: DeviceHealth;
  /** The severity to colour this row with (battery-only on the battery tab, etc). */
  severity: Severity;
  mode: 'battery' | 'connectivity';
  now: Date;
  /** Called when the row is activated. Optional so the row works without HA. */
  onOpen?: ((device: DeviceHealth) => void) | undefined;
  /** Drain estimate for the battery, when the recorder had enough history. */
  drain?: DrainEstimate | undefined;
}

function connectivityLabel(device: DeviceHealth): string {
  if (device.isOffline) return 'Offline';
  if (device.isQuiet) return 'Quiet';
  return 'Online';
}

export function DeviceRow({ device, severity, mode, now, onOpen, drain }: Props) {
  const lastHeard = formatRelative(device.lastHeard, now);

  return (
    <li className="row" data-severity={severity}>
      <button
        type="button"
        className="rowbutton"
        onClick={() => onOpen?.(device)}
        aria-label={`${device.name}, open in Home Assistant`}
      >
        <span className="stripe" aria-hidden="true" />

        <span className="main">
          <span className="name" title={device.name}>
            {device.name}
          </span>
          <span className="meta">
            {device.area && <span>{device.area}</span>}
            <IntegrationBadge platform={device.integration} />
            {device.extras.map((extra) => (
              <span key={extra.label} className="badge" data-severity={extra.severity ?? 'ok'}>
                {extra.label}: {extra.value}
              </span>
            ))}
          </span>
        </span>

        <span className="status">
          {mode === 'battery' && device.battery ? (
            <>
              <BatteryBar battery={device.battery} severity={severity} />
              <span className="sub">
                heard {lastHeard}
                {drain && (
                  <>
                    {' · '}
                    <span title={`Losing about ${drain.ratePerDay.toFixed(1)}% per day`}>
                      {formatDaysLeft(drain.daysLeft)} left
                    </span>
                  </>
                )}
              </span>
            </>
          ) : (
            <>
              <span className="label" data-severity={severity}>
                {connectivityLabel(device)}
              </span>
              <span className="sub">
                last heard {lastHeard}
                {device.isQuiet && ` · limit ${formatHours(device.quietThresholdHours)}`}
              </span>
            </>
          )}
        </span>
      </button>
    </li>
  );
}
