/**
 * Local demo page. Renders the real card element with mock `hass` data, so
 * the card can be developed and shown off without a Home Assistant instance.
 *
 * Run with `npm run dev`.
 */
import '../index';
import type { CardConfig } from '../card/config';
import type { HassLike } from '../core/types';
import { buildHass } from '../../test/fixtures/hass';

type Scenario = 'default' | 'tuned' | 'shopping' | 'healthy' | 'broken';

const CONFIGS: Record<Scenario, unknown> = {
  default: { type: 'custom:pulse-check-card' } satisfies CardConfig,
  tuned: {
    type: 'custom:pulse-check-card',
    title: 'Device Health',
    battery_warning: 35,
    battery_critical: 20,
    integration_thresholds: { zwave_js: 48 },
    quiet_scope: 'all',
    exclude_integrations: ['mobile_app'],
    default_tab: 'connectivity',
  } satisfies CardConfig,
  shopping: {
    type: 'custom:pulse-check-card',
    title: 'Battery Shop',
    battery_sort: 'replace_soon',
    show_tabs: ['batteries', 'shopping'],
    default_tab: 'shopping',
    device_overrides: [
      { device_id: 'dev_z2m_motion', battery_type: 'CR2450' },
      { device_id: 'dev_zha_temp', battery_type: 'CR2032' },
      { device_id: 'dev_smoke_alarm', battery_type: 'CR2032' },
    ],
  } satisfies CardConfig,
  healthy: { type: 'custom:pulse-check-card', title: 'All good' } satisfies CardConfig,
  broken: { type: 'custom:pulse-check-card', battery_warning: 'thirty' },
};

/** The "healthy" scenario: same fixture, but every device fresh and charged. */
function healthyHass(now: Date): HassLike {
  const base = buildHass(now);
  const states = Object.fromEntries(
    Object.entries(base.states).map(([id, s]) => {
      const fixed = { ...s, last_updated: now.toISOString(), last_changed: now.toISOString() };
      if (s.state === 'unavailable') fixed.state = 'on';
      if (s.attributes.device_class === 'battery') {
        fixed.state = id.startsWith('binary_sensor.') ? 'off' : '95';
      }
      if (typeof s.attributes.battery_level === 'number') {
        fixed.attributes = { ...s.attributes, battery_level: 95 };
      }
      return [id, fixed];
    }),
  );
  return { ...base, states };
}

/**
 * A fake `callWS` standing in for Home Assistant's websocket. It answers the
 * one command the card sends (recorder statistics) with 14 days of made-up
 * daily means, so "~12d left" labels and the replace-soon order can be seen.
 */
const DAY = 24 * 60 * 60 * 1000;
const DRAIN_PER_DAY: Record<string, number> = {
  'sensor.front_door_battery': 0.4, // slow: months left
  'sensor.living_room_motion_battery': 2.5, // fast: days left
  'sensor.bedroom_climate_battery': 1.2,
  'sensor.window_sensor_battery': 3, // 40% but draining fast: replace before the 28% one
  'sensor.kitchen_ht_battery': 0.3,
  'sensor.garage_multisensor_battery_level': 0.8,
  'sensor.remote_battery_template': 0.5,
  // phones and the dog tracker get charged: flat history, no estimate
};

function fakeCallWS<T>(message: Record<string, unknown>): Promise<T> {
  if (message.type !== 'recorder/statistics_during_period') {
    return Promise.reject(new Error(`demo: unsupported command ${String(message.type)}`));
  }
  const now = Date.now();
  const ids = message.statistic_ids as string[];
  const current = buildHass(new Date()).states;
  const response: Record<string, { start: number; end: number; mean: number }[]> = {};
  for (const id of ids) {
    const rate = DRAIN_PER_DAY[id] ?? 0;
    const level = Number(current[id]?.state ?? 50);
    response[id] = Array.from({ length: 14 }, (_, i) => {
      const daysAgo = 14 - i;
      const start = now - daysAgo * DAY;
      return { start, end: start + DAY, mean: level + daysAgo * rate };
    });
  }
  // A little latency, like the real thing.
  return new Promise((resolve) =>
    setTimeout(() => {
      resolve(response as T);
    }, 300),
  );
}

interface CardLike extends HTMLElement {
  setConfig(config: unknown): void;
  hass: HassLike;
}

