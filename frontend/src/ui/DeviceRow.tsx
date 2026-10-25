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
import type { Translator } from '../i18n';
import { translateBasis, translateUnusual } from '../i18n/serverText';
import { BatteryBar } from './BatteryBar';
import { useT } from './i18n';
import { IntegrationBadge } from './IntegrationBadge';
import { integrationLabel } from './labels';
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

function connectivityLabel(device: DeviceHealth, t: Translator): string {
  if (device.isOffline) return t.t('row.offline');
  if (device.isNotProvided) return t.t('row.not_provided');
  if (device.isQuiet) return t.t('row.quiet');
  return t.t('row.online');
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
  const t = useT();
  // The estimate: the fetched history's when it has one, else the device's own.
  const estimate = history?.estimate ?? device.estimate;
  const daysLeft = estimate?.daysLeft ?? device.daysLeft;
  const lastHeard = formatRelative(device.lastHeard, now, t);
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
        aria-label={t.t('row.open', { name: device.name })}
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
              <span className="badge" data-kind="charging" title={t.t('row.charging_title')}>
                ⚡ {t.t('row.charging')}
              </span>
            )}
            {device.snoozedUntil && (
              <span className="badge" data-kind="snoozed">
                💤{' '}
                {t.t('row.snoozed_until', {
                  date: device.snoozedUntil.toLocaleDateString(t.language),
                })}
              </span>
            )}
            {device.extras.map((extra) => (
              <span key={extra.label} className="badge" data-severity={extra.severity ?? 'ok'}>
                {extra.label}: {extra.value}
              </span>
            ))}
            {device.unusual !== undefined && (
              <span className="badge" data-severity="warning" title={t.t('row.unusual_title')}>
                ⚠ {translateUnusual(device.unusual, t)}
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
                {t.t('row.heard', { time: lastHeard })}
                {daysLeft !== undefined && !charging && (
                  <>
                    {' · '}
                    <span
                      title={
                        estimate
                          ? t.t(`row.estimate_${estimate.confidence}`, {
                              basis: translateBasis(estimate.basis, t),
                            })
                          : t.t('row.estimate_fallback')
                      }
                    >
                      {estimate?.kind === 'charge'
                        ? t.t('row.charge_in', { days: formatDaysLeft(daysLeft, t) })
                        : estimate?.openEnded
                          ? t.t('row.year_plus')
                          : t.t('row.left', { days: formatDaysLeft(daysLeft, t) })}
                    </span>
                  </>
                )}
              </span>
            </>
          ) : (
            <>
              <span className="label" data-severity={severity}>
                {connectivityLabel(device, t)}
              </span>
              <span className="sub">
                {device.isNotProvided
                  ? t.t('row.not_provided_by', {
                      integration: integrationLabel(device.integration, t),
                    })
                  : t.t('row.last_heard', { time: lastHeard })}
                {device.isQuiet &&
                  ` · ${t.t('row.limit', { hours: formatHours(device.quietThresholdHours, t) })}`}
              </span>
            </>
          )}
        </span>
      </button>

      {onDone !== undefined && (
        <button
          type="button"
          className="done"
          aria-label={t.t('row.done_label', { name: device.name })}
          title={t.t('row.done_title')}
          onClick={() => {
            onDone(device);
          }}
        >
          ✓ {t.t('row.done')}
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
