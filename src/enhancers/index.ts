/**
 * Enhancer registry.
 *
 * The list is exported so tests can pass their own, and `applyEnhancers`
 * wraps each call in a try/catch so a bug in one enhancer can never break
 * the whole card.
 */
import type { DeviceGroup } from '../core/group';
import type { HassLike } from '../core/types';
import type { Enhancer, EnhancerResult } from './Enhancer';
import { zhaEnhancer } from './zha';
import { zigbee2mqttEnhancer } from './zigbee2mqtt';
import { zwaveJsEnhancer } from './zwaveJs';

export type { Enhancer, EnhancerResult } from './Enhancer';

/** Add new enhancers here. Order only affects the order of badges on a row. */
export const ENHANCERS: readonly Enhancer[] = [zwaveJsEnhancer, zigbee2mqttEnhancer, zhaEnhancer];

/** Merge the results of every enhancer that matches the device's integration. */
export function applyEnhancers(
  enhancers: readonly Enhancer[],
  integration: string,
  group: DeviceGroup,
  hass: HassLike,
): EnhancerResult {
  const merged: EnhancerResult = { extras: [] };
  for (const enhancer of enhancers) {
    if (enhancer.platform !== integration) continue;
    try {
      const result = enhancer.enhance(group, hass);
      merged.extras.push(...result.extras);
      if (result.offline) merged.offline = true;
      if (result.lastHeard && (!merged.lastHeard || result.lastHeard > merged.lastHeard)) {
        merged.lastHeard = result.lastHeard;
      }
    } catch (err) {
      // Enhancers are optional polish. Log and carry on.
      console.warn(`[pulse-check-card] enhancer "${enhancer.id}" failed`, err);
    }
  }
  return merged;
}
