/**
 * `useSnapshot`: the integration's live data as React state.
 *
 * Subscribes once per websocket connection and re-renders whenever a new
 * snapshot arrives. The subscription is torn down when the component
 * unmounts (Home Assistant removes and re-adds cards while editing
 * dashboards) or when the connection object changes (a reconnect).
 *
 * React note: `useEffect` runs after render; the function it returns is
 * the cleanup, which React calls before the effect runs again and on
 * unmount. That is exactly where "unsubscribe" belongs.
 */
import { useEffect, useState } from 'react';
import { subscribeSnapshots, type Snapshot, type SubscribeFailure } from '../card/snapshot';
import type { HassConnection, HassBox } from '../core/types';

export type SnapshotStatus = 'loading' | 'ready' | SubscribeFailure;

export interface SnapshotState {
  status: SnapshotStatus;
  snapshot?: Snapshot;
  /** The server's message when the status is "error" or "missing". */
  error?: string;
}

function initialState(connection: HassConnection | undefined): SnapshotState {
  return connection ? { status: 'loading' } : { status: 'error', error: 'No websocket connection' };
}

export function useSnapshot(
  hassBox: HassBox,
  connection: HassConnection | undefined,
): SnapshotState {
  const [state, setState] = useState<SnapshotState>(() => initialState(connection));

  // A new connection starts over. Resetting state during render (not in an
  // effect) is React's pattern for state that depends on a prop.
  const [seen, setSeen] = useState(connection);
  if (seen !== connection) {
    setSeen(connection);
    setState(initialState(connection));
  }

  useEffect(() => {
    const hass = hassBox.latest;
    if (!hass || !connection) return;
    return subscribeSnapshots(hass, {
      onSnapshot: (snapshot) => {
        setState({ status: 'ready', snapshot });
      },
      onError: (kind, message) => {
        setState({ status: kind, error: message });
      },
    });
  }, [hassBox, connection]);

  return state;
}
