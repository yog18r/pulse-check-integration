/**
 * Small shared helpers for enhancers.
 *
 * Integrations don't give us a typed "this is the node status sensor"
 * flag, so enhancers recognise entities by convention: the entity id
 * suffix the integration generates, the unit, or the device class.
 */
import { parseNumeric } from '../core/battery';
import type { DeviceGroup } from '../core/group';
import type { HassEntityState } from '../core/types';

/** First state in the group whose entity id ends with one of the suffixes. */
export function findBySuffix(
  group: DeviceGroup,
  ...suffixes: string[]
): HassEntityState | undefined {
  return group.states.find((s) => suffixes.some((suffix) => s.entity_id.endsWith(suffix)));
}

/** First state in the group with the given attribute value. */
export function findByAttribute(
  group: DeviceGroup,
  attribute: string,
  value: unknown,
): HassEntityState | undefined {
  return group.states.find((s) => s.attributes[attribute] === value);
}

/** Numeric state, or undefined for unavailable/unknown/garbage. */
export function numericState(state: HassEntityState | undefined): number | undefined {
  return state ? parseNumeric(state.state) : undefined;
}
