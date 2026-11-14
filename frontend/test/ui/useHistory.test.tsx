// @vitest-environment jsdom
/**
 * `useHistory` on its own: which `pulse_check/histories` requests it sends
 * as batteries come and go, and what it does when one fails.
 */
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HassBox, HassLike } from '../../src/core/types';
import { REFRESH_MS, RETRY_MS, useHistory, type HistoryRequest } from '../../src/ui/useHistory';
import { FIXED_NOW, hass as fixtureHass } from '../fixtures/hass';

interface WsMessage {
  type: string;
  requests: { entity_id: string; days: number }[];
}

/** A hass whose `pulse_check/histories` answers one point per battery, or fails when told. */
function setup() {
  let failing = false;
  const callWS = vi.fn((message: WsMessage) => {
    if (failing) {
      // Home Assistant rejects with a plain { code, message } object.
      // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
      return Promise.reject({ code: 'not_loaded', message: 'Pulse Check is reloading' });
    }
    return Promise.resolve({
      results: message.requests.map((r) => ({
        entity_id: r.entity_id,
        days: r.days,
        points: [{ time: 1, level: 50 }],
      })),
    });
  });
  const hass: HassLike = {
    ...fixtureHass,
    callWS: callWS as unknown as NonNullable<HassLike['callWS']>,
  };
  const hassBox: HassBox = { latest: hass };
  /** The entity ids each call asked for, in order. */
  const asked = () =>
    callWS.mock.calls.map(([message]) => message.requests.map((r) => r.entity_id).sort());
  return {
    hassBox,
    callWS,
    asked,
    fail: (value: boolean) => {
      failing = value;
    },
  };
}

const req = (entityId: string, days = 14): HistoryRequest => ({ entityId, days });

beforeEach(() => {
  vi.useFakeTimers({ now: FIXED_NOW, toFake: ['Date', 'setInterval', 'clearInterval'] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('useHistory', () => {
  it('fetches only batteries that are new, and merges them into the map', async () => {
    const { hassBox, asked } = setup();
    const { result, rerender } = renderHook(
      ({ requests }: { requests: HistoryRequest[] }) => useHistory(hassBox, requests, true),
      { initialProps: { requests: [req('sensor.a'), req('sensor.b')] } },
    );
    await vi.waitFor(() => {
      expect(result.current?.size).toBe(2);
    });
    expect(asked()).toEqual([['sensor.a', 'sensor.b']]);

    // A third battery appears: one request for it alone.
    rerender({ requests: [req('sensor.a'), req('sensor.b'), req('sensor.c')] });
    await vi.waitFor(() => {
      expect(result.current?.size).toBe(3);
    });
    expect(asked()).toEqual([['sensor.a', 'sensor.b'], ['sensor.c']]);
    expect([...result.current!.keys()].sort()).toEqual(['sensor.a', 'sensor.b', 'sensor.c']);

    // sensor.b goes unavailable and comes back: nothing to fetch.
    rerender({ requests: [req('sensor.a'), req('sensor.c')] });
    rerender({ requests: [req('sensor.a'), req('sensor.b'), req('sensor.c')] });
    expect(asked()).toHaveLength(2);
    expect(result.current?.get('sensor.b')).toBeDefined();

    // A new window for a battery (a per-device setting) is a new request.
    rerender({ requests: [req('sensor.a', 1), req('sensor.b'), req('sensor.c')] });
    await vi.waitFor(() => {
      expect(asked()).toHaveLength(3);
    });
    expect(asked()[2]).toEqual(['sensor.a']);
  });

  it('refreshes every battery on screen in one call every few hours', async () => {
    const { hassBox, asked } = setup();
    const { result, rerender } = renderHook(
      ({ requests }: { requests: HistoryRequest[] }) => useHistory(hassBox, requests, true),
      { initialProps: { requests: [req('sensor.a')] } },
    );
    await vi.waitFor(() => {
      expect(result.current?.size).toBe(1);
    });
    rerender({ requests: [req('sensor.a'), req('sensor.b')] });
    await vi.waitFor(() => {
      expect(asked()).toHaveLength(2);
    });

    act(() => {
      vi.advanceTimersByTime(REFRESH_MS);
    });
    await vi.waitFor(() => {
      expect(asked()).toHaveLength(3);
    });
    expect(asked()[2]).toEqual(['sensor.a', 'sensor.b']);
  });

  it('keeps what it has and warns when a fetch fails, and retries it later', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { hassBox, asked, fail } = setup();
    const { result, rerender } = renderHook(
      ({ requests }: { requests: HistoryRequest[] }) => useHistory(hassBox, requests, true),
      { initialProps: { requests: [req('sensor.a')] } },
    );
    await vi.waitFor(() => {
      expect(result.current?.size).toBe(1);
    });

    fail(true);
    rerender({ requests: [req('sensor.a'), req('sensor.b')] });
    await vi.waitFor(() => {
      expect(warn).toHaveBeenCalledOnce();
    });
    expect(warn.mock.calls[0]?.[1]).toMatchObject({ message: 'Pulse Check is reloading' });
    // The sparkline already on screen stays.
    expect([...result.current!.keys()]).toEqual(['sensor.a']);

    // sensor.b was not loaded, so the next change asks for it again.
    fail(false);
    rerender({ requests: [req('sensor.a'), req('sensor.b'), req('sensor.c')] });
    await vi.waitFor(() => {
      expect(result.current?.size).toBe(3);
    });
    expect(asked().at(-1)).toEqual(['sensor.b', 'sensor.c']);
  });

  it('tries a failed fetch again on its own after a while', async () => {
    vi.useFakeTimers({
      now: FIXED_NOW,
      toFake: ['Date', 'setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'],
    });
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { hassBox, asked, fail } = setup();
    fail(true);
    const { result } = renderHook(() => useHistory(hassBox, [req('sensor.a')], true));
    await vi.waitFor(() => {
      expect(asked()).toHaveLength(1);
    });
    expect(result.current).toBeUndefined();

    // Nothing changes on screen; the retry comes by itself.
    fail(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RETRY_MS);
    });
    await vi.waitFor(() => {
      expect(result.current?.size).toBe(1);
    });
    expect(asked()).toEqual([['sensor.a'], ['sensor.a']]);
  });

  it('asks for nothing while disabled', () => {
    const { hassBox, callWS } = setup();
    renderHook(() => useHistory(hassBox, [req('sensor.a')], false));
    expect(callWS).not.toHaveBeenCalled();
  });
});
