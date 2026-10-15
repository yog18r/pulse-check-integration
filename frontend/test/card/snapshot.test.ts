import { describe, expect, it, vi } from 'vitest';
import {
  callPulseCheck,
  loadHistory,
  parseDevice,
  parseSnapshot,
  subscribeSnapshots,
  type Snapshot,
} from '../../src/card/snapshot';
import { deviceEntry, fakeHass, SNAPSHOT_PAYLOAD } from '../fixtures/snapshot';

describe('parseSnapshot', () => {
  it('turns the integration event into typed data, dates included', () => {
    const snapshot = parseSnapshot({
      ...SNAPSHOT_PAYLOAD,
      device_settings: { dev_zha_temp: { battery_type: 'CR2450', battery_count: 2, bogus: 1 } },
    });
    expect(snapshot.devices).toHaveLength(16);
    expect(snapshot.summary.attention).toBe(7);
    expect(snapshot.actions.shopping[0]).toEqual({
      batteryType: 'Unknown type',
      count: 5,
      devices: 5,
    });
    expect(snapshot.config).toEqual({
      battery_warning: 30,
      battery_critical: 15,
      quiet_threshold_hours: 24,
      quiet_scope: 'battery',
    });
    expect(snapshot.deviceSettings).toEqual({
      dev_zha_temp: { battery_type: 'CR2450', battery_count: 2 },
    });
    expect(snapshot.computedAt?.toISOString()).toBe('2026-10-15T10:00:00.000Z');

    const motion = snapshot.devices.find((d) => d.name === 'Living Room Motion')!;
    expect(motion.lastHeard?.toISOString()).toBe('2026-10-15T09:20:00.000Z');
    expect(motion.deviceType).toBe('motion');
    expect(motion.battery).toEqual({
      level: 12,
      isLow: false,
      source: 'sensor',
      entityId: 'sensor.living_room_motion_battery',
    });
  });

  it('never throws on garbage, and skips entries that are not devices', () => {
    expect(parseSnapshot(null).devices).toEqual([]);
    expect(
      parseSnapshot({ devices: [null, { name: 'x' }, deviceEntry('Pixel 9')] }).devices,
    ).toHaveLength(1);
    expect(parseSnapshot({ summary: 'nope' }).summary.attention).toBe(0);
    expect(parseSnapshot({ config: { battery_warning: 'high' } }).config.battery_warning).toBe(30);
  });

  it('parses the optional history fields on a device', () => {
    const device = parseDevice({
      ...deviceEntry('Living Room Motion'),
      daysLeft: 6.1,
      lastReplaced: '2026-10-01T00:00:00.000Z',
      unusual: 'draining 3× faster than usual',
      deviceType: 'spaceship',
    })!;
    expect(device.daysLeft).toBe(6.1);
    expect(device.lastReplaced?.toISOString()).toBe('2026-10-01T00:00:00.000Z');
    expect(device.unusual).toBe('draining 3× faster than usual');
    expect(device.deviceType).toBe('other'); // unknown types fall back
  });
});

describe('subscribeSnapshots', () => {
  it('delivers snapshots and stops on unsubscribe', async () => {
    const fake = fakeHass();
    const received: Snapshot[] = [];
    const stop = subscribeSnapshots(fake.hass, {
      onSnapshot: (s) => received.push(s),
      onError: () => undefined,
    });
    await vi.waitFor(() => {
      expect(received).toHaveLength(1);
    });
    fake.emit(SNAPSHOT_PAYLOAD);
    expect(received).toHaveLength(2);
    stop();
    expect(fake.unsubscribe).toHaveBeenCalledOnce();
    fake.emit(SNAPSHOT_PAYLOAD);
    expect(received).toHaveLength(2);
  });

  it('tells "integration missing" apart from other errors', async () => {
    const onError = vi.fn();
    subscribeSnapshots(fakeHass({ reject: { code: 'not_loaded', message: 'nope' } }).hass, {
      onSnapshot: () => undefined,
      onError,
    });
    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalledWith('missing', 'nope');
    });
    const other = vi.fn();
    subscribeSnapshots(fakeHass({ reject: { code: 'unauthorized', message: 'no' } }).hass, {
      onSnapshot: () => undefined,
      onError: other,
    });
    await vi.waitFor(() => {
      expect(other).toHaveBeenCalledWith('error', 'no');
    });
  });

  it('reports a hass without a connection', () => {
    const onError = vi.fn();
    const hass = { ...fakeHass().hass };
    delete hass.connection;
    subscribeSnapshots(hass, { onSnapshot: () => undefined, onError });
    expect(onError).toHaveBeenCalledWith('error', 'No websocket connection');
  });
});

describe('loadHistory and services', () => {
  it('reads sparkline points and the estimate from pulse_check/history', async () => {
    const { hass } = fakeHass({
      history: () => ({
        days: 14,
        points: [
          { time: 1, level: 50 },
          { time: 2, level: 'x' },
        ],
        estimate: {
          daysLeft: 6,
          basis: 'trend over current cycle',
          confidence: 'high',
          kind: 'replace',
        },
      }),
    });
    const history = await loadHistory(hass, 'sensor.x', 14);
    expect(history).toEqual({
      days: 14,
      points: [{ time: 1, level: 50 }],
      estimate: {
        daysLeft: 6,
        basis: 'trend over current cycle',
        confidence: 'high',
        kind: 'replace',
      },
    });
    const noWS = { ...hass };
    delete noWS.callWS;
    expect(await loadHistory(noWS, 'sensor.x', 14)).toBeUndefined();
  });

  it('calls the integration service when hass can', async () => {
    const { hass, callService } = fakeHass();
    await callPulseCheck(hass, 'snooze', { device_id: 'x', days: 7 });
    expect(callService).toHaveBeenCalledWith('pulse_check', 'snooze', { device_id: 'x', days: 7 });
    await expect(
      callPulseCheck(undefined, 'unsnooze', { device_id: 'x' }),
    ).resolves.toBeUndefined();
  });
});
