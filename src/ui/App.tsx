/**
 * The card's React root component.
 *
 * Responsibilities:
 *  - run the core analysis (memoised, so it only re-runs when inputs change)
 *  - show the header with title, headline and breakdown
 *  - manage which tab is selected
 *  - hand each tab its sorted list
 *
 * React note on `useMemo`: it caches the result of a calculation and only
 * recomputes when one of the listed dependencies changes. `analyseDevices`
 * walks every entity in the house, so we do not want to run it on every
 * render (e.g. when the user merely clicks a tab).
 */
import { useMemo, useState } from 'react';
import type { ResolvedConfig, TabId } from '../card/config';
import type { BatteryEntity } from '../card/statistics';
import { analyseDevices } from '../core/analyse';
import { shoppingList } from '../core/shopping';
import { batteryList, connectivityList } from '../core/sort';
import { breakdown, headline, summarise } from '../core/summarise';
import { batterySeverity, connectivitySeverity } from '../core/thresholds';
import type { DeviceHealth, HassLike } from '../core/types';
import type { Enhancer } from '../enhancers';
import { DeviceRow } from './DeviceRow';
import { EmptyState } from './EmptyState';
import { ShoppingTab } from './ShoppingTab';
import { useDrainEstimates } from './useDrainEstimates';
import { useNow } from './useNow';

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
  shopping: '🛒 Shopping',
};

export function App({ hass, config, enhancers, onOpenDevice }: AppProps) {
  const now = useNow();

  // `useState` returns the current value and a setter. Calling the setter
  // re-renders this component with the new value.
  const [selected, setSelected] = useState<TabId>(config.default_tab);
  // If the config changes so the selected tab is hidden, fall back gracefully.
  const activeTab: TabId = config.show_tabs.includes(selected)
    ? selected
    : (config.show_tabs[0] ?? config.default_tab);

  const devices = useMemo(
    () => analyseDevices(hass, config, { now, enhancers }),
    [hass, config, now, enhancers],
  );

  // Battery sensors with a numeric level are candidates for drain estimates.
  const batteryEntities = useMemo<BatteryEntity[]>(
    () =>
      devices.flatMap((d) =>
        d.battery?.level !== undefined
          ? [{ entityId: d.battery.entityId, level: d.battery.level }]
          : [],
      ),
    [devices],
  );
  const drains = useDrainEstimates(hass, batteryEntities);

  const batteries = useMemo(() => batteryList(devices, config, drains), [devices, config, drains]);
  const connectivity = useMemo(() => connectivityList(devices), [devices]);
  const shopping = useMemo(() => shoppingList(devices, config), [devices, config]);
  const summary = useMemo(() => summarise(devices, config), [devices, config]);

  const tabCounts: Record<TabId, number> = {
    batteries: summary.lowBatteries,
    connectivity: connectivity.length,
    shopping: shopping.reduce((n, g) => n + g.devices.length, 0),
  };

  const headlineSeverity =
    summary.critical > 0 ? 'critical' : summary.warning > 0 ? 'warning' : 'ok';
  const detail = breakdown(summary);

  return (
    <div className="card">
      <header className="header">
        <h2 className="title">{config.title}</h2>
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
              lead="No battery-powered devices found"
              detail="Everything here runs on mains power. Lucky you."
            />
          ) : (
            <ul className="rows">
              {batteries.map((d) => (
                <DeviceRow
                  key={d.deviceId}
                  device={d}
                  severity={batterySeverity(d.battery, config)}
                  mode="battery"
                  now={now}
                  drain={d.battery ? drains?.get(d.battery.entityId) : undefined}
                  onOpen={onOpenDevice}
                />
              ))}
            </ul>
          ))}

        {activeTab === 'connectivity' &&
          (connectivity.length === 0 ? (
            <EmptyState
              emoji="🎉"
              lead="Everyone's checked in"
              detail="No devices are offline or unusually quiet."
            />
          ) : (
            <ul className="rows">
              {connectivity.map((d) => (
                <DeviceRow
                  key={d.deviceId}
                  device={d}
                  severity={connectivitySeverity(d.isOffline, d.isQuiet)}
                  mode="connectivity"
                  now={now}
                  onOpen={onOpenDevice}
                />
              ))}
            </ul>
          ))}

        {activeTab === 'shopping' && (
          <ShoppingTab groups={shopping} config={config} now={now} onOpen={onOpenDevice} />
        )}
      </div>
    </div>
  );
}
