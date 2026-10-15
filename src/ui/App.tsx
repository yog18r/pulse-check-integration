/**
 * The card's React root component.
 *
 * Responsibilities:
 *  - run the core analysis (memoised, so it only re-runs when inputs change)
 *  - show the header with title, headline and breakdown
 *  - manage which tab is selected
 *  - hand each tab its sorted list
 *  - own the three bits of browser-side state: snoozes, drain estimates
 *    and on-demand last_reported lookups
 *
 * React note on `useMemo`: it caches the result of a calculation and only
 * recomputes when one of the listed dependencies changes. `analyseDevices`
 * walks every entity in the house, so we do not want to run it on every
 * render (e.g. when the user merely clicks a tab).
 */
import { useCallback, useMemo, useState } from 'react';
import type { ResolvedConfig, TabId } from '../card/config';
import { callPulseCheck, readIntegration } from '../card/integration';
import type { BatteryEntity } from '../card/statistics';
import type { ActionKind } from '../core/actions';
import { analyseDevices, lastReportedCandidates } from '../core/analyse';
import { actionList } from '../core/actions';
import { batteryList, connectivityList } from '../core/sort';
import { settingsForDevice } from '../core/settings';
import { breakdown, headline, summarise } from '../core/summarise';
import { batterySeverity, connectivitySeverity } from '../core/thresholds';
import type { DeviceHealth, HassLike } from '../core/types';
import type { Enhancer } from '../enhancers';
import { DeviceRow } from './DeviceRow';
import { EmptyState } from './EmptyState';
import { GroupedRows } from './GroupedRows';
import { ActionsTab } from './ActionsTab';
import { useDrainEstimates } from './useDrainEstimates';
import { useLastReported } from './useLastReported';
import { useNow } from './useNow';
import { useSnoozes } from './useSnoozes';

export interface AppProps {
  hass: HassLike;
  config: ResolvedConfig;
  enhancers: readonly Enhancer[];
  /** Called when a row is tapped. The custom element wires this to HA navigation. */
  onOpenDevice?: ((device: DeviceHealth) => void) | undefined;
}

const TAB_LABELS: Record<TabId, string> = {
  batteries: '🔋 Batteries',
  connectivity: '📡 Connectivity',
  actions: '🛠️ Actions',
};

