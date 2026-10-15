/**
 * One device in a list. Both tabs use this; `mode` picks what the right-hand
 * status column emphasises.
 *
 * The main part of the row is a <button>, so it is keyboard reachable and
 * announced as clickable. Tapping it opens the device in Home Assistant.
 * The snooze control sits beside it as a separate button.
 */
import { formatDaysLeft, type BatteryHistory } from '../core/drain';
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
  /** On the Actions tab: the instruction shown in place of the device name. */
  action?: string | undefined;
  /** Snooze handlers. When absent the 💤 control is not rendered. */
  onSnooze?: ((device: DeviceHealth, days: number) => void) | undefined;
  onUnsnooze?: ((device: DeviceHealth) => void) | undefined;
  /** On the Actions tab in integration mode: "I did it". Absent otherwise. */
  onDone?: ((device: DeviceHealth) => void) | undefined;
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
  action,
  onSnooze,
  onUnsnooze,
  onDone,
}: Props) {
  const drain = history?.estimate;
  // Days left: the browser's own fit when it has one, else the integration's.
  const daysLeft = drain?.daysLeft ?? device.daysLeft;
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
            {action ?? device.name}
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
            {device.unusual !== undefined && (
              <span
                className="badge"
                data-severity="warning"
                title="Compared with this device's own history"
              >
                ⚠ {device.unusual}
              </span>
            )}
          </span>
        </span>

        <span className="status">
          {mode === 'battery' && device.battery ? (
            <>
              <span className="gauge">
                {sparkline && history && (
                  <Sparkline points={history.points} days={history.days} severity={severity} />
                )}
                <BatteryBar battery={device.battery} severity={severity} />
              </span>
              <span className="sub">
                heard {lastHeard}
                {daysLeft !== undefined && !charging && (
                  <>
                    {' · '}
                    <span
                      title={
                        drain
                          ? `Losing about ${drain.ratePerDay.toFixed(1)}% per day`
                          : 'Estimated by the Pulse Check integration'
                      }
                    >
                      {formatDaysLeft(daysLeft)} left
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

      {onDone !== undefined && (
        <button
          type="button"
          className="done"
          aria-label={`Mark ${device.name} done`}
          title="Record that this battery was replaced or charged"
          onClick={() => {
            onDone(device);
          }}
        >
          ✓ Done
        </button>
      )}

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
