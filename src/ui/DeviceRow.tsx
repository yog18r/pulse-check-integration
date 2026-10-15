/**
 * One device in a list. Both tabs use this; `mode` picks what the right-hand
 * status column emphasises.
 */
import { formatRelative } from '../core/time';
import type { DeviceHealth, Severity } from '../core/types';
import { BatteryBar } from './BatteryBar';
import { IntegrationBadge } from './IntegrationBadge';

interface Props {
  device: DeviceHealth;
  /** The severity to colour this row with (battery-only on the battery tab, etc). */
  severity: Severity;
  mode: 'battery' | 'connectivity';
  now: Date;
}

function connectivityLabel(device: DeviceHealth): string {
  if (device.isOffline) return 'Offline';
  if (device.isQuiet) return 'Quiet';
  return 'Online';
}

export function DeviceRow({ device, severity, mode, now }: Props) {
  const lastHeard = formatRelative(device.lastHeard, now);

  return (
    <li className="row" data-severity={severity}>
      <span className="stripe" aria-hidden="true" />

      <div className="main">
        <div className="name" title={device.name}>
          {device.name}
        </div>
        <div className="meta">
          {device.area && <span>{device.area}</span>}
          <IntegrationBadge platform={device.integration} />
          {device.extras.map((extra) => (
            <span key={extra.label} className="badge" data-severity={extra.severity ?? 'ok'}>
              {extra.label}: {extra.value}
            </span>
          ))}
        </div>
      </div>

      <div className="status">
        {mode === 'battery' && device.battery ? (
          <>
            <BatteryBar battery={device.battery} severity={severity} />
            <span className="sub">heard {lastHeard}</span>
          </>
        ) : (
          <>
            <span className="label" data-severity={severity}>
              {connectivityLabel(device)}
            </span>
            <span className="sub">last heard {lastHeard}</span>
          </>
        )}
      </div>
    </li>
  );
}
