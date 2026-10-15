/**
 * Core data types.
 *
 * Everything in `src/core` is plain TypeScript with no React and no DOM, so
 * it can be unit-tested directly. These types describe two things:
 *
 *  1. The slice of Home Assistant's frontend `hass` object we read from
 *     (`HassLike` and friends). We define our own narrow interfaces rather
 *     than importing HA's, so the card has zero runtime dependencies on HA
 *     packages and the fixtures stay small.
 *  2. What the core produces: one `DeviceHealth` per physical device.
 *
 * TypeScript note: an `interface` describes the *shape* of an object. It
 * exists only at compile time; nothing is emitted to the bundle.
 */

/* ------------------------------------------------------------------------ */
/* Input: the parts of `hass` we use                                        */
/* ------------------------------------------------------------------------ */

/** One entry in `hass.states`. */
export interface HassEntityState {
  entity_id: string;
  /** Always a string in HA, even for numbers ("87") or timestamps. */
  state: string;
  attributes: Record<string, unknown>;
  /** ISO 8601 timestamp of the last time `state` changed. */
  last_changed: string;
  /**
   * ISO 8601 timestamp of the last time state OR attributes changed.
   * The frontend does not receive `last_reported`, so this is the best
   * "last heard from" signal available without a websocket round-trip.
   */
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

/**
 * The subset of the frontend `hass` object the core reads.
 *
 * `Record<string, T>` is TypeScript's type for "an object used as a map from
 * string keys to T values", which is exactly how HA stores these.
 */
export interface HassLike {
  states: Record<string, HassEntityState>;
  entities: Record<string, HassEntityRegistryEntry>;
  devices: Record<string, HassDeviceRegistryEntry>;
  areas: Record<string, HassAreaRegistryEntry>;
}

/* ------------------------------------------------------------------------ */
/* Output: what the core computes                                           */
/* ------------------------------------------------------------------------ */

/** Traffic-light severity used for colouring and sorting. */
export type Severity = 'ok' | 'warning' | 'critical';

/** Where a battery reading came from. Shown in the UI as a hint, and useful in tests. */
export type BatterySource = 'sensor' | 'binary' | 'attribute';

export interface BatteryReading {
  /** 0-100 when a numeric level is known. Absent for binary "low battery" sensors. */
  level?: number;
  /** True when a binary low-battery sensor reports "on". */
  isLow: boolean;
  source: BatterySource;
  /** The entity the reading was taken from, for debugging and tap-through. */
  entityId: string;
}

/**
 * A small piece of extra information contributed by an integration-specific
 * enhancer, e.g. { label: "Node", value: "asleep" } for Z-Wave JS.
 */
export interface EnhancerExtra {
  label: string;
  value: string;
  /** Optional: an enhancer can escalate severity, e.g. a "dead" Z-Wave node. */
  severity?: Severity;
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
  /** The most recent `last_updated` across the device's entities. */
  lastHeard?: Date;
  /** True when every primary (non-diagnostic, non-config) entity is unavailable. */
  isOffline: boolean;
  /** True when `lastHeard` is older than the device's quiet threshold. */
  isQuiet: boolean;
  severity: Severity;
  extras: EnhancerExtra[];
  /** Every entity id that belongs to this device, so the UI can drill down. */
  entityIds: string[];
}
