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

type Scenario = 'default' | 'tuned' | 'healthy' | 'broken';

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

  card.hass = scenario === 'healthy' ? healthyHass(now) : buildHass(now);
  host.appendChild(card);

  // Simulate HA pushing a fresh hass object every few seconds. The card's
  // fingerprint check means this does NOT cause a React re-render unless a
  // relevant entity actually changed; open devtools to verify.
  const timer = setInterval(() => {
    if (!card.isConnected) {
      clearInterval(timer);
      return;
    }
    card.hass = scenario === 'healthy' ? healthyHass(new Date()) : buildHass(new Date());
  }, 5000);
}

scenarioSelect.addEventListener('change', () => {
  mount(scenarioSelect.value as Scenario);
});

themeButton.addEventListener('click', () => {
  const dark = document.body.dataset.theme === 'dark';
  document.body.dataset.theme = dark ? 'light' : 'dark';
});

if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
  document.body.dataset.theme = 'dark';
}

mount('default');
