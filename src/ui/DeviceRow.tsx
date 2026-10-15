/**
 * One device in a list. Both tabs use this; `mode` picks what the right-hand
 * status column emphasises.
 *
 * The main part of the row is a <button>, so it is keyboard reachable and
 * announced as clickable. Tapping it opens the device in Home Assistant.
 * The snooze control sits beside it as a separate button.
 */
import type { BatteryHistory } from '../card/statistics';
import { formatDaysLeft } from '../core/drain';
import { formatHours, formatRelative } from '../core/time';
import type { DeviceHealth, Severity } from '../core/types';
import { BatteryBar } from './BatteryBar';
import { IntegrationBadge } from './IntegrationBadge';
import { SnoozeMenu } from './SnoozeMenu';
import { Sparkline } from './Sparkline';

interface Props {
  device: DeviceHealth;
  /** The severity to colour this row with (battery-only on the battery tab, etc). */
  severity: Severity;
  mode: 'battery' | 'connectivity';
  now: Date;
  /** Called when the row is activated. Optional so the row works without HA. */
  onOpen?: ((device: DeviceHealth) => void) | undefined;
  /** Battery history (trend points and drain estimate), when the recorder had any. */
  history?: BatteryHistory | undefined;
  /** Draw the trend line next to the bar. */
  sparkline?: boolean;
  /** Snooze handlers. When absent the 💤 control is not rendered. */
  onSnooze?: ((device: DeviceHealth, days: number) => void) | undefined;
  onUnsnooze?: ((device: DeviceHealth) => void) | undefined;
}

function connectivityLabel(device: DeviceHealth): string {
  if (device.isOffline) return 'Offline';
  if (device.isQuiet) return 'Quiet';
  return 'Online';
}

export function DeviceRow({
  device,
  severity,
  mode,
  now,
  onOpen,
  history,
  sparkline = true,
  onSnooze,
  onUnsnooze,
}: Props) {
  const drain = history?.estimate;
  const lastHeard = formatRelative(device.lastHeard, now);
  const charging = device.battery?.isCharging === true;
  // Only offer snoozing where there is something to snooze.
  const snoozable =
    onSnooze !== undefined &&
    onUnsnooze !== undefined &&
    (device.snoozedUntil !== undefined || severity !== 'ok');

  return (
    <li
      className="row"
      data-severity={severity}
      data-snoozed={device.snoozedUntil ? 'true' : undefined}
    >
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
            {charging && (
              <span className="badge" data-kind="charging" title="Charging">
                ⚡ charging
              </span>
            )}
            {device.snoozedUntil && (
              <span className="badge" data-kind="snoozed">
                💤 until {device.snoozedUntil.toLocaleDateString()}
              </span>
            )}
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
              <span className="gauge">
                {sparkline && history && <Sparkline points={history.points} severity={severity} />}
                <BatteryBar battery={device.battery} severity={severity} />
              </span>
              <span className="sub">
                heard {lastHeard}
                {drain && !charging && (
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

      {snoozable && (
        <SnoozeMenu
          deviceName={device.name}
          snoozedUntil={device.snoozedUntil}
          onSnooze={(days) => {
            onSnooze(device, days);
          }}
          onUnsnooze={() => {
            onUnsnooze(device);
          }}
        />
      )}
    </li>
  );
}
