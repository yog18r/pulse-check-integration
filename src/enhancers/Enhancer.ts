/**
 * The enhancer contract.
 *
 * The universal core only uses data every integration provides. An enhancer
 * adds integration-specific detail when, and only when, the data exists.
 * It must never throw and never make a device disappear: returning an empty
 * array is always a valid answer.
 *
 * To add support for a new integration, implement this interface in a new
 * file and add one line to `src/enhancers/index.ts`. Nothing else changes.
 */
import type { DeviceGroup } from '../core/group';
import type { EnhancerExtra, HassLike } from '../core/types';

export interface Enhancer {
  /** Short id, used in tests and debugging. */
  readonly id: string;
  /** The integration (platform) this enhancer understands, e.g. "zwave_js". */
  readonly platform: string;
  /**
   * Inspect a device's raw entities and states and return extra facts.
   * Only called for devices whose dominant integration equals `platform`.
   */
  enhance(group: DeviceGroup, hass: HassLike): EnhancerExtra[];
}
