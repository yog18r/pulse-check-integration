/**
 * The orchestrator: `hass` + config -> one DeviceHealth per device.
 *
 * This is the single function the UI calls. Everything else in `core/` is a
 * building block it composes. Keeping it pure (no React, no DOM, `now`
 * passed in) means the whole pipeline is testable with one fixture.
 */
import type { ResolvedConfig } from '../card/config';
import { applyEnhancers, type Enhancer } from '../enhancers';
import { detectLastHeard, detectOffline, isQuiet, isStaticEntity } from './availability';
import { detectBattery } from './battery';
import {
  areaName,
  collectDeviceGroups,
  displayName,
  dominantIntegration,
  type DeviceGroup,
} from './group';
import { settingsForDevice } from './settings';
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
  /**
   * True "last reported" timestamps fetched on demand from HA's REST API,
   * keyed by entity id. The frontend's `last_updated` only moves when a
   * value changes; these move on every report. Used when newer.
   */
  lastReported?: ReadonlyMap<string, Date>;
  /** Devices the user has muted, with the time the snooze ends. */
  snoozes?: ReadonlyMap<string, Date>;
}

/** Case-insensitive membership test for user-typed lists. */
function listHas(list: string[], ...values: (string | undefined)[]): boolean {
  const wanted = new Set(list.map((v) => v.trim().toLowerCase()));
  return values.some((v) => v !== undefined && wanted.has(v.trim().toLowerCase()));
}

function isExcluded(
  group: DeviceGroup,
  integration: string,
  config: ResolvedConfig,
  hass: HassLike,
): boolean {
  // Integration allow/deny lists.
  if (config.include_integrations.length > 0 && !listHas(config.include_integrations, integration))
    return true;
  if (listHas(config.exclude_integrations, integration)) return true;

  // Area allow/deny lists, matching the area's id or its display name. A
  // per-device `area` setting stands in for the registry's area.
  if (config.include_areas.length > 0 || config.exclude_areas.length > 0) {
    const override = settingsForDevice(config, group.deviceId)?.area;
    const areaId =
      override ?? group.device?.area_id ?? group.entities.find((e) => e.area_id)?.area_id;
    const name = override ?? (areaId ? hass.areas[areaId]?.name : undefined);
    if (config.include_areas.length > 0 && !listHas(config.include_areas, areaId, name))
      return true;
    if (listHas(config.exclude_areas, areaId, name)) return true;
  }

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

/** The newest on-demand `last_reported` among the group's live entities. */
function newestReported(
  group: DeviceGroup,
  hass: HassLike,
  lastReported: ReadonlyMap<string, Date> | undefined,
): Date | undefined {
  if (!lastReported) return undefined;
  let newest: Date | undefined;
  for (const entity of group.entities) {
    if (isStaticEntity(entity.entity_id, hass.entities[entity.entity_id])) continue;
    const d = lastReported.get(entity.entity_id);
    if (d && (!newest || d > newest)) newest = d;
  }
  return newest;
}

export function analyseDevices(
  hass: HassLike,
  config: ResolvedConfig,
  options: AnalyseOptions,
): DeviceHealth[] {
  const { now, enhancers = [], lastReported, snoozes } = options;
  const results: DeviceHealth[] = [];

  for (const rawGroup of collectDeviceGroups(hass)) {
    const integration = dominantIntegration(rawGroup.entities);
    if (isExcluded(rawGroup, integration, config, hass)) continue;

    const group = withoutExcludedEntities(rawGroup, config);
    if (!group) continue;

    const battery = detectBattery(group.states, hass.entities);

    // A lone entity with no device is only interesting if it tells us about
    // a battery. Otherwise (template helpers, input_booleans...) it is noise.
    // And even then, it can only ever be a battery reading: with no device
    // behind it there is nothing to be "offline" or "quiet".
    const isOrphan = group.device === null;
    if (isOrphan && !battery) continue;

    // Enhancers run first so their better signals (a Z-Wave "dead" node, a
    // Zigbee2MQTT last_seen timestamp) can feed the generic rules below.
    const enhanced = applyEnhancers(enhancers, integration, group, hass);
    const { extras } = enhanced;

    const isOffline =
      !isOrphan && (enhanced.offline === true || detectOffline(group.entities, hass.states));

    // Last heard: the best of the frontend heuristic, any enhancer signal,
    // and any on-demand last_reported lookup. Newest wins.
    let lastHeard = detectLastHeard(group.states, hass.entities);
    for (const candidate of [enhanced.lastHeard, newestReported(group, hass, lastReported)]) {
      if (candidate && (!lastHeard || candidate > lastHeard)) lastHeard = candidate;
    }

    // Quiet detection only makes sense for devices expected to report on
    // their own. By default that is battery devices; mains devices go
    // `unavailable` when they drop off, and an untouched light is not news.
    const quietEligible =
      !isOrphan && !isOffline && (config.quiet_scope === 'all' || battery !== undefined);
    const quietHours = resolveQuietThreshold(config, integration, group.deviceId);
    const quiet = quietEligible && isQuiet(lastHeard, now, quietHours);

    const snoozedUntil = snoozes?.get(group.deviceId);
    const snoozed = snoozedUntil !== undefined && snoozedUntil > now;

    const severity = snoozed
      ? 'ok'
      : worstSeverity(
          batterySeverity(battery, config),
          connectivitySeverity(isOffline, quiet),
          extrasSeverity(extras),
        );

    const health: DeviceHealth = {
      deviceId: group.deviceId,
      // The user's display name wins over the registry's. It changes only
      // what the card shows; the device itself keeps its name.
      name: settingsForDevice(config, group.deviceId)?.name ?? displayName(group),
      integration,
      isOffline,
      isQuiet: quiet,
      quietThresholdHours: quietHours,
      severity,
      extras,
      entityIds: group.entities.map((e) => e.entity_id),
    };
    // `exactOptionalPropertyTypes` means we must leave optional keys out
    // rather than set them to undefined. Verbose, but it keeps `health`
    // honest: a missing key really is missing.
    const area = settingsForDevice(config, group.deviceId)?.area ?? areaName(group, hass);
    if (area !== undefined) health.area = area;
    if (group.device?.manufacturer) health.manufacturer = group.device.manufacturer;
    if (group.device?.model) health.model = group.device.model;
    if (battery) health.battery = battery;
    if (lastHeard) health.lastHeard = lastHeard;
    if (snoozed) health.snoozedUntil = snoozedUntil;

    results.push(health);
  }

  return results;
}

/**
 * Entities worth asking HA's REST API about: the live entities of devices
 * currently flagged quiet. Tiny list by design; the lookup is only there to
 * un-flag devices that report unchanged values, so there's no point asking
 * about devices that are fine.
 */
export function lastReportedCandidates(devices: DeviceHealth[], hass: HassLike): string[] {
  const ids: string[] = [];
  for (const d of devices) {
    if (!d.isQuiet) continue;
    for (const id of d.entityIds) {
      if (!isStaticEntity(id, hass.entities[id])) ids.push(id);
    }
  }
  return ids;
}
