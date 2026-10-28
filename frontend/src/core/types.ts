/**
 * Core data types.
 *
 * The card is a renderer: the Pulse Check integration computes everything
 * on the server and streams it over a websocket subscription (see
 * `src/card/snapshot.ts`). These types describe two things:
 *
 *  1. The slice of Home Assistant's frontend `hass` object the card still
 *     reads: the registries (for the editor's device picker), the
 *     websocket connection, and service calls. We define our own narrow
 *     interfaces rather than importing HA's, so the card has zero runtime
 *     dependencies on HA packages and the fixtures stay small.
 *  2. The wire shape of what the integration sends: one `DeviceHealth`
 *     per physical device. This is the integration's `DeviceHealth.to_dict()`
 *     with the timestamps parsed into Dates.
 *
 * TypeScript note: an `interface` describes the *shape* of an object. It
 * exists only at compile time; nothing is emitted to the bundle.
 */
import type { DeviceType } from './deviceType';

/* ------------------------------------------------------------------------ */
/* Input: the parts of `hass` we use                                        */
/* ------------------------------------------------------------------------ */

/** One entry in `hass.states`. Only used to name device-less battery sensors. */
export interface HassEntityState {
  entity_id: string;
  /** Always a string in HA, even for numbers ("87") or timestamps. */
  state: string;
  attributes: Record<string, unknown>;
  last_changed: string;
  last_updated: string;
}

/** One entry in `hass.entities` (the entity registry, display subset). */
export interface HassEntityRegistryEntry {
  entity_id: string;
  device_id?: string;
  area_id?: string;
  /** Integration domain that provides the entity, e.g. "zha", "mqtt", "zwave_js". */
  platform?: string;
  /** "diagnostic" or "config" entities are secondary; undefined means primary. */
  entity_category?: 'diagnostic' | 'config';
  hidden?: boolean;
  name?: string;
}

/** One entry in `hass.devices` (the device registry). */
export interface HassDeviceRegistryEntry {
  id: string;
  name: string | null;
  /** The user's rename, which should win over `name` when present. */
  name_by_user: string | null;
  manufacturer: string | null;
  model: string | null;
  area_id: string | null;
  /** "service" marks virtual devices (Sun, Forecast, etc.) that have no hardware. */
  entry_type: 'service' | null;
  disabled_by: string | null;
}

/** One entry in `hass.areas`. */
export interface HassAreaRegistryEntry {
  area_id: string;
  name: string;
}

/** Returned by `subscribeMessage`: call it to stop receiving events. */
export type UnsubscribeFunc = () => Promise<void>;

/** The part of HA's websocket connection object the card uses. */
export interface HassConnection {
  subscribeMessage(
    callback: (message: unknown) => void,
    message: Record<string, unknown>,
    /** `resubscribe: false`: do not re-send it after a reconnect; the card does that itself. */
    options?: { resubscribe?: boolean },
  ): Promise<UnsubscribeFunc>;
  /** "ready" fires when the connection is back after Home Assistant restarted. */
  addEventListener?(event: 'ready', listener: () => void): void;
  removeEventListener?(event: 'ready', listener: () => void): void;
}

/**
 * The subset of the frontend `hass` object the card reads.
 *
 * `Record<string, T>` is TypeScript's type for "an object used as a map from
 * string keys to T values", which is exactly how HA stores these.
 */
export interface HassLike {
  states: Record<string, HassEntityState>;
  entities: Record<string, HassEntityRegistryEntry>;
  devices: Record<string, HassDeviceRegistryEntry>;
  areas: Record<string, HassAreaRegistryEntry>;
  /** The websocket connection, for the integration's subscription. */
  connection?: HassConnection;
  /** Home Assistant's run state: "STARTING" while integrations are still loading. */
  config?: { state?: string };
  /** Send a websocket command and await the result (used for history). */
  callWS?: <T>(message: Record<string, unknown>) => Promise<T>;
  /** The user's language and formats; `language` is the code, e.g. "de" or "pt-BR". */
  locale?: { language?: string };
  /** The user's language on older Home Assistant versions. */
  language?: string;
  /** Call a Home Assistant service (snooze, mark replaced, device settings). */
  callService?: (
    domain: string,
    service: string,
    data?: Record<string, unknown>,
  ) => Promise<unknown>;
}

