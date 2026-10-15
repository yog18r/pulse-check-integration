// @vitest-environment jsdom
/**
 * Integration mode: the card renders what the Pulse Check integration's
 * sensor says, and snoozes and "done" become service calls.
 */
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_CONFIG, type ResolvedConfig } from '../../src/card/config';
import type { HassLike } from '../../src/core/types';
import { ENHANCERS } from '../../src/enhancers';
import { App } from '../../src/ui/App';
import golden from '../fixtures/golden.json';
import { buildHass, FIXED_NOW } from '../fixtures/hass';

const SENSOR = 'sensor.pulse_check_attention';

function hassFromIntegration(devices: unknown[], callService = vi.fn()): HassLike {
  const base = buildHass(FIXED_NOW);
  return {
    ...base,
    callService,
    states: {
      ...base.states,
      [SENSOR]: {
        entity_id: SENSOR,
        state: '6',
        attributes: { devices },
        last_changed: FIXED_NOW.toISOString(),
        last_updated: FIXED_NOW.toISOString(),
      },
    },
  };
}

function renderApp(hass: HassLike, overrides: Partial<ResolvedConfig> = {}) {
  const config: ResolvedConfig = { ...DEFAULT_CONFIG, source: 'integration', ...overrides };
  return render(<App hass={hass} config={config} enhancers={ENHANCERS} />);
}

beforeEach(() => {
  vi.useFakeTimers({ now: FIXED_NOW, toFake: ['Date', 'setInterval', 'clearInterval'] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe('App in integration mode', () => {
  it('renders the integration device list instead of analysing', () => {
    // Only the critical motion sensor, with the integration's extras.
    const motion = golden.cases[0]!.devices.find((d) => d.name === 'Living Room Motion')!;
    renderApp(
      hassFromIntegration([{ ...motion, daysLeft: 6.2, unusual: 'draining 3× faster than usual' }]),
    );
    expect(screen.getByText('⚠️ 1 device needs attention')).toBeInTheDocument();
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(1);
    expect(within(rows[0]!).getByText('Living Room Motion')).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/~6d left/)).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/draining 3× faster/)).toBeInTheDocument();
  });

  it('explains itself when the integration is not installed', () => {
    renderApp(buildHass(FIXED_NOW));
    expect(screen.getByText('Pulse Check integration not found')).toBeInTheDocument();
  });

  it('snoozes through the integration service', async () => {
    const callService = vi.fn().mockResolvedValue(undefined);
    const lock = golden.cases[0]!.devices.find((d) => d.name === 'Front Door Lock')!;
    renderApp(hassFromIntegration([lock], callService), { show_tabs: ['connectivity'] });

    await user().click(screen.getByRole('button', { name: 'Snooze Front Door Lock' }));
    await user().click(screen.getByRole('menuitem', { name: /7 days/ }));
    expect(callService).toHaveBeenCalledWith('pulse_check', 'snooze', {
      device_id: 'dev_zwave_lock',
      days: 7,
    });
  });

  it('offers "done" on the Actions tab and records a replacement', async () => {
    const callService = vi.fn().mockResolvedValue(undefined);
    const motion = golden.cases[0]!.devices.find((d) => d.name === 'Living Room Motion')!;
    renderApp(hassFromIntegration([motion], callService), {
      show_tabs: ['actions'],
      default_tab: 'actions',
    });
    await user().click(screen.getByRole('button', { name: 'Mark Living Room Motion done' }));
    expect(callService).toHaveBeenCalledWith('pulse_check', 'mark_replaced', {
      device_id: 'dev_z2m_motion',
    });
  });

  it('groups rows when asked', () => {
    renderApp(hassFromIntegration(golden.cases[0]!.devices), { group_by: 'device_type' });
    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings[0]).toMatch(/^Climate/);
    expect(headings).toContainEqual(expect.stringMatching(/^Contact sensors/));
    expect(headings.at(-1)).toMatch(/^Other/);
  });
});
