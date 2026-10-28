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
    expect(snapshot.maintenanceUntil).toBeUndefined();
    expect(
      parseSnapshot({ maintenance_until: '2026-10-15T12:00:00.000Z' }).maintenanceUntil,
    ).toEqual(new Date('2026-10-15T12:00:00.000Z'));

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
    const stopMissing = subscribeSnapshots(
      fakeHass({ reject: { code: 'not_loaded', message: 'nope' } }).hass,
      { onSnapshot: () => undefined, onError },
    );
    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalledWith('missing', 'nope');
    });
    const other = vi.fn();
    const stopOther = subscribeSnapshots(
      fakeHass({ reject: { code: 'unauthorized', message: 'no' } }).hass,
      { onSnapshot: () => undefined, onError: other },
    );
    await vi.waitFor(() => {
      expect(other).toHaveBeenCalledWith('error', 'no');
    });
    stopMissing();
    stopOther();
  });

  describe('after Home Assistant restarts', () => {
    const NOT_YET = { code: 'unknown_command', message: 'Unknown command.' };

    it('tries again until Pulse Check answers, then clears the error', async () => {
      vi.useFakeTimers();
      try {
        const fake = fakeHass({ reject: NOT_YET, rejectTimes: 2, state: 'RUNNING' });
        const onError = vi.fn();
        const onSnapshot = vi.fn();
        const stop = subscribeSnapshots(fake.hass, { onSnapshot, onError });
        await vi.advanceTimersByTimeAsync(0);
        expect(onError).toHaveBeenCalledWith('missing', 'Unknown command.');
        expect(onSnapshot).not.toHaveBeenCalled();

        await vi.advanceTimersByTimeAsync(1_000); // second attempt, still loading
        expect(fake.attempts()).toBe(2);
        await vi.advanceTimersByTimeAsync(2_000); // third attempt succeeds
        expect(fake.attempts()).toBe(3);
        expect(onSnapshot).toHaveBeenCalledOnce();
        stop();
      } finally {
        vi.useRealTimers();
      }
    });

    it('does not say "not found" while Home Assistant is still starting', async () => {
      vi.useFakeTimers();
      try {
        const fake = fakeHass({ reject: NOT_YET, rejectTimes: 3, state: 'STARTING' });
        const onError = vi.fn();
        const onSnapshot = vi.fn();
        const stop = subscribeSnapshots(fake.hass, { onSnapshot, onError });
        await vi.advanceTimersByTimeAsync(10_000);
        expect(onError).not.toHaveBeenCalled();
        expect(onSnapshot).toHaveBeenCalledOnce();
        stop();
      } finally {
        vi.useRealTimers();
      }
    });

    it('subscribes again itself after the connection comes back', async () => {
      const fake = fakeHass();
      const received: Snapshot[] = [];
      const stop = subscribeSnapshots(fake.hass, {
        onSnapshot: (s) => received.push(s),
        onError: () => undefined,
      });
      await vi.waitFor(() => {
        expect(received).toHaveLength(1);
      });
      // The websocket library must not re-send it on its own.
      expect(fake.lastOptions()).toEqual({ resubscribe: false });

      fake.reconnect();
      await vi.waitFor(() => {
        expect(received).toHaveLength(2);
      });
      expect(fake.attempts()).toBe(2);
      stop();
    });

    it('stops trying once the card is gone', async () => {
      vi.useFakeTimers();
      try {
        const fake = fakeHass({ reject: NOT_YET, state: 'RUNNING' });
        const stop = subscribeSnapshots(fake.hass, {
          onSnapshot: () => undefined,
          onError: () => undefined,
        });
        await vi.advanceTimersByTimeAsync(0);
        stop();
        await vi.advanceTimersByTimeAsync(120_000);
        expect(fake.attempts()).toBe(1);
        fake.reconnect();
        expect(fake.attempts()).toBe(1);
      } finally {
        vi.useRealTimers();
      }
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
