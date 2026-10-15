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

export function analyseDevices(
  hass: HassLike,
  config: ResolvedConfig,
  options: AnalyseOptions,
): DeviceHealth[] {
  const { now, enhancers = [] } = options;
  const results: DeviceHealth[] = [];

  for (const group of collectDeviceGroups(hass)) {
    const integration = dominantIntegration(group.entities);
    if (isExcluded(group, integration, config)) continue;

    const battery = detectBattery(group.states);

    // A lone entity with no device is only interesting if it tells us about
    // a battery. Otherwise (template helpers, input_booleans...) it is noise.
    if (!group.device && !battery) continue;

    const isOffline = detectOffline(group.entities, hass.states);
    const lastHeard = detectLastHeard(group.states);
    const quietHours = resolveQuietThreshold(config, integration, group.deviceId);
    // An offline device is already flagged; don't double-report it as quiet.
    const quiet = !isOffline && isQuiet(lastHeard, now, quietHours);

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
