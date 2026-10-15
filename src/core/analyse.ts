/**
 * The orchestrator: `hass` + config -> one DeviceHealth per device.
 *
 * This is the single function the UI calls. Everything else in `core/` is a
 * building block it composes. Keeping it pure (no React, no DOM, `now`
 * passed in) means the whole pipeline is testable with one fixture.
 */
import type { ResolvedConfig } from '../card/config';
import { applyEnhancers, type Enhancer } from '../enhancers';
import { detectLastHeard, detectOffline, isQuiet } from './availability';
import { detectBattery } from './battery';
import {
  areaName,
  collectDeviceGroups,
  displayName,
  dominantIntegration,
  type DeviceGroup,
} from './group';
import {
  batterySeverity,
  connectivitySeverity,
  extrasSeverity,
  resolveQuietThreshold,
  worstSeverity,
} from './thresholds';
import type { DeviceHealth, HassLike } from './types';

export interface AnalyseOptions {
  now: Date;
  enhancers?: readonly Enhancer[];
}

function isExcluded(group: DeviceGroup, integration: string, config: ResolvedConfig): boolean {
  if (config.exclude_integrations.includes(integration)) return true;
  if (config.exclude_devices.includes(group.deviceId)) return true;
  // Allow excluding an orphan by its bare entity id too.
  if (!group.device) {
    const entityId = group.entities[0]?.entity_id;
    if (entityId && config.exclude_devices.includes(entityId)) return true;
  }
  return false;
}

/** Drop individually excluded entities from a group. Returns null if nothing is left. */
function withoutExcludedEntities(group: DeviceGroup, config: ResolvedConfig): DeviceGroup | null {
  if (config.exclude_entities.length === 0) return group;
  const banned = new Set(config.exclude_entities);
  const entities = group.entities.filter((e) => !banned.has(e.entity_id));
  if (entities.length === 0) return null;
  const states = group.states.filter((s) => !banned.has(s.entity_id));
  return { ...group, entities, states };
}

export function analyseDevices(
  hass: HassLike,
  config: ResolvedConfig,
  options: AnalyseOptions,
): DeviceHealth[] {
  const { now, enhancers = [] } = options;
  const results: DeviceHealth[] = [];

  for (const rawGroup of collectDeviceGroups(hass)) {
    const integration = dominantIntegration(rawGroup.entities);
    if (isExcluded(rawGroup, integration, config)) continue;

    const group = withoutExcludedEntities(rawGroup, config);
    if (!group) continue;

    const battery = detectBattery(group.states, hass.entities);

    // A lone entity with no device is only interesting if it tells us about
    // a battery. Otherwise (template helpers, input_booleans...) it is noise.
    // And even then, it can only ever be a battery reading: with no device
    // behind it there is nothing to be "offline" or "quiet".
    const isOrphan = group.device === null;
    if (isOrphan && !battery) continue;

    const isOffline = !isOrphan && detectOffline(group.entities, hass.states);
    const lastHeard = detectLastHeard(group.states, hass.entities);

    // Quiet detection only makes sense for devices expected to report on
    // their own. By default that is battery devices; mains devices go
    // `unavailable` when they drop off, and an untouched light is not news.
    const quietEligible =
      !isOrphan && !isOffline && (config.quiet_scope === 'all' || battery !== undefined);
    const quietHours = resolveQuietThreshold(config, integration, group.deviceId);
    const quiet = quietEligible && isQuiet(lastHeard, now, quietHours);

    const extras = applyEnhancers(enhancers, integration, group, hass);

    const severity = worstSeverity(
      batterySeverity(battery, config),
      connectivitySeverity(isOffline, quiet),
      extrasSeverity(extras),
    );

    const health: DeviceHealth = {
      deviceId: group.deviceId,
      name: displayName(group),
      integration,
      isOffline,
      isQuiet: quiet,
      severity,
      extras,
      entityIds: group.entities.map((e) => e.entity_id),
    };
    // `exactOptionalPropertyTypes` means we must leave optional keys out
    // rather than set them to undefined. Verbose, but it keeps `health`
    // honest: a missing key really is missing.
    const area = areaName(group, hass);
    if (area !== undefined) health.area = area;
    if (group.device?.manufacturer) health.manufacturer = group.device.manufacturer;
    if (group.device?.model) health.model = group.device.model;
    if (battery) health.battery = battery;
    if (lastHeard) health.lastHeard = lastHeard;

    results.push(health);
  }

  return results;
}
