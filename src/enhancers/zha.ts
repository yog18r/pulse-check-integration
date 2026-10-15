/**
 * ZHA enhancer.
 *
 * ZHA can expose two diagnostic sensors per device (disabled by default,
 * users enable them in the entity settings):
 *
 *   lqi    0-255 link quality, same scale as Zigbee2MQTT
 *   rssi   signal strength in dBm, typically -40 (great) to -90 (poor)
 *
 * We show whichever exist and warn on a weak LQI.
 */
import type { EnhancerExtra } from '../core/types';
import { type Enhancer, NO_RESULT } from './Enhancer';
import { findBySuffix, numericState } from './helpers';
import { WEAK_LQI } from './zigbee2mqtt';

export const zhaEnhancer: Enhancer = {
  id: 'zha',
  platform: 'zha',

  enhance(group) {
    const extras: EnhancerExtra[] = [];

    const lqi = numericState(findBySuffix(group, '_lqi'));
    if (lqi !== undefined) {
      extras.push({
        label: 'LQI',
        value: String(Math.round(lqi)),
        severity: lqi <= WEAK_LQI ? 'warning' : 'ok',
      });
    }

    const rssi = numericState(findBySuffix(group, '_rssi'));
    if (rssi !== undefined) {
      extras.push({ label: 'RSSI', value: `${String(Math.round(rssi))} dBm` });
    }

    return extras.length === 0 ? NO_RESULT : { extras };
  },
};
