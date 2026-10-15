/**
 * Local demo page. Renders the real card element against a fake Home
 * Assistant whose websocket "subscription" replays a canned snapshot, so
 * the card can be developed and shown off without a Home Assistant
 * instance or the integration.
 *
 * Run with `npm run dev`.
 */
import '../index';
import type { CardConfig } from '../card/config';
import type { HassConnection, HassLike } from '../core/types';
import { buildHass } from '../../test/fixtures/hass';
import payload from '../../test/fixtures/snapshot.json';

type Scenario = 'default' | 'grouped' | 'actions' | 'healthy' | 'missing' | 'broken';

const CONFIGS: Record<Scenario, unknown> = {
  default: { type: 'custom:pulse-check-card' } satisfies CardConfig,
  grouped: {
    type: 'custom:pulse-check-card',
    title: 'Device Health',
    group_by: 'area',
    max_rows: 5,
    default_tab: 'connectivity',
  } satisfies CardConfig,
  actions: {
    type: 'custom:pulse-check-card',
    title: 'Battery Jobs',
    battery_sort: 'replace_soon',
    show_tabs: ['batteries', 'actions'],
    default_tab: 'actions',
  } satisfies CardConfig,
  healthy: { type: 'custom:pulse-check-card', title: 'All good' } satisfies CardConfig,
  missing: { type: 'custom:pulse-check-card', title: 'No integration' } satisfies CardConfig,
  broken: { type: 'custom:pulse-check-card', group_by: 'colour' },
};

const COMPUTED_AT = new Date(payload.computed_at).getTime();
const DAY = 24 * 60 * 60 * 1000;

/** Shift every timestamp in the canned snapshot so "heard 3h ago" stays true today. */
function shifted(raw: Record<string, unknown>, offset: number): Record<string, unknown> {
  const devices = (raw.devices as Record<string, unknown>[]).map((d) => {
    const out = { ...d };
    for (const key of ['lastHeard', 'snoozedUntil', 'lastReplaced']) {
      if (typeof out[key] === 'string') {
        out[key] = new Date(new Date(out[key]).getTime() + offset).toISOString();
      }
    }
    return out;
  });
  return { ...raw, devices, computed_at: new Date(COMPUTED_AT + offset).toISOString() };
}

/** The "healthy" scenario: no devices in trouble. */
function healthy(raw: Record<string, unknown>): Record<string, unknown> {
  const devices = (raw.devices as Record<string, unknown>[]).map((d) => {
    const battery = d.battery as Record<string, unknown> | undefined;
    return {
      ...d,
      severity: 'ok',
      isOffline: false,
      isQuiet: false,
      battery: battery ? { ...battery, level: 95, isLow: false } : undefined,
    };
  });
  const summary = { ...(raw.summary as object), attention: 0, critical: 0, warning: 0 };
  return { ...raw, devices, summary: { ...summary, lowBatteries: 0, offline: 0, quiet: 0 } };
}

/**
 * A fake subscription: sends the snapshot now and again whenever a service
 * call changes it (snooze, mark replaced), the way the integration does.
 */
function fakeConnection(scenario: Scenario): {
  connection: HassConnection;
  mutate: (fn: (s: Record<string, unknown>) => void) => void;
} {
  let current = shifted(payload, Date.now() - COMPUTED_AT);
  if (scenario === 'healthy') current = healthy(current);
  let subscriber: ((message: unknown) => void) | undefined;
  const connection: HassConnection = {
    subscribeMessage(callback: (message: unknown) => void) {
      if (scenario === 'missing') {
        // Home Assistant rejects with a plain { code, message } object, not an Error.
        // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
        return Promise.reject({ code: 'not_loaded', message: 'Pulse Check is not set up' });
      }
      subscriber = callback;
      setTimeout(() => subscriber?.(current), 300);
      return Promise.resolve(() => {
        subscriber = undefined;
        return Promise.resolve();
      });
    },
  };
  return {
    connection,
    mutate: (fn) => {
      const next = structuredClone(current);
      fn(next);
      current = next;
      subscriber?.(current);
    },
  };
}

