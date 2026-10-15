/**
 * The integration's data: the websocket subscription, battery history and
 * the services the card calls.
 *
 * The Pulse Check integration (github.com/yog18r/pulse-check-integration)
 * registers two websocket commands:
 *
 *   pulse_check/subscribe   streams a full `Snapshot` now and after every
 *                           recompute (about 2 s after a relevant change,
 *                           and at least every 5 minutes)
 *   pulse_check/history     sparkline points for one battery over N days
 *
 * and the services `pulse_check.snooze`, `unsnooze`, `mark_replaced`,
 * `mark_charged` and `set_device_settings`.
 *
 * Everything that arrives is parsed defensively: the payload comes from
 * outside, so a malformed entry is skipped rather than crashing the card.
 */
import {
  EMPTY_ACTIONS,
  type ActionItem,
  type ActionList,
  type ShoppingLine,
} from '../core/actions';
import { isDeviceType } from '../core/deviceType';
import type { BatteryHistory, DrainPoint } from '../core/drain';
import { EMPTY_SUMMARY, type Summary } from '../core/summarise';
import type { Thresholds } from '../core/thresholds';
import type {
  BatteryReading,
  DeviceHealth,
  EnhancerExtra,
  Estimate,
  HassLike,
  Severity,
  UnsubscribeFunc,
} from '../core/types';

/** Per-device settings as stored by the integration (`set_device_settings`). */
export interface DeviceSettings {
  name?: string;
  area?: string;
  quiet_threshold_hours?: number;
  /** Free text, usually a standard size: "CR2032", "AA", "Built-in rechargeable". */
  battery_type?: string;
  battery_count?: number;
  rechargeable?: boolean;
  notify_policy?: NotifyPolicy;
  /** Sparkline window for this device, in days (1-365). Overrides the card's. */
  sparkline_days?: number;
}

export const NOTIFY_POLICIES = ['instant', 'daily', 'weekly', 'none'] as const;
export type NotifyPolicy = (typeof NOTIFY_POLICIES)[number];

/** The rule inputs the integration used, so the card colours rows the same way. */
export interface RuleConfig extends Thresholds {
  quiet_threshold_hours: number;
  quiet_scope: 'battery' | 'all';
}

/** One `pulse_check/subscribe` event. */
export interface Snapshot {
  devices: DeviceHealth[];
  summary: Summary;
  actions: ActionList;
  config: RuleConfig;
  /** Device id -> settings. Device-less batteries are keyed `entity:<entity_id>`. */
  deviceSettings: Record<string, DeviceSettings>;
  computedAt?: Date;
}

/* ---- small parsers ----------------------------------------------------- */

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

function date(value: unknown): Date | undefined {
  if (typeof value !== 'string' || value === '') return undefined;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

function severity(value: unknown): Severity | undefined {
  return typeof value === 'string' && SEVERITIES.has(value) ? (value as Severity) : undefined;
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
    const sev = severity(item.severity);
    if (sev !== undefined) extra.severity = sev;
    extras.push(extra);
  }
  return extras;
}

const CONFIDENCES = new Set<string>(['high', 'medium', 'low']);

/** The integration's `estimate` object, or undefined if it is not usable. */
export function parseEstimate(raw: unknown): Estimate | undefined {
  if (!isRecord(raw)) return undefined;
  const daysLeft = num(raw.daysLeft);
  const basis = str(raw.basis);
  const confidence = str(raw.confidence);
  const kind = raw.kind === 'charge' ? 'charge' : raw.kind === 'replace' ? 'replace' : undefined;
  if (daysLeft === undefined || basis === undefined || !kind) return undefined;
  const estimate: Estimate = {
    daysLeft,
    basis,
    confidence:
      confidence !== undefined && CONFIDENCES.has(confidence)
        ? (confidence as Estimate['confidence'])
        : 'low',
    kind,
  };
  if (raw.openEnded === true) estimate.openEnded = true;
  return estimate;
}

