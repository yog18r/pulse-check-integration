/**
 * A fake `hass` whose websocket "subscription" replays a canned snapshot,
 * for component tests and the demo page.
 *
 * `snapshot.json` is one `pulse_check/subscribe` event: 16 devices from
 * the integration's test fixture (a mock house covering every rule),
 * computed at 2026-10-15T10:00:00Z. Tests freeze time there.
 */
import { vi } from 'vitest';
import type { HassConnection, HassLike } from '../../src/core/types';
import { buildHass, FIXED_NOW } from './hass';
import payload from './snapshot.json';

export const SNAPSHOT_PAYLOAD: Record<string, unknown> = payload;

/** The raw device entries of the canned snapshot. */
export const SNAPSHOT_DEVICES = payload.devices as Record<string, unknown>[];

export function deviceEntry(name: string): Record<string, unknown> {
  const found = SNAPSHOT_DEVICES.find((d) => d.name === name);
  if (!found) throw new Error(`no fixture device named ${name}`);
  return found;
}

export interface FakeHassOptions {
  /** The first event sent after subscribing. Defaults to the canned snapshot. */
  payload?: unknown;
  /** Reject the subscription with this error instead. */
  reject?: { code: string; message: string };
  /** Answer `pulse_check/history` with this, per entity id. */
  history?: (entityId: string, days: number) => unknown;
}

export interface FakeHass {
  hass: HassLike;
  /** Push another snapshot event to the subscriber. */
  emit: (payload: unknown) => void;
  callService: ReturnType<typeof vi.fn>;
  unsubscribe: ReturnType<typeof vi.fn>;
  subscribed: () => boolean;
}

export function fakeHass(options: FakeHassOptions = {}): FakeHass {
  let callback: ((message: unknown) => void) | undefined;
  const unsubscribe = vi.fn(() => {
    callback = undefined;
    return Promise.resolve();
  });
  const connection: HassConnection = {
    subscribeMessage(cb: (message: unknown) => void, message: Record<string, unknown>) {
      // Home Assistant rejects with a plain { code, message } object, not an Error.
      if (message.type !== 'pulse_check/subscribe') {
        // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
        return Promise.reject({ code: 'unknown_command', message: 'Unknown command.' });
      }
      // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
      if (options.reject) return Promise.reject(options.reject);
      callback = cb;
      // HA confirms the subscription first and sends the first event after.
      queueMicrotask(() => {
        callback?.(options.payload ?? SNAPSHOT_PAYLOAD);
      });
      return Promise.resolve(unsubscribe);
    },
  };
  const callService = vi.fn(() => Promise.resolve());
  const hass: HassLike = {
    ...buildHass(FIXED_NOW),
    connection,
    callService,
    callWS: <T>(message: Record<string, unknown>) => {
      if (message.type === 'pulse_check/history' && options.history) {
        return Promise.resolve(
          options.history(String(message.entity_id), Number(message.days)) as T,
        );
      }
      return Promise.resolve({ points: [], days: message.days, estimate: null } as T);
    },
  };
  return {
    hass,
    emit: (next) => callback?.(next),
    callService,
    unsubscribe,
    subscribed: () => callback !== undefined,
  };
}
