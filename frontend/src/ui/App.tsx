/**
 * The card's React root component.
 *
 * Responsibilities:
 *  - subscribe to the integration's snapshots (useSnapshot) and show a
 *    plain message while connecting or when the integration is missing
 *  - show the header with title, headline and breakdown
 *  - manage which tab is selected
 *  - hand each tab its sorted (and optionally grouped) list
 *  - turn snooze / unsnooze / done into service calls, and say when one fails
 *  - warn when the newest snapshot is old enough that the integration
 *    seems to have stopped updating
 *
 * Nothing is analysed here. The integration decided every device's
 * severity, days left and so on; the card orders, groups and draws.
 *
 * React note on `useMemo`: it caches the result of a calculation and only
 * recomputes when one of the listed dependencies changes, so sorting a
 * few hundred devices does not happen on every click.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ResolvedConfig, TabId } from '../card/config';
import {
  callPulseCheck,
  errorMessage,
  type PulseCheckService,
  type Snapshot,
} from '../card/snapshot';
import { filterActions, type ActionKind } from '../core/actions';
import { filterDevices } from '../core/filters';
import { batteryList, connectivityList } from '../core/sort';
import { breakdown, headline, summarise } from '../core/summarise';
import {
  connectivitySeverity,
  deviceBatterySeverity,
  hasConnectivityProblem,
} from '../core/thresholds';
import { formatClock, formatRelative } from '../core/time';
import type { DeviceHealth, HassBox } from '../core/types';
import { languageOf, translator } from '../i18n';
import { ActionsTab } from './ActionsTab';
import { DeviceRow } from './DeviceRow';
import { EmptyState } from './EmptyState';
import { GroupedRows } from './GroupedRows';
import { I18nContext } from './i18n';
import { useHistory, type HistoryRequest } from './useHistory';
import { CARD_VERSION } from '../version';
import { useNow } from './useNow';
import { useSnapshot } from './useSnapshot';

export interface AppProps {
  hassBox: HassBox;
  config: ResolvedConfig;
  /** Called when a row is tapped. The custom element wires this to HA navigation. */
  onOpenDevice?: ((device: DeviceHealth) => void) | undefined;
  /** Called with every snapshot, so the element can size itself. */
  onSnapshot?: ((snapshot: Snapshot) => void) | undefined;
}

const TAB_EMOJI: Record<TabId, string> = {
  batteries: '🔋',
  connectivity: '📡',
  actions: '🛠️',
};

/** How long the "Undo" after a Done stays on screen. */
export const UNDO_MS = 10_000;

/** How long a "could not snooze" style notice stays on screen. */
export const FAILURE_MS = 10_000;

/**
 * The integration recomputes at least every five minutes. A snapshot three
 * times that old means it has stopped (or the subscription has gone quiet).
 */
export const STALE_MS = 15 * 60 * 1000;

/** The last Done that the integration confirmed: which device and what. */
interface DoneRecord {
  device: DeviceHealth;
  kind: ActionKind;
}

/** A row action the integration refused, with its reason when it gave one. */
interface Failure {
  text: string;
  reason?: string | undefined;
}

