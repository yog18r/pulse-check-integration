// @vitest-environment jsdom
/**
 * Component tests: render the real React tree against a canned
 * subscription payload and assert on what a user would see. The rules
 * themselves are the integration's; these tests check that its data
 * reaches the screen and that clicks do what the labels promise.
 */
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_CONFIG, type ResolvedConfig } from '../../src/card/config';
import type { HassBox } from '../../src/core/types';
import { translator } from '../../src/i18n';
import { App } from '../../src/ui/App';
import { FIXED_NOW } from '../fixtures/hass';
import {
  deviceEntry,
  fakeHass,
  SNAPSHOT_PAYLOAD,
  type FakeHassOptions,
} from '../fixtures/snapshot';

function renderApp(overrides: Partial<ResolvedConfig> = {}, options: FakeHassOptions = {}) {
  const fake = fakeHass(options);
  const hassBox: HassBox = { latest: fake.hass };
  const onOpenDevice = vi.fn();
  const config = { ...DEFAULT_CONFIG, ...overrides };
  const utils = render(<App hassBox={hassBox} config={config} onOpenDevice={onOpenDevice} />);
  return { ...utils, ...fake, onOpenDevice };
}

beforeEach(() => {
  vi.useFakeTimers({ now: FIXED_NOW, toFake: ['Date', 'setInterval', 'clearInterval'] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe('App', () => {
  it('shows the headline, breakdown and tab counts from the snapshot', async () => {
    renderApp({ title: 'Pulse Check' });
    expect(screen.getByText('Connecting to Pulse Check')).toBeInTheDocument();
    expect(await screen.findByText('⚠️ 7 devices need attention')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Pulse Check' })).toBeInTheDocument();
    expect(screen.getByText('5 low batteries · 1 offline · 2 quiet')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Batteries/ })).toHaveTextContent('5');
    expect(screen.getByRole('tab', { name: /Connectivity/ })).toHaveTextContent('3');
  });

  it('lists batteries lowest first and opens a device when a row is tapped', async () => {
    const { onOpenDevice } = renderApp();
    await screen.findByText(/devices need attention/);
    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]!).getByText('Hallway Smoke Alarm')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('TV Remote Battery')).toBeInTheDocument();

    await user().click(screen.getByRole('button', { name: /Living Room Motion, open/ }));
    expect(onOpenDevice).toHaveBeenCalledOnce();
    expect(onOpenDevice.mock.calls[0]?.[0]).toMatchObject({ deviceId: 'dev_z2m_motion' });
  });

  it('says so while maintenance mode holds notifications back', async () => {
    const { emit } = renderApp();
    await screen.findByText('⚠️ 7 devices need attention');
    expect(screen.queryByText(/Maintenance mode/)).not.toBeInTheDocument();
    emit({ ...SNAPSHOT_PAYLOAD, maintenance_until: '2026-10-15T12:00:00.000Z' });
    expect(await screen.findByRole('status')).toHaveTextContent(
      /Maintenance mode until .*12.00.*Notifications are held back/,
    );
  });

  it('shows devices an integration no longer provides as stale, not offline', async () => {
    const { emit } = renderApp();
    await screen.findByText('⚠️ 7 devices need attention');
    const leftover = {
      deviceId: 'dev_unifi_rule',
      name: 'UniFi Network Allow DNS',
      integration: 'unifi',
      deviceType: 'switch',
      isOffline: false,
      isQuiet: false,
      isNotProvided: true,
      quietThresholdHours: 24,
      severity: 'warning',
      extras: [],
      entityIds: ['switch.allow_dns'],
    };
    const devices = SNAPSHOT_PAYLOAD.devices as unknown[];
    emit({ ...SNAPSHOT_PAYLOAD, devices: [...devices, leftover] });
    expect(await screen.findByText('⚠️ 8 devices need attention')).toBeInTheDocument();
    expect(screen.getByText(/1 not provided/)).toBeInTheDocument();

    await user().click(screen.getByRole('tab', { name: /Connectivity/ }));
    const row = screen.getByText('UniFi Network Allow DNS').closest('li');
    expect(row).not.toBeNull();
    const cells = within(row!);
    expect(cells.getByText('Not provided')).toBeInTheDocument();
    expect(cells.getByText('no longer provided by UniFi Network')).toBeInTheDocument();
    expect(cells.queryByText('Offline')).not.toBeInTheDocument();
  });

  it("speaks the user's language", async () => {
    const fake = fakeHass();
    fake.hass.locale = { language: 'de' };
    render(<App hassBox={{ latest: fake.hass }} config={DEFAULT_CONFIG} />);
    const de = translator('de');
    expect(await screen.findByText(`⚠️ ${de.tn('headline.attention', 7)}`)).toBeInTheDocument();
    expect(
      screen.getByRole('tab', { name: new RegExp(de.t('tab.batteries')) }),
    ).toBeInTheDocument();
    const breakdown = [
      de.tn('breakdown.low', 5),
      de.tn('breakdown.offline', 1),
      de.tn('breakdown.quiet', 2),
    ].join(' · ');
    expect(screen.getByText(breakdown)).toBeInTheDocument();
  });

  it('re-renders when the subscription sends a new snapshot', async () => {
    const { emit } = renderApp();
    await screen.findByText('⚠️ 7 devices need attention');
    emit({
      ...SNAPSHOT_PAYLOAD,
      summary: { ...(SNAPSHOT_PAYLOAD.summary as object), attention: 1, lowBatteries: 1 },
      devices: [deviceEntry('Living Room Motion')],
    });
    expect(await screen.findByText('⚠️ 1 device needs attention')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it("shows the integration's days-left and unusual note on a row", async () => {
    renderApp(
      {},
      {
        payload: {
          ...SNAPSHOT_PAYLOAD,
          devices: [
            {
              ...deviceEntry('Living Room Motion'),
              daysLeft: 6.2,
              estimate: {
                daysLeft: 6.2,
                basis: 'trend over current cycle',
                confidence: 'high',
                kind: 'replace',
              },
              unusual: 'draining 3× faster than usual',
            },
          ],
        },
      },
    );
    const row = (await screen.findAllByRole('listitem'))[0]!;
    const label = within(row).getByText(/~6d left/);
    expect(label).toHaveAttribute('title', 'trend over current cycle (high confidence)');
    expect(within(row).getByText(/draining 3× faster/)).toBeInTheDocument();
  });

  it('labels charge estimates and open-ended ones differently', async () => {
    renderApp(
      {},
      {
        payload: {
          ...SNAPSHOT_PAYLOAD,
          devices: [
            {
              ...deviceEntry('Front Door Sensor'),
              daysLeft: 58,
              batteryKind: 'charged',
              estimate: {
                daysLeft: 58,
                basis: 'until charge needed',
                confidence: 'medium',
                kind: 'charge',
              },
            },
            {
              ...deviceEntry('Window Sensor'),
              daysLeft: 365,
              batteryKind: 'replaceable',
              estimate: {
                daysLeft: 365,
                basis: 'flat for 120 days',
                confidence: 'low',
                kind: 'replace',
                openEnded: true,
              },
            },
          ],
        },
      },
    );
    const charge = await screen.findByText(/charge in ~8w/);
    expect(charge).toHaveAttribute('title', 'until charge needed (medium confidence)');
    const flat = screen.getByText(/more than a year left/);
    expect(flat).toHaveAttribute('title', 'flat for 120 days (low confidence)');
  });

  it('shows no days-left for devices without an estimate, charging or not', async () => {
    renderApp();
    await screen.findByText(/devices need attention/);
    const rows = screen.getAllByRole('listitem');
    const phone = rows.find((r) => within(r).queryByText('Pixel 9'))!;
    const vacuum = rows.find((r) => within(r).queryByText('Mr Roboto'))!;
    expect(within(phone).queryByText(/left/)).not.toBeInTheDocument();
    expect(within(vacuum).queryByText(/left/)).not.toBeInTheDocument();
    expect(within(vacuum).getByText(/charging/)).toBeInTheDocument();
  });

  it('snoozes and unsnoozes through the integration services', async () => {
    const { callService } = renderApp({ show_tabs: ['connectivity'] });
    await screen.findByText(/devices need attention/);

    await user().click(screen.getByRole('button', { name: 'Snooze Front Door Lock' }));
    await user().click(screen.getByRole('menuitem', { name: /7 days/ }));
    expect(callService).toHaveBeenCalledWith('pulse_check', 'snooze', {
      device_id: 'dev_zwave_lock',
      days: 7,
    });
  });

  it('offers "done" on the Actions tab and records a replacement', async () => {
    const { callService } = renderApp({ show_tabs: ['actions'], default_tab: 'actions' });
    await screen.findByText(/To buy/);
    await user().click(screen.getByRole('button', { name: 'Mark Living Room Motion done' }));
    expect(callService).toHaveBeenCalledWith('pulse_check', 'mark_replaced', {
      device_id: 'dev_z2m_motion',
    });
    // A battery with no device, not even a registry entry, goes by its entity: id.
    await user().click(screen.getByRole('button', { name: 'Mark Garden Soil Sensor done' }));
    expect(callService).toHaveBeenCalledWith('pulse_check', 'mark_replaced', {
      device_id: 'entity:sensor.garden_soil_moisture',
    });
  });

  it('view filters narrow the card, header included', async () => {
    renderApp({ areas: ['Hallway'], show_tabs: ['batteries', 'connectivity'] });
    expect(await screen.findByText('⚠️ 2 devices need attention')).toBeInTheDocument();
    expect(screen.getByText('1 low battery · 1 offline')).toBeInTheDocument();
    const rows = screen.getAllByRole('listitem');
    expect(rows.map((r) => r.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining('Hallway Smoke Alarm')]),
    );
    expect(screen.queryByText('Living Room Motion')).not.toBeInTheDocument();
  });

  it('groups rows when asked', async () => {
    renderApp({ group_by: 'device_type' });
    await screen.findByText(/devices need attention/);
    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings[0]).toMatch(/^Climate/);
    expect(headings).toContainEqual(expect.stringMatching(/^Contact sensors/));
    expect(headings.at(-1)).toMatch(/^Other/);
  });

  it("asks for each battery's history with its own sparkline window", async () => {
    const history = vi.fn((_entityId: string, days: number) => ({
      days,
      points: [],
      estimate: null,
    }));
    renderApp(
      { sparkline_days: 14 },
      {
        history,
        payload: {
          ...SNAPSHOT_PAYLOAD,
          device_settings: {
            dev_phone: { sparkline_days: 1 },
            'entity:sensor.garden_soil_moisture': { sparkline_days: 3 },
          },
        },
      },
    );
    await screen.findByText(/devices need attention/);
    await vi.waitFor(() => {
      expect(history).toHaveBeenCalledWith('sensor.pixel_9_battery_level', 1);
    });
    expect(history).toHaveBeenCalledWith('sensor.kitchen_ht_battery', 14);
    expect(history).toHaveBeenCalledWith('sensor.garden_soil_moisture', 3);
  });

  it('explains itself when the integration is not installed', async () => {
    renderApp({}, { reject: { code: 'not_loaded', message: 'Pulse Check is not set up' } });
    expect(await screen.findByText('Pulse Check integration not found')).toBeInTheDocument();
  });

  it('reports other subscription failures', async () => {
    renderApp({}, { reject: { code: 'unauthorized', message: 'Unauthorized' } });
    expect(await screen.findByText('Could not reach Pulse Check')).toBeInTheDocument();
    expect(screen.getByText('Unauthorized')).toBeInTheDocument();
  });

  it('unsubscribes when unmounted', async () => {
    const { unmount, unsubscribe, subscribed } = renderApp();
    await screen.findByText(/devices need attention/);
    expect(subscribed()).toBe(true);
    unmount();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
});
