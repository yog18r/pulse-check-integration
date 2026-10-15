/**
 * Change detection for the `hass` setter.
 *
 * Home Assistant hands the card a brand-new `hass` object every time ANY
 * entity in the whole house changes, often several times a second. Most of
 * those changes are irrelevant to us (a power meter ticking over). Rendering
 * React on every one would be wasteful, so we compute a cheap fingerprint of
 * just the data our analysis depends on and only re-render when it moves.
 *
 * The fingerprint is a plain string built from `state` and `last_updated`
 * of every entity that belongs to a device (or carries a battery). Building
 * a string of a few thousand short segments takes well under a millisecond.
 */
import type { HassLike } from './types';

export function fingerprint(hass: HassLike): string {
  const parts: string[] = [];
  for (const entity of Object.values(hass.entities)) {
    const state = hass.states[entity.entity_id];
    if (!state) continue;
    const relevant =
      entity.device_id !== undefined ||
      state.attributes.device_class === 'battery' ||
      'battery_level' in state.attributes;
    if (!relevant) continue;
    parts.push(entity.entity_id, state.state, state.last_updated);
  }
  return parts.join('\u0001');
}

/**
 * The registries change rarely (rename a device, add an area). Comparing
 * their object identity is enough: HA replaces the object when they change.
 */
export function registriesChanged(a: HassLike | undefined, b: HassLike): boolean {
  return a?.entities !== b.entities || a.devices !== b.devices || a.areas !== b.areas;
}