const DRAIN_PER_DAY: Record<string, number> = {
  'sensor.front_door_battery': 0.4,
  'sensor.living_room_motion_battery': 2.5,
  'sensor.bedroom_climate_battery': 1.2,
  'sensor.window_sensor_battery': 3,
  'sensor.kitchen_ht_battery': 0.3,
  'sensor.garage_multisensor_battery_level': 0.8,
  'sensor.remote_battery_template': 0.5,
};

/** Fake `pulse_check/history`: a straight drain over the window. */
function fakeCallWS(message: Record<string, unknown>): Promise<unknown> {
  if (message.type !== 'pulse_check/history') {
    return Promise.reject(new Error(`demo: unsupported command ${String(message.type)}`));
  }
  const entityId = String(message.entity_id);
  const days = Number(message.days);
  const rate = DRAIN_PER_DAY[entityId] ?? 0;
  const device = (payload.devices as Record<string, unknown>[]).find(
    (d) => (d.battery as { entityId?: string } | undefined)?.entityId === entityId,
  );
  const level = (device?.battery as { level?: number } | undefined)?.level ?? 50;
  const now = Date.now();
  const points = Array.from({ length: days }, (_, i) => {
    const daysAgo = days - i;
    return { time: now - daysAgo * DAY, level: level + daysAgo * rate };
  });
  const estimate = rate > 0 ? { ratePerDay: rate, daysLeft: level / rate, samples: days } : null;
  return new Promise((resolve) =>
    setTimeout(() => {
      resolve({ entity_id: entityId, days, points, estimate });
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

function toast(message: string) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, 2500);
}

function mount(scenario: Scenario) {
  host.replaceChildren();
  const { connection, mutate } = fakeConnection(scenario);

  /** Fake services: apply the change to the snapshot and re-send it. */
  const callService = (domain: string, service: string, data?: Record<string, unknown>) => {
    toast(`${domain}.${service} ${JSON.stringify(data ?? {})}`);
    const id = typeof data?.device_id === 'string' ? data.device_id : '';
    mutate((s) => {
      const devices = s.devices as Record<string, unknown>[];
      const device = devices.find((d) => d.deviceId === id);
      if (!device) return;
      if (service === 'snooze') {
        device.snoozedUntil = new Date(Date.now() + Number(data?.days ?? 7) * DAY).toISOString();
        device.severity = 'ok';
      } else if (service === 'unsnooze') {
        delete device.snoozedUntil;
      } else if (service === 'mark_replaced' || service === 'mark_charged') {
        device.lastReplaced = new Date().toISOString();
      } else if (service === 'set_device_settings') {
        const settings = s.device_settings as Record<string, Record<string, unknown>>;
        const rest = { ...data };
        delete rest.device_id;
        settings[id] = { ...settings[id], ...rest };
      }
    });
    return Promise.resolve();
  };

  const hass: HassLike = {
    ...buildHass(new Date()),
    connection,
    callWS: fakeCallWS as NonNullable<HassLike['callWS']>,
    callService,
  };

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
  card.hass = hass;
  host.appendChild(card);

  // Simulate HA pushing a fresh hass object every few seconds. Same
  // connection, so the card does not re-render; open devtools to verify.
  const timer = setInterval(() => {
    if (!card.isConnected) {
      clearInterval(timer);
      return;
    }
    card.hass = { ...hass };
  }, 5000);

  mountEditor(CONFIGS[scenario] as CardConfig, hass);
}

interface EditorLike extends HTMLElement {
  setConfig(config: CardConfig): void;
  hass: HassLike;
}

/** Render the visual editor next to the card and echo what it emits. */
function mountEditor(config: CardConfig, hass: HassLike) {
  const editorHost = mustGet('editor-host');
  const output = mustGet('editor-output');
  editorHost.replaceChildren();
  const editor = document.createElement('pulse-check-card-editor') as EditorLike;
  editor.setConfig(config);
  editor.hass = hass;
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

mount(scenarioSelect.value as Scenario);
