/**
 * Z-Wave JS enhancer.
 *
 * Z-Wave JS gives every node a diagnostic "Node status" sensor with one of
 * the states: alive, awake, asleep, dead, unknown. That is a far better
 * liveness signal than timestamps:
 *
 *   dead    the controller has given up on the node   -> offline, critical
 *   asleep  normal for battery devices between wakeups -> informational
 *   alive / awake                                       -> informational
 */
import type { EnhancerExtra, Severity } from '../core/types';
import { type Enhancer, NO_RESULT } from './Enhancer';
import { findBySuffix } from './helpers';

const KNOWN_STATUSES = new Set(['alive', 'awake', 'asleep', 'dead', 'unknown']);

export const zwaveJsEnhancer: Enhancer = {
  id: 'zwave-js',
  platform: 'zwave_js',

  enhance(group) {
    const status = findBySuffix(group, '_node_status');
    if (!status || !KNOWN_STATUSES.has(status.state)) return NO_RESULT;

    const dead = status.state === 'dead';
    const severity: Severity = dead ? 'critical' : 'ok';
    const extra: EnhancerExtra = { label: 'Node', value: status.state, severity };
    return dead ? { extras: [extra], offline: true } : { extras: [extra] };
  },
};