export function App({ hassBox, config, onOpenDevice, onSnapshot }: AppProps) {
  const now = useNow();
  // The element re-renders when the user's language changes.
  const t = translator(languageOf(hassBox.latest));
  const connection = hassBox.latest?.connection;
  const { status, snapshot, error } = useSnapshot(hassBox, connection);

  // Tell the element about each new snapshot (it sizes itself from the
  // last one). React note: calling a parent's callback is a side effect,
  // and render must stay free of those (React may render more than once
  // per screen update), so it runs in an effect, after the render, and
  // only when `snapshot` is a new object.
  useEffect(() => {
    if (snapshot) onSnapshot?.(snapshot);
  }, [snapshot, onSnapshot]);

  // `useState` returns the current value and a setter. Calling the setter
  // re-renders this component with the new value.
  const [selected, setSelected] = useState<TabId>(config.default_tab);
  const [showSnoozed, setShowSnoozed] = useState(false);
  // If the config changes so the selected tab is hidden, fall back gracefully.
  const activeTab: TabId = config.show_tabs.includes(selected)
    ? selected
    : (config.show_tabs[0] ?? config.default_tab);

  // What this card shows: the integration's devices, through the card's
  // own view filters (a per-room card, a locks-only card).
  const areaNames = useMemo(() => {
    const areas = hassBox.latest?.areas ?? {};
    return Object.fromEntries(Object.values(areas).map((a) => [a.area_id, a.name]));
    // The registries only change on rename; re-reading them per snapshot is cheap.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hassBox, snapshot]);
  const devices = useMemo(
    () => filterDevices(snapshot?.devices ?? [], config, areaNames),
    [snapshot, config, areaNames],
  );
  const rules = useMemo(
    () => snapshot?.config ?? { battery_warning: 30, battery_critical: 15 },
    [snapshot],
  );

  // Sparkline history for the batteries on screen, from the integration.
  // A device's own `sparkline_days` setting (phones: 1 day) wins over the card's.
  const deviceSettings = snapshot?.deviceSettings;
  const requests = useMemo<HistoryRequest[]>(
    () =>
      devices.flatMap((d) =>
        d.battery?.level !== undefined
          ? [
              {
                entityId: d.battery.entityId,
                days: deviceSettings?.[d.deviceId]?.sparkline_days ?? config.sparkline_days,
              },
            ]
          : [],
      ),
    [devices, deviceSettings, config.sparkline_days],
  );
  const histories = useHistory(
    hassBox,
    requests,
    config.show_sparklines || config.sort === 'replace_soon',
  );

  const batteries = useMemo(
    () => batteryList(devices, rules, config.sort, histories),
    [devices, rules, config.sort, histories],
  );
  const problemBatteries = useMemo(
    () => batteries.filter((d) => deviceBatterySeverity(d, rules) !== 'ok'),
    [batteries, rules],
  );
  const shownBatteries = config.problems_only ? problemBatteries : batteries;
  const connectivity = useMemo(() => connectivityList(devices), [devices]);
  const snoozed = useMemo(() => devices.filter((d) => d.snoozedUntil), [devices]);
  const byId = useMemo(() => new Map(devices.map((d) => [d.deviceId, d])), [devices]);
  const summary = useMemo(() => summarise(devices, rules), [devices, rules]);
  const actions = useMemo(
    () =>
      filterActions(
        snapshot?.actions ?? { replace: [], charge: [], shopping: [] },
        new Set(byId.keys()),
      ),
    [snapshot, byId],
  );

  // A refused row action shows for a few seconds, then goes.
  const [failure, setFailure] = useState<Failure | null>(null);
  useEffect(() => {
    if (!failure) return;
    const timer = setTimeout(() => {
      setFailure(null);
    }, FAILURE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [failure]);

  // "Done" can be taken back for a few seconds.
  const [lastDone, setLastDone] = useState<DoneRecord | null>(null);
  useEffect(() => {
    if (!lastDone) return;
    const timer = setTimeout(() => {
      setLastDone(null);
    }, UNDO_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [lastDone]);

  // Snoozes and replacements are the integration's business: one service
  // call, and the next snapshot shows the result everywhere. If the call
  // is refused (the integration is reloading, the device is unknown, the
  // user may not call services), nothing would change on screen, so say so.
  // The failure text is worded when the user taps, in the language of the
  // moment; `t` is cached per language, so listing it as a dependency only
  // rebuilds these callbacks when the language changes.
  const runAction = useCallback(
    (
      service: PulseCheckService,
      data: Record<string, unknown>,
      failText: string,
      onDone?: () => void,
    ) => {
      callPulseCheck(hassBox.latest, service, data).then(
        () => {
          onDone?.();
        },
        (err: unknown) => {
          setFailure({ text: failText, reason: errorMessage(err) });
        },
      );
    },
    [hassBox],
  );

  const handleSnooze = useCallback(
    (device: DeviceHealth, days: number) => {
      runAction(
        'snooze',
        { device_id: device.deviceId, days },
        t.t('failed.snooze', { name: device.name }),
      );
    },
    [runAction, t],
  );
  const handleUnsnooze = useCallback(
    (device: DeviceHealth) => {
      runAction(
        'unsnooze',
        { device_id: device.deviceId },
        t.t('failed.unsnooze', { name: device.name }),
      );
    },
    [runAction, t],
  );

  const handleDone = useCallback(
    (device: DeviceHealth, kind: ActionKind) => {
      const service = kind === 'charge' ? 'mark_charged' : 'mark_replaced';
      const failKey = kind === 'charge' ? 'failed.charged' : 'failed.replaced';
      setLastDone(null);
      // "Marked … Undo" only once the integration has recorded it: undoing
      // a mark that never landed would find nothing to undo.
      runAction(
        service,
        { device_id: device.deviceId },
        t.t(failKey, { name: device.name }),
        () => {
          setLastDone({ device, kind });
        },
      );
    },
    [runAction, t],
  );

  const handleUndo = useCallback(() => {
    if (!lastDone) return;
    const { device } = lastDone;
    setLastDone(null);
    runAction(
      'undo_mark',
      { device_id: device.deviceId },
      t.t('failed.undo', { name: device.name }),
    );
  }, [runAction, t, lastDone]);

  if (status !== 'ready' || !snapshot) {
    return (
      <div className="card">
        {status === 'loading' && (
          <EmptyState
            emoji="⏳"
            lead={t.t('app.connecting')}
            detail={t.t('app.connecting_detail')}
          />
        )}
        {status === 'missing' && (
          <EmptyState emoji="🔌" lead={t.t('app.missing')} detail={t.t('app.missing_detail')} />
        )}
        {status === 'error' && (
          <EmptyState
            emoji="⚠️"
            lead={t.t('app.error')}
            detail={error ?? t.t('app.error_detail')}
          />
        )}
      </div>
    );
  }

  const tabCounts: Record<TabId, number> = {
    batteries: summary.lowBatteries,
    connectivity: connectivity.length,
    actions: actions.replace.length + actions.charge.length,
  };
  const headlineSeverity =
    summary.critical > 0 ? 'critical' : summary.warning > 0 ? 'warning' : 'ok';
  const detail = breakdown(summary, t);

  const rowProps = {
    now,
    onOpen: onOpenDevice,
    onSnooze: handleSnooze,
    onUnsnooze: handleUnsnooze,
  };

  // React note: `<I18nContext value={t}>` provides the translator to every
  // component below it (see ./i18n.ts).
  return (
    <I18nContext value={t}>
      <div className="card">
        <header className="header" data-untitled={config.title === '' ? 'true' : undefined}>
          {config.title !== '' && <h2 className="title">{config.title}</h2>}
          <div className="verdict">
            <p className="headline" data-severity={headlineSeverity} aria-live="polite">
              {headline(summary, t)}
            </p>
            {detail && <p className="breakdown">{detail}</p>}
          </div>
        </header>

        {snapshot.maintenanceUntil && snapshot.maintenanceUntil > now && (
          <p className="maintenance" role="status">
            🔧{' '}
            {t.t('app.maintenance', {
              time: formatClock(snapshot.maintenanceUntil, now, t.language),
            })}
          </p>
        )}

        {snapshot.computedAt && now.getTime() - snapshot.computedAt.getTime() > STALE_MS && (
          <p className="notice" role="status" data-kind="warning">
            <span>
              ⏱️ {t.t('app.stale', { time: formatRelative(snapshot.computedAt, now, t) })}
            </span>
          </p>
        )}

        {snapshot.version !== undefined && snapshot.version !== CARD_VERSION && (
          <p className="notice" role="status">
            <span>⬆️ {t.t('app.updated', { version: snapshot.version })}</span>
            <button
              type="button"
              className="noticebutton"
              onClick={() => {
                window.location.reload();
              }}
            >
              {t.t('app.refresh')}
            </button>
          </p>
        )}

        {config.show_tabs.length > 1 && (
          <div className="tabs" role="tablist" aria-label={t.t('app.tabs_label')}>
            {config.show_tabs.map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                className="tab"
                id={`tab-${tab}`}
                aria-selected={tab === activeTab}
                aria-controls={`panel-${tab}`}
                onClick={() => {
                  setSelected(tab);
                }}
              >
                {TAB_EMOJI[tab]} {t.t(`tab.${tab}`)}
                {tabCounts[tab] > 0 && <span className="count">{tabCounts[tab]}</span>}
              </button>
            ))}
          </div>
        )}

        <div role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`}>
          {activeTab === 'batteries' &&
            (batteries.length === 0 ? (
              <EmptyState
                emoji="🔌"
                lead={t.t('empty.no_batteries')}
                detail={t.t('empty.no_batteries_detail')}
              />
            ) : shownBatteries.length === 0 ? (
              <EmptyState
                emoji="✅"
                lead={t.t('empty.batteries_ok')}
                detail={t.t('empty.batteries_ok_detail')}
              />
            ) : (
              <GroupedRows
                items={shownBatteries}
                groupBy={config.group_by}
                maxRows={config.max_rows}
                resetKey="batteries"
                renderRow={(d) => (
                  <DeviceRow
                    key={d.deviceId}
                    device={d}
                    severity={deviceBatterySeverity(d, rules)}
                    mode="battery"
                    history={d.battery ? histories?.get(d.battery.entityId) : undefined}
                    sparkline={config.show_sparklines}
                    {...rowProps}
                  />
                )}
              />
            ))}

          {activeTab === 'connectivity' &&
            (connectivity.length === 0 ? (
              <EmptyState
                emoji="✅"
                lead={t.t('empty.online')}
                detail={t.t('empty.online_detail')}
              />
            ) : (
              <GroupedRows
                items={connectivity}
                groupBy={config.group_by}
                maxRows={config.max_rows}
                resetKey="connectivity"
                renderRow={(d) => (
                  <DeviceRow
                    key={d.deviceId}
                    device={d}
                    severity={connectivitySeverity(d.isOffline, d.isQuiet, d.isNotProvided)}
                    mode="connectivity"
                    {...rowProps}
                  />
                )}
              />
            ))}

          {activeTab === 'actions' && (
            <ActionsTab actions={actions} devices={byId} onDone={handleDone} {...rowProps} />
          )}

          {lastDone && (
            <p className="notice" role="status">
              <span>
                {t.t(lastDone.kind === 'charge' ? 'undo.charged' : 'undo.replaced', {
                  name: lastDone.device.name,
                })}
              </span>
              <button type="button" className="noticebutton" onClick={handleUndo}>
                {t.t('undo.undo')}
              </button>
            </p>
          )}

          {failure && (
            <p className="notice" role="alert" data-kind="error">
              <span>
                ⚠️ {failure.text}
                {failure.reason !== undefined && ` ${failure.reason}`}
              </span>
            </p>
          )}
        </div>

        {snoozed.length > 0 && activeTab !== 'batteries' && (
          <footer className="footer">
            <button
              type="button"
              className="footerbutton"
              aria-expanded={showSnoozed}
              onClick={() => {
                setShowSnoozed((s) => !s);
              }}
            >
              💤 {t.tn('app.snoozed', snoozed.length)} ·{' '}
              {showSnoozed ? t.t('app.hide') : t.t('app.show')}
            </button>
            {showSnoozed && (
              <ul className="rows">
                {snoozed.map((d) => (
                  <DeviceRow
                    key={d.deviceId}
                    device={d}
                    severity="ok"
                    mode={hasConnectivityProblem(d) ? 'connectivity' : 'battery'}
                    {...rowProps}
                  />
                ))}
              </ul>
            )}
          </footer>
        )}
      </div>
    </I18nContext>
  );
}
