/**
 * Integration mode: read the device list the Pulse Check integration
 * computed on the server, instead of analysing in the browser.
 *
 * The integration (github.com/yog18r/pulse-check-integration) publishes
 * `sensor.pulse_check_attention`, whose `devices` attribute carries one
 * entry per device in exactly this card's `DeviceHealth` shape (the two
 * implementations share a golden test), plus a few extras the browser
 * cannot compute: days left from recorder history, when the battery was
 * last replaced, and an "unusual behaviour" note. Snoozes and
 * replacements become service calls, so they are shared across every
 * browser and user.
 *
 * Everything here is defensive: the attribute comes from outside, so a
 * malformed entry is skipped rather than crashing the card.
 */
import { parseTimestamp } from '../core/availability';
import { DEVICE_TYPES, type DeviceType } from '../core/deviceType';
import type {
  BatteryReading,
  DeviceHealth,
  EnhancerExtra,
  HassLike,
  Severity,
} from '../core/types';

export const DEFAULT_INTEGRATION_ENTITY = 'sensor.pulse_check_attention';

export interface IntegrationSource {
  devices: DeviceHealth[];
  /** When the integration last computed the list. */
  computedAt?: Date;
}

const SEVERITIES = new Set<string>(['ok', 'warning', 'critical']);
const SOURCES = new Set<string>(['sensor', 'binary', 'attribute']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function parseBattery(raw: unknown): BatteryReading | undefined {
  if (!isRecord(raw)) return undefined;
  const source = str(raw.source);
  const entityId = str(raw.entityId);
  if (source === undefined || !SOURCES.has(source) || entityId === undefined) return undefined;
  const battery: BatteryReading = {
    isLow: raw.isLow === true,
    source: source as BatteryReading['source'],
    entityId,
  };
  const level = num(raw.level);
  if (level !== undefined) battery.level = level;
  if (raw.isCharging === true) battery.isCharging = true;
  return battery;
}

function parseExtras(raw: unknown): EnhancerExtra[] {
  if (!Array.isArray(raw)) return [];
  const extras: EnhancerExtra[] = [];
  for (const item of raw) {
    if (!isRecord(item)) continue;
    const label = str(item.label);
    const value = str(item.value);
    if (label === undefined || value === undefined) continue;
    const extra: EnhancerExtra = { label, value };
    const severity = str(item.severity);
    if (severity !== undefined && SEVERITIES.has(severity)) extra.severity = severity as Severity;
    extras.push(extra);
  }
  return extras;
}

function parseDeviceType(value: unknown): DeviceType {
  return typeof value === 'string' && (DEVICE_TYPES as readonly string[]).includes(value)
    ? (value as DeviceType)
    : 'other';
}

/** One attribute entry -> DeviceHealth, or undefined if it is not usable. */
export function parseDevice(raw: unknown): DeviceHealth | undefined {
  if (!isRecord(raw)) return undefined;
  const deviceId = str(raw.deviceId);
  const name = str(raw.name);
  const integration = str(raw.integration);
  const severity = str(raw.severity);
  if (
    deviceId === undefined ||
    name === undefined ||
    integration === undefined ||
    severity === undefined ||
    !SEVERITIES.has(severity)
  ) {
    return undefined;
  }
  const device: DeviceHealth = {
    deviceId,
    name,
    integration,
    deviceType: parseDeviceType(raw.deviceType),
    isOffline: raw.isOffline === true,
    isQuiet: raw.isQuiet === true,
    quietThresholdHours: num(raw.quietThresholdHours) ?? 24,
    severity: severity as Severity,
    extras: parseExtras(raw.extras),
    entityIds: Array.isArray(raw.entityIds)
      ? raw.entityIds.filter((id) => typeof id === 'string')
      : [],
  };
  const area = str(raw.area);
  if (area !== undefined) device.area = area;
  const manufacturer = str(raw.manufacturer);
  if (manufacturer !== undefined) device.manufacturer = manufacturer;
  const model = str(raw.model);
  if (model !== undefined) device.model = model;
  const battery = parseBattery(raw.battery);
  if (battery) device.battery = battery;
  const lastHeard = parseTimestamp(raw.lastHeard);
  if (lastHeard) device.lastHeard = lastHeard;
  const snoozedUntil = parseTimestamp(raw.snoozedUntil);
  if (snoozedUntil) device.snoozedUntil = snoozedUntil;
  const daysLeft = num(raw.daysLeft);
  if (daysLeft !== undefined) device.daysLeft = daysLeft;
  const lastReplaced = parseTimestamp(raw.lastReplaced);
  if (lastReplaced) device.lastReplaced = lastReplaced;
  const unusual = str(raw.unusual);
  if (unusual !== undefined) device.unusual = unusual;
  return device;
}

/** The integration's device list, or undefined when the sensor is not there. */
export function readIntegration(hass: HassLike, entityId: string): IntegrationSource | undefined {
  const state = hass.states[entityId];
  if (!state || state.state === 'unavailable') return undefined;
  const raw = state.attributes.devices;
  const devices = Array.isArray(raw)
    ? raw.map(parseDevice).filter((d): d is DeviceHealth => d !== undefined)
    : [];
  const source: IntegrationSource = { devices };
  const computedAt = parseTimestamp(state.attributes.computed_at);
  if (computedAt) source.computedAt = computedAt;
  return source;
}

/** Cheap change detection for the hass setter: the sensor's state and timestamp. */
export function integrationFingerprint(hass: HassLike, entityId: string): string {
  const state = hass.states[entityId];
  return state ? `${state.state}\u0001${state.last_updated}` : '';
}

/** Call one of the integration's services, if hass can. */
export async function callPulseCheck(
  hass: HassLike,
  service: 'snooze' | 'unsnooze' | 'mark_replaced' | 'mark_charged',
  data: Record<string, unknown>,
): Promise<void> {
  if (!hass.callService) return;
  await hass.callService('pulse_check', service, data);
}