/** One device entry -> DeviceHealth, or undefined if it is not usable. */
export function parseDevice(raw: unknown): DeviceHealth | undefined {
  if (!isRecord(raw)) return undefined;
  const deviceId = str(raw.deviceId);
  const name = str(raw.name);
  const integration = str(raw.integration);
  const sev = severity(raw.severity);
  if (deviceId === undefined || name === undefined || integration === undefined || !sev) {
    return undefined;
  }
  const device: DeviceHealth = {
    deviceId,
    name,
    integration,
    deviceType: isDeviceType(raw.deviceType) ? raw.deviceType : 'other',
    isOffline: raw.isOffline === true,
    isQuiet: raw.isQuiet === true,
    quietThresholdHours: num(raw.quietThresholdHours) ?? 24,
    severity: sev,
    extras: parseExtras(raw.extras),
    entityIds: Array.isArray(raw.entityIds)
      ? raw.entityIds.filter((id): id is string => typeof id === 'string')
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
  const lastHeard = date(raw.lastHeard);
  if (lastHeard) device.lastHeard = lastHeard;
  const snoozedUntil = date(raw.snoozedUntil);
  if (snoozedUntil) device.snoozedUntil = snoozedUntil;
  const daysLeft = num(raw.daysLeft);
  if (daysLeft !== undefined) device.daysLeft = daysLeft;
  const estimate = parseEstimate(raw.estimate);
  if (estimate) device.estimate = estimate;
  const batteryKind = str(raw.batteryKind);
  if (batteryKind === 'charged' || batteryKind === 'replaceable' || batteryKind === 'unknown') {
    device.batteryKind = batteryKind;
  }
  const lastReplaced = date(raw.lastReplaced);
  if (lastReplaced) device.lastReplaced = lastReplaced;
  const unusual = str(raw.unusual);
  if (unusual !== undefined) device.unusual = unusual;
  return device;
}

function parseSummary(raw: unknown): Summary {
  if (!isRecord(raw)) return EMPTY_SUMMARY;
  const summary = { ...EMPTY_SUMMARY };
  for (const key of Object.keys(summary) as (keyof Summary)[]) {
    summary[key] = num(raw[key]) ?? 0;
  }
  return summary;
}

function parseActionItem(raw: unknown): ActionItem | undefined {
  if (!isRecord(raw)) return undefined;
  const kind = raw.kind === 'charge' ? 'charge' : raw.kind === 'replace' ? 'replace' : undefined;
  const deviceId = str(raw.deviceId);
  const name = str(raw.name);
  const sev = severity(raw.severity);
  const label = str(raw.label);
  if (!kind || deviceId === undefined || name === undefined || !sev || label === undefined) {
    return undefined;
  }
  return {
    kind,
    deviceId,
    name,
    severity: sev,
    batteryType: str(raw.batteryType) ?? 'Unknown type',
    count: num(raw.count) ?? 1,
    label,
  };
}

function parseActions(raw: unknown): ActionList {
  if (!isRecord(raw)) return EMPTY_ACTIONS;
  const items = (list: unknown) =>
    Array.isArray(list)
      ? list.map(parseActionItem).filter((i): i is ActionItem => i !== undefined)
      : [];
  const shopping: ShoppingLine[] = Array.isArray(raw.shopping)
    ? raw.shopping.flatMap((line: unknown) => {
        if (!isRecord(line)) return [];
        const batteryType = str(line.batteryType);
        if (batteryType === undefined) return [];
        return [{ batteryType, count: num(line.count) ?? 0, devices: num(line.devices) ?? 0 }];
      })
    : [];
  return { replace: items(raw.replace), charge: items(raw.charge), shopping };
}

const DEFAULT_RULES: RuleConfig = {
  battery_warning: 30,
  battery_critical: 15,
  quiet_threshold_hours: 24,
  quiet_scope: 'battery',
};

function parseRules(raw: unknown): RuleConfig {
  if (!isRecord(raw)) return DEFAULT_RULES;
  return {
    battery_warning: num(raw.battery_warning) ?? DEFAULT_RULES.battery_warning,
    battery_critical: num(raw.battery_critical) ?? DEFAULT_RULES.battery_critical,
    quiet_threshold_hours: num(raw.quiet_threshold_hours) ?? DEFAULT_RULES.quiet_threshold_hours,
    quiet_scope: raw.quiet_scope === 'all' ? 'all' : 'battery',
  };
}

export function parseDeviceSettings(raw: unknown): DeviceSettings {
  if (!isRecord(raw)) return {};
  const settings: DeviceSettings = {};
  const name = str(raw.name);
  if (name !== undefined) settings.name = name;
  const area = str(raw.area);
  if (area !== undefined) settings.area = area;
  const quiet = num(raw.quiet_threshold_hours);
  if (quiet !== undefined) settings.quiet_threshold_hours = quiet;
  const type = str(raw.battery_type);
  if (type !== undefined) settings.battery_type = type;
  const count = num(raw.battery_count);
  if (count !== undefined) settings.battery_count = count;
  if (typeof raw.rechargeable === 'boolean') settings.rechargeable = raw.rechargeable;
  const policy = str(raw.notify_policy);
  if (policy !== undefined && (NOTIFY_POLICIES as readonly string[]).includes(policy)) {
    settings.notify_policy = policy as NotifyPolicy;
  }
  const days = num(raw.sparkline_days);
  if (days !== undefined && days >= 1) settings.sparkline_days = Math.floor(days);
  return settings;
}

/** A whole subscription event -> Snapshot. Never throws. */
export function parseSnapshot(raw: unknown): Snapshot {
  const record = isRecord(raw) ? raw : {};
  const devices = Array.isArray(record.devices)
    ? record.devices.map(parseDevice).filter((d): d is DeviceHealth => d !== undefined)
    : [];
  const deviceSettings: Record<string, DeviceSettings> = {};
  if (isRecord(record.device_settings)) {
    for (const [id, value] of Object.entries(record.device_settings)) {
      deviceSettings[id] = parseDeviceSettings(value);
    }
  }
  const snapshot: Snapshot = {
    devices,
    summary: parseSummary(record.summary),
    actions: parseActions(record.actions),
    config: parseRules(record.config),
    deviceSettings,
  };
  const computedAt = date(record.computed_at);
  if (computedAt) snapshot.computedAt = computedAt;
  return snapshot;
}

/* ---- subscription ------------------------------------------------------ */

/** Why a subscription could not be made. */
export type SubscribeFailure = 'missing' | 'error';

export interface SubscribeHandlers {
  onSnapshot: (snapshot: Snapshot) => void;
  onError: (kind: SubscribeFailure, message: string) => void;
}

/** Error codes HA sends when the integration is not there. */
const MISSING_CODES = new Set(['not_loaded', 'unknown_command']);

function errorKind(err: unknown): [SubscribeFailure, string] {
  if (isRecord(err)) {
    const code = str(err.code);
    const message = str(err.message) ?? code ?? 'subscription failed';
    if (code !== undefined && MISSING_CODES.has(code)) return ['missing', message];
    return ['error', message];
  }
  return ['error', err instanceof Error ? err.message : String(err)];
}

/**
 * Subscribe to the integration's snapshots. Returns a function that stops
 * the subscription; safe to call before the subscription was confirmed.
 */
export function subscribeSnapshots(hass: HassLike, handlers: SubscribeHandlers): () => void {
  const connection = hass.connection;
  if (!connection) {
    handlers.onError('error', 'No websocket connection');
    return () => undefined;
  }
  let cancelled = false;
  let unsubscribe: UnsubscribeFunc | undefined;
  connection
    .subscribeMessage(
      (message) => {
        if (!cancelled) handlers.onSnapshot(parseSnapshot(message));
      },
      { type: 'pulse_check/subscribe' },
    )
    .then((unsub) => {
      if (cancelled) void unsub();
      else unsubscribe = unsub;
    })
    .catch((err: unknown) => {
      if (!cancelled) handlers.onError(...errorKind(err));
    });
  return () => {
    cancelled = true;
    void unsubscribe?.();
  };
}

/* ---- history ----------------------------------------------------------- */

/** Fetch sparkline points for one battery; undefined when hass cannot ask. */
export async function loadHistory(
  hass: HassLike,
  entityId: string,
  days: number,
): Promise<BatteryHistory | undefined> {
  if (!hass.callWS) return undefined;
  const raw = await hass.callWS<unknown>({
    type: 'pulse_check/history',
    entity_id: entityId,
    days,
  });
  if (!isRecord(raw)) return undefined;
  const points: DrainPoint[] = Array.isArray(raw.points)
    ? raw.points.flatMap((p: unknown) => {
        if (!isRecord(p)) return [];
        const time = num(p.time);
        const level = num(p.level);
        return time !== undefined && level !== undefined ? [{ time, level }] : [];
      })
    : [];
  const history: BatteryHistory = { points, days: num(raw.days) ?? days };
  const estimate = parseEstimate(raw.estimate);
  if (estimate) history.estimate = estimate;
  return history;
}

/* ---- services ---------------------------------------------------------- */

export type PulseCheckService =
  'snooze' | 'unsnooze' | 'mark_replaced' | 'mark_charged' | 'set_device_settings';

/** Call one of the integration's services, if hass can. */
export async function callPulseCheck(
  hass: HassLike | undefined,
  service: PulseCheckService,
  data: Record<string, unknown>,
): Promise<void> {
  if (!hass?.callService) return;
  await hass.callService('pulse_check', service, data);
}
