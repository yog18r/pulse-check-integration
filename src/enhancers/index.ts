/**
 * Enhancer registry.
 *
 * Phase 2 adds Z-Wave JS, Zigbee2MQTT and ZHA here. The list is exported so
 * tests can pass their own, and `applyEnhancers` wraps each call in a
 * try/catch so a bug in one enhancer can never break the whole card.
 */
import type { DeviceGroup } from '../core/group';
import type { EnhancerExtra, HassLike } from '../core/types';
import type { Enhancer } from './Enhancer';

export type { Enhancer } from './Enhancer';

export const ENHANCERS: readonly Enhancer[] = [];

export function applyEnhancers(
  enhancers: readonly Enhancer[],
  integration: string,
  group: DeviceGroup,
  hass: HassLike,
): EnhancerExtra[] {
  const extras: EnhancerExtra[] = [];
  for (const enhancer of enhancers) {
    if (enhancer.platform !== integration) continue;
    try {
      extras.push(...enhancer.enhance(group, hass));
    } catch (err) {
      // Enhancers are optional polish. Log and carry on.
      console.warn(`[pulse-check-card] enhancer "${enhancer.id}" failed`, err);
    }
  }
  return extras;
}