/** Look up a required element, failing loudly if the HTML and script drift apart. */
function mustGet(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Demo page is missing #${id}`);
  return el;
}

const host = mustGet('card-host');
const scenarioSelect = mustGet('scenario') as HTMLSelectElement;
const themeButton = mustGet('theme');

function mount(scenario: Scenario) {
  host.replaceChildren();
  const now = new Date();
  const card = document.createElement('pulse-check-card') as CardLike;

  try {
    card.setConfig(CONFIGS[scenario]);
  } catch (err) {
    // Mirror what HA does: show the thrown message in place of the card.
    const pre = document.createElement('pre');
    pre.style.color = 'var(--error-color)';
    pre.textContent = `Card error: ${err instanceof Error ? err.message : String(err)}`;
    host.appendChild(pre);
    return;
  }

  card.hass = withWS(scenario === 'healthy' ? healthyHass(now) : buildHass(now));
  host.appendChild(card);

  // Simulate HA pushing a fresh hass object every few seconds. The card's
  // fingerprint check means this does NOT cause a React re-render unless a
  // relevant entity actually changed; open devtools to verify.
  const timer = setInterval(() => {
    if (!card.isConnected) {
      clearInterval(timer);
      return;
    }
    card.hass = withWS(scenario === 'healthy' ? healthyHass(new Date()) : buildHass(new Date()));
  }, 5000);

  mountEditor(CONFIGS[scenario] as CardConfig);
}

/**
 * A fake REST API for the on-demand last_reported lookup. The ZHA bedroom
 * sensor's temperature entity "reported" (unchanged) two hours ago even
 * though its value last changed 30h ago, so after the lookup it stops
 * being quiet. Everything else just echoes the frontend's last_updated.
 */
function fakeCallApi<T>(method: string, path: string): Promise<T> {
  if (method !== 'GET' || !path.startsWith('states/')) {
    return Promise.reject(new Error(`demo: unsupported ${method} ${path}`));
  }
  const entityId = decodeURIComponent(path.slice('states/'.length));
  const state = buildHass(new Date()).states[entityId];
  if (!state) return Promise.reject(new Error('404'));
  const lastReported =
    entityId === 'sensor.bedroom_climate_temperature'
      ? new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
      : state.last_updated;
  return new Promise((resolve) =>
    setTimeout(() => {
      resolve({ entity_id: entityId, last_reported: lastReported } as T);
    }, 200),
  );
}

function withWS(h: HassLike): HassLike {
  return { ...h, callWS: fakeCallWS, callApi: fakeCallApi };
}

interface EditorLike extends HTMLElement {
  setConfig(config: CardConfig): void;
  hass: HassLike;
}

/** Render the visual editor next to the card and echo what it emits. */
function mountEditor(config: CardConfig) {
  const editorHost = mustGet('editor-host');
  const output = mustGet('editor-output');
  editorHost.replaceChildren();
  const editor = document.createElement('pulse-check-card-editor') as EditorLike;
  editor.setConfig(config);
  editor.hass = withWS(buildHass(new Date()));
  editor.addEventListener('config-changed', (event) => {
    const detail = (event as CustomEvent<{ config: CardConfig }>).detail;
    output.textContent = JSON.stringify(detail.config, null, 2);
    // Live preview, the way HA does it.
    const card = host.querySelector<CardLike>('pulse-check-card');
    try {
      card?.setConfig(detail.config);
    } catch {
      // The editor shows the validation message itself.
    }
  });
  editorHost.appendChild(editor);
  output.textContent = JSON.stringify(config, null, 2);
}

scenarioSelect.addEventListener('change', () => {
  mount(scenarioSelect.value as Scenario);
});

themeButton.addEventListener('click', () => {
  const dark = document.body.dataset.theme === 'dark';
  document.body.dataset.theme = dark ? 'light' : 'dark';
});

/**
 * Home Assistant handles these two events; here we just show what the card
 * asked for, so tap-to-open can be seen working without HA.
 */
function toast(message: string) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, 2500);
}

window.addEventListener('location-changed', () => {
  toast(`HA would navigate to ${location.pathname}`);
  history.replaceState(null, '', '/');
});

document.addEventListener('hass-more-info', (event) => {
  const detail = (event as CustomEvent<{ entityId: string }>).detail;
  toast(`HA would open more-info for ${detail.entityId}`);
});

if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
  document.body.dataset.theme = 'dark';
}

mount('default');
