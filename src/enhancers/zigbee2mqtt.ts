/**
 * Zigbee2MQTT enhancer.
 *
 * Zigbee2MQTT devices arrive through the `mqtt` integration. Two optional
 * sensors make them recognisable and tell us more than timestamps can:
 *
 *   linkquality   0-255 LQI, present on every Z2M device. Below ~30 is a
 *                 weak link worth a warning.
 *   last_seen     an ISO timestamp sensor, only present when the user turns
 *                 on `advanced.last_seen` in Z2M. When it exists it is the
 *                 true "last heard from", so we hand it to the core.
 *
 * Plain MQTT devices without these sensors get nothing, which is correct.
 */
import { parseTimestamp } from '../core/availability';
import type { EnhancerExtra } from '../core/types';
import { type Enhancer, type EnhancerResult, NO_RESULT } from './Enhancer';
import { findByAttribute, findBySuffix, numericState } from './helpers';

/** LQI at or below this is flagged as a weak link. */
export const WEAK_LQI = 30;

export const zigbee2mqttEnhancer: Enhancer = {
  id: 'zigbee2mqtt',
  platform: 'mqtt',

  enhance(group) {
    const extras: EnhancerExtra[] = [];
    const result: EnhancerResult = { extras };

    const lqi = numericState(
      findBySuffix(group, '_linkquality') ?? findByAttribute(group, 'unit_of_measurement', 'lqi'),
    );
    if (lqi !== undefined) {
      extras.push({
        label: 'LQI',
        value: String(Math.round(lqi)),
        severity: lqi <= WEAK_LQI ? 'warning' : 'ok',
      });
    }

    const lastSeen = findBySuffix(group, '_last_seen');
    const seenAt = lastSeen ? parseTimestamp(lastSeen.state) : undefined;
    if (seenAt) result.lastHeard = seenAt;

    return extras.length === 0 && !result.lastHeard ? NO_RESULT : result;
  },
};
