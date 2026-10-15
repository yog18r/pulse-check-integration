/**
 * The card's React root component.
 *
 * Responsibilities:
 *  - subscribe to the integration's snapshots (useSnapshot) and show a
 *    plain message while connecting or when the integration is missing
 *  - show the header with title, headline and breakdown
 *  - manage which tab is selected
 *  - hand each tab its sorted (and optionally grouped) list
 *  - turn snooze / unsnooze / done into service calls
 *
 * Nothing is analysed here. The integration decided every device's
 * severity, days left and so on; the card orders, groups and draws.
 *
 * React note on `useMemo`: it caches the result of a calculation and only
 * recomputes when one of the listed dependencies changes, so sorting a
 * few hundred devices does not happen on every click.
 */
import { useCallback, useMemo, useState } from 'react';
import type { ResolvedConfig, TabId } from '../card/config';
import { callPulseCheck, type Snapshot } from '../card/snapshot';
import { filterActions, type ActionKind } from '../core/actions';
import { filterDevices } from '../core/filters';
import { batteryList, connectivityList } from '../core/sort';
import { breakdown, headline, summarise } from '../core/summarise';
import { batterySeverity, connectivitySeverity } from '../core/thresholds';
import { formatClock } from '../core/time';
import type { DeviceHealth, HassBox } from '../core/types';
import { languageOf, translator } from '../i18n';
import { ActionsTab } from './ActionsTab';
import { DeviceRow } from './DeviceRow';
import { EmptyState } from './EmptyState';
import { GroupedRows } from './GroupedRows';
import { I18nContext } from './i18n';
import { useHistory, type HistoryRequest } from './useHistory';
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

export function App({ hassBox, config, onOpenDevice, onSnapshot }: AppProps) {
  const now = useNow();
  // The element re-renders when the user's language changes.
  const t = translator(languageOf(hassBox.latest));
  const connection = hassBox.latest?.connection;
  const { status, snapshot, error } = useSnapshot(hassBox, connection);
  if (snapshot) onSnapshot?.(snapshot);

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
    () => batteries.filter((d) => batterySeverity(d.battery, rules) !== 'ok'),
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

  // Snoozes and replacements are the integration's business: one service
  // call, and the next snapshot shows the result everywhere.
  const handleSnooze = useCallback(
    (device: DeviceHealth, days: number) => {
      void callPulseCheck(hassBox.latest, 'snooze', { device_id: device.deviceId, days });
    },
    [hassBox],
  );
  const handleUnsnooze = useCallback(
    (device: DeviceHealth) => {
      void callPulseCheck(hassBox.latest, 'unsnooze', { device_id: device.deviceId });
    },
    [hassBox],
  );
  const handleDone = useCallback(
    (device: DeviceHealth, kind: ActionKind) => {
      const service = kind === 'charge' ? 'mark_charged' : 'mark_replaced';
      void callPulseCheck(hassBox.latest, service, { device_id: device.deviceId });
    },
    [hassBox],
  );

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
                    severity={batterySeverity(d.battery, rules)}
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
                    severity={connectivitySeverity(d.isOffline, d.isQuiet)}
                    mode="connectivity"
                    {...rowProps}
                  />
                )}
              />
            ))}

          {activeTab === 'actions' && (
            <ActionsTab actions={actions} devices={byId} onDone={handleDone} {...rowProps} />
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
                    mode={d.isOffline || d.isQuiet ? 'connectivity' : 'battery'}
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