/**
 * The latest `hass`, always. Home Assistant hands the card a new `hass`
 * object several times a second; React must not re-render on each one, so
 * components get this mutable box and read `.latest` when they act. (It is
 * deliberately not a React ref: reading it during render is the point.)
 */
export interface HassBox {
  latest: HassLike | undefined;
}

/** Prefix of the synthetic id the integration gives a device-less entity. */
export const ORPHAN_PREFIX = 'entity:';

/* ------------------------------------------------------------------------ */
/* Output: what the integration computes                                    */
/* ------------------------------------------------------------------------ */

/** Traffic-light severity used for colouring and sorting. */
export type Severity = 'ok' | 'warning' | 'critical';

/** Where a battery reading came from. Shown in the UI as a hint. */
export type BatterySource = 'sensor' | 'binary' | 'attribute';

export interface BatteryReading {
  /** 0-100 when a numeric level is known. Absent for binary "low battery" sensors. */
  level?: number;
  /** True when a binary low-battery sensor reports "on". */
  isLow: boolean;
  /** True when the device reports it is charging or docked. */
  isCharging?: boolean;
  source: BatterySource;
  /** The entity the reading was taken from, for sparklines and tap-through. */
  entityId: string;
}

/** A small badge contributed by an integration-specific enhancer, e.g. { label: "Node", value: "asleep" }. */
export interface EnhancerExtra {
  label: string;
  value: string;
  severity?: Severity;
}

export type BatteryKind = 'charged' | 'replaceable' | 'unknown';

/** A days-left estimate with its provenance, as the integration computes it. */
export interface Estimate {
  daysLeft: number;
  /** Plain words for a tooltip: "trend over current cycle", "until charge needed". */
  basis: string;
  confidence: 'high' | 'medium' | 'low';
  /** "replace": days until empty. "charge": days until the warning level. */
  kind: 'replace' | 'charge';
  /** "More than a year": daysLeft is a floor, not a prediction. */
  openEnded?: boolean;
}

/** Everything the UI needs to render one device row. */
export interface DeviceHealth {
  deviceId: string;
  name: string;
  area?: string;
  manufacturer?: string;
  model?: string;
  /** Integration domain, e.g. "zwave_js". "unknown" when the registry has no platform. */
  integration: string;
  battery?: BatteryReading;
  /** The newest report across the device's live entities. */
  lastHeard?: Date;
  /** True when every primary (non-diagnostic, non-config) entity is unavailable. */
  isOffline: boolean;
  /** True when `lastHeard` is older than the device's quiet threshold. */
  isQuiet: boolean;
  /**
   * True when the integration no longer provides the entities that would
   * make the device offline: stale configuration left by an integration
   * update, to delete in Home Assistant. Never also offline or quiet.
   */
  isNotProvided?: boolean;
  /** The threshold that applied to this device, after overrides, in hours. */
  quietThresholdHours: number;
  /** Set while the user has snoozed this device; severity is then "ok". */
  snoozedUntil?: Date;
  severity: Severity;
  /** What kind of thing it is, for grouping: "lock", "motion", "phone"... */
  deviceType: DeviceType;
  extras: EnhancerExtra[];
  /** Every entity id that belongs to this device, so the UI can drill down. */
  entityIds: string[];
  /** Days until empty (or until a charge is needed), from the integration's cycles. */
  daysLeft?: number;
  /** Where `daysLeft` came from and how much to trust it. */
  estimate?: Estimate;
  /** "charged", "replaceable" or "unknown", from the battery's history. */
  batteryKind?: BatteryKind;
  /** When the battery was last replaced or charged. */
  lastReplaced?: Date;
  /** A note when the battery behaves unlike its own past, e.g. "draining 3× faster than usual". */
  unusual?: string;
}