export function App({ hass, config, enhancers, onOpenDevice }: AppProps) {
  const now = useNow();
  const { snoozes, snooze, unsnooze } = useSnoozes();

  // `useState` returns the current value and a setter. Calling the setter
  // re-renders this component with the new value.
  const [selected, setSelected] = useState<TabId>(config.default_tab);
  const [showSnoozed, setShowSnoozed] = useState(false);
  // If the config changes so the selected tab is hidden, fall back gracefully.
  const activeTab: TabId = config.show_tabs.includes(selected)
    ? selected
    : (config.show_tabs[0] ?? config.default_tab);

  // Integration mode: the server already did the analysis (and holds the
  // snoozes), so the browser only reads the sensor's attributes.
  const integrationMode = config.source === 'integration';
  const integration = useMemo(
    () => (integrationMode ? readIntegration(hass, config.integration_entity) : undefined),
    [integrationMode, hass, config.integration_entity],
  );

  // The thresholds and per-device settings the rules run with. In
  // integration mode they come from the integration, so rows, counts and
  // action labels agree with the header it computed. The card's own YAML
  // keeps only its presentation keys (title, tabs, row cap, sort, grouping).
  const rules = useMemo<ResolvedConfig>(
    () => (integration?.config ? { ...config, ...integration.config } : config),
    [integration, config],
  );

  // Standalone: first pass decides which devices look quiet from frontend data alone...
  const firstPass = useMemo(
    () => (integrationMode ? [] : analyseDevices(hass, config, { now, enhancers, snoozes })),
    [integrationMode, hass, config, now, enhancers, snoozes],
  );
  // ...those are the only entities worth asking the server about...
  const candidates = useMemo(() => lastReportedCandidates(firstPass, hass), [firstPass, hass]);
  const lastReported = useLastReported(hass, candidates);
  // ...and the answers feed the real analysis. Same function, one more input.
  const devices = useMemo(() => {
    if (integrationMode) return integration?.devices ?? [];
    return lastReported.size === 0
      ? firstPass
      : analyseDevices(hass, config, { now, enhancers, snoozes, lastReported });
  }, [
    integrationMode,
    integration,
    firstPass,
    hass,
    config,
    now,
    enhancers,
    snoozes,
    lastReported,
  ]);

  // Battery sensors with a numeric level are candidates for drain estimates.
  const batteryEntities = useMemo<BatteryEntity[]>(
    () =>
      devices.flatMap((d) =>
        d.battery?.level !== undefined
          ? [
              {
                entityId: d.battery.entityId,
                level: d.battery.level,
                days:
                  settingsForDevice(config, d.deviceId)?.sparkline_days ?? config.sparkline_days,
              },
            ]
          : [],
      ),
    [devices, config],
  );
  const drains = useDrainEstimates(hass, batteryEntities);

  const batteries = useMemo(() => batteryList(devices, rules, drains), [devices, rules, drains]);
  const problemBatteries = useMemo(
    () => batteries.filter((d) => batterySeverity(d.battery, rules) !== 'ok'),
    [batteries, rules],
  );
  const shownBatteries = config.problems_only ? problemBatteries : batteries;
  const connectivity = useMemo(() => connectivityList(devices), [devices]);
  const actions = useMemo(() => actionList(devices, rules), [devices, rules]);
  const summary = useMemo(() => summarise(devices, rules), [devices, rules]);
  const snoozed = useMemo(() => devices.filter((d) => d.snoozedUntil), [devices]);

  // Snoozes: browser-local in standalone mode, shared via the integration's
  // services in integration mode (the sensor then reports them back).
  const handleSnooze = useCallback(
    (device: DeviceHealth, days: number) => {
      if (integrationMode) {
        void callPulseCheck(hass, 'snooze', { device_id: device.deviceId, days });
      } else {
        snooze(device.deviceId, days);
      }
    },
    [integrationMode, hass, snooze],
  );
  const handleUnsnooze = useCallback(
    (device: DeviceHealth) => {
      if (integrationMode) {
        void callPulseCheck(hass, 'unsnooze', { device_id: device.deviceId });
      } else {
        unsnooze(device.deviceId);
      }
    },
    [integrationMode, hass, unsnooze],
  );
  // "Done" on the Actions tab records a replacement or charge. Only the
  // integration can remember that, so standalone mode does not offer it.
  const handleDone = useCallback(
    (device: DeviceHealth, kind: ActionKind) => {
      const service = kind === 'charge' ? 'mark_charged' : 'mark_replaced';
      void callPulseCheck(hass, service, { device_id: device.deviceId });
    },
    [hass],
  );

  const tabCounts: Record<TabId, number> = {
    batteries: summary.lowBatteries,
    connectivity: connectivity.length,
    actions: actions.replace.length + actions.charge.length,
  };

  const headlineSeverity =
    summary.critical > 0 ? 'critical' : summary.warning > 0 ? 'warning' : 'ok';
  const detail = breakdown(summary);

  if (integrationMode && integration === undefined) {
    return (
      <div className="card">
        <EmptyState
          emoji="🔌"
          lead="Pulse Check integration not found"
          detail={`No ${config.integration_entity}. Install the integration, or set source: standalone.`}
        />
      </div>
    );
  }

  const rowProps = {
    now,
    onOpen: onOpenDevice,
    onSnooze: handleSnooze,
    onUnsnooze: handleUnsnooze,
  };

  return (
    <div className="card">
      <header className="header" data-untitled={config.title === '' ? 'true' : undefined}>
        {config.title !== '' && <h2 className="title">{config.title}</h2>}
        <div className="verdict">
          <p className="headline" data-severity={headlineSeverity} aria-live="polite">
            {headline(summary)}
          </p>
          {detail && <p className="breakdown">{detail}</p>}
        </div>
      </header>

      {config.show_tabs.length > 1 && (
        <div className="tabs" role="tablist" aria-label="Device health views">
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
              {TAB_LABELS[tab]}
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
              lead="No battery-powered devices"
              detail="Nothing here runs on batteries."
            />
          ) : shownBatteries.length === 0 ? (
            <EmptyState
              emoji="✅"
              lead="No battery problems"
              detail="Every battery is above the warning threshold."
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
                  history={d.battery ? drains?.get(d.battery.entityId) : undefined}
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
              lead="All devices online"
              detail="No devices are offline or unusually quiet."
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
          <ActionsTab
            actions={actions}
            onDone={integrationMode ? handleDone : undefined}
            {...rowProps}
          />
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
            💤 {snoozed.length} snoozed · {showSnoozed ? 'hide' : 'show'}
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
  );
}
