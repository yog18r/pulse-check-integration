// @vitest-environment jsdom
/**
 * Component tests: render the real React tree against the shared fixture
 * and assert on what a user would see. These complement the pure-logic
 * tests; they don't re-test the rules, they test that the rules reach
 * the screen and that clicks do what the labels promise.
 */
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_CONFIG, type ResolvedConfig } from '../../src/card/config';
import { SNOOZE_STORAGE_KEY } from '../../src/card/snoozeStore';
import { ENHANCERS } from '../../src/enhancers';
import { App } from '../../src/ui/App';
import { buildHass, FIXED_NOW } from '../fixtures/hass';

function renderApp(overrides: Partial<ResolvedConfig> = {}) {
  const config = { ...DEFAULT_CONFIG, ...overrides };
  const onOpenDevice = vi.fn();
  const utils = render(
    <App
      hass={buildHass(FIXED_NOW)}
      config={config}
      enhancers={ENHANCERS}
      onOpenDevice={onOpenDevice}
    />,
  );
  return { ...utils, onOpenDevice };
}

beforeEach(() => {
  vi.useFakeTimers({ now: FIXED_NOW, toFake: ['Date', 'setInterval', 'clearInterval'] });
  localStorage.removeItem(SNOOZE_STORAGE_KEY);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe('App', () => {
  it('shows the headline, breakdown and tab counts from the fixture', () => {
    renderApp({ title: 'Pulse Check' });
    expect(screen.getByRole('heading', { name: 'Pulse Check' })).toBeInTheDocument();
    expect(screen.getByText('⚠️ 6 devices need attention')).toBeInTheDocument();
    expect(screen.getByText('4 low batteries · 1 offline · 2 quiet')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Batteries/ })).toHaveTextContent('4');
    expect(screen.getByRole('tab', { name: /Connectivity/ })).toHaveTextContent('3');
  });

  it('lists batteries lowest first and opens a device when a row is tapped', async () => {
    const { onOpenDevice } = renderApp();
    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]!).getByText('Hallway Smoke Alarm')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('TV Remote Battery')).toBeInTheDocument();

    await user().click(screen.getByRole('button', { name: /Living Room Motion, open/ }));
    expect(onOpenDevice).toHaveBeenCalledOnce();
    expect(onOpenDevice.mock.calls[0]?.[0]).toMatchObject({ deviceId: 'dev_z2m_motion' });
  });

  it('switches tabs', async () => {
    renderApp();
    await user().click(screen.getByRole('tab', { name: /Connectivity/ }));
    expect(screen.getByRole('tab', { name: /Connectivity/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByText('Front Door Lock')).toBeInTheDocument();
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(screen.queryByText('Kitchen H&T')).not.toBeInTheDocument();
  });

  it('problems_only shows just the batteries that need attention', () => {
    renderApp({ problems_only: true });
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
    expect(screen.queryByText('Kitchen H&T')).not.toBeInTheDocument();
  });

  it('hides the title row when the title is blank', () => {
    renderApp({ title: '' });
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    expect(screen.getByText('⚠️ 6 devices need attention')).toBeInTheDocument();
  });

  it('caps rows and expands on "Show N more"', async () => {
    renderApp({ max_rows: 3 });
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
    await user().click(screen.getByRole('button', { name: 'Show 8 more' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(11);
    expect(screen.getByRole('button', { name: 'Show less' })).toBeInTheDocument();
  });

  it('snoozes a device from the Connectivity tab and can unsnooze it from the footer', async () => {
    renderApp();
    const u = user();
    await u.click(screen.getByRole('tab', { name: /Connectivity/ }));
    await u.click(screen.getByRole('button', { name: 'Snooze Front Door Lock' }));
    await u.click(screen.getByRole('menuitem', { name: '7 days' }));

    expect(screen.queryByText('Front Door Lock')).not.toBeInTheDocument();
    expect(screen.getByText('⚠️ 5 devices need attention')).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(SNOOZE_STORAGE_KEY) ?? '{}')).toHaveProperty(
      'dev_zwave_lock',
    );

    await u.click(screen.getByRole('button', { name: /1 snoozed · show/ }));
    await u.click(screen.getByRole('button', { name: 'Unsnooze Front Door Lock' }));
    expect(screen.getByText('⚠️ 6 devices need attention')).toBeInTheDocument();
  });

  it('shows the Actions tab with replace and charge jobs', async () => {
    renderApp({
      show_tabs: ['batteries', 'actions'],
      device_settings: [
        { device_id: 'dev_zha_temp', battery_type: 'AAA', battery_count: 2 },
        { device_id: 'dev_smoke_alarm', rechargeable: true },
      ],
    });
    await user().click(screen.getByRole('tab', { name: /Actions/ }));
    expect(screen.getByText('To buy:').closest('p')).toHaveTextContent('2 × AAA');
    expect(screen.getByText('Replace 2 × AAA in Bedroom Temp & Humidity')).toBeInTheDocument();
    expect(screen.getByText('Charge Hallway Smoke Alarm')).toBeInTheDocument();
  });

  it('uses per-device display names and areas', () => {
    renderApp({
      device_settings: [{ device_id: 'dev_phone', name: 'My Pixel', area: 'Office' }],
    });
    const row = screen.getByRole('button', { name: /My Pixel, open/ });
    expect(within(row).getByText('Office')).toBeInTheDocument();
  });
});
