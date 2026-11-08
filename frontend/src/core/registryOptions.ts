/**
 * Option lists for the visual editor, derived from the registries.
 *
 * The editor gets the same `hass` object as the card, so instead of asking
 * users to type integration ids it can offer what actually exists in their
 * instance. Pure functions, unit tested.
 */
import type { HassLike } from './types';

export interface IntegrationOption {
  /** The platform id used in config, e.g. "zwave_js". */
  id: string;
  /** How many entities that integration provides; useful for sorting and display. */
  entityCount: number;
}

/** Every integration that provides at least one entity, most entities first. */
export function listIntegrations(hass: HassLike): IntegrationOption[] {
  const counts = new Map<string, number>();
  for (const entity of Object.values(hass.entities)) {
    if (!entity.platform) continue;
    counts.set(entity.platform, (counts.get(entity.platform) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([id, entityCount]) => ({ id, entityCount }))
    .sort((a, b) => b.entityCount - a.entityCount || a.id.localeCompare(b.id));
}
