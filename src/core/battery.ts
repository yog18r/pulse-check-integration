/**
 * Battery detection.
 *
 * Three rules, applied to every entity of a device, in order of preference:
 *
 *  1. `sensor.*` with `device_class: battery` and a numeric state  -> level in %
 *  2. `binary_sensor.*` with `device_class: battery`               -> on means LOW
 *  3. Any entity with a numeric `battery_level` attribute         -> level in %
 *     (older or custom integrations that never got a dedicated sensor)
 *
 * The functions here are pure: same input, same output, no side effects.
 * That is what makes them trivial to unit test.
 */
import type { BatteryReading, HassEntityRegistryEntry, HassEntityState } from './types';

/** Entity ids look like "domain.object_id". The domain tells us the entity type. */
export function domainOf(entityId: string): string {
  return entityId.split('.', 1)[0] ?? '';
}

/**
 * HA stores every state as a string. "87" is a battery level, but so are
 * "87.0" and " 87 ". "unavailable", "unknown" and "" are not.
 */
export function parseNumeric(value: unknown): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  if (trimmed === '') return undefined;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : undefined;
}

function clampPercent(n: number): number {
  return Math.min(100, Math.max(0, Math.round(n)));
}

/**
 * Try to read a battery value from a single entity.
 * Returns `undefined` when the entity says nothing about battery.
 */
export function readBattery(state: HassEntityState): BatteryReading | undefined {
  const domain = domainOf(state.entity_id);
  const deviceClass = state.attributes.device_class;

  // Rule 1: numeric battery sensor
  if (domain === 'sensor' && deviceClass === 'battery') {
    const level = parseNumeric(state.state);
    if (level === undefined) return undefined; // unavailable / unknown
    return {
      level: clampPercent(level),
      isLow: false,
      source: 'sensor',
      entityId: state.entity_id,
    };
  }

  // Rule 2: binary low-battery sensor. "on" means the battery IS low.
  if (domain === 'binary_sensor' && deviceClass === 'battery') {
    if (state.state !== 'on' && state.state !== 'off') return undefined;
    return { isLow: state.state === 'on', source: 'binary', entityId: state.entity_id };
  }

  // Rule 3: battery_level attribute on anything else
  const attrLevel = parseNumeric(state.attributes.battery_level);
  if (attrLevel !== undefined) {
    return {
      level: clampPercent(attrLevel),
      isLow: false,
      source: 'attribute',
      entityId: state.entity_id,
    };
  }

  return undefined;
}

/** Lower number = preferred source when a device offers several. */
const SOURCE_RANK: Record<BatteryReading['source'], number> = {
  sensor: 0,
  attribute: 1,
  binary: 2,
};

/**
 * A device often exposes more than one battery signal (a % sensor AND a
 * low-battery binary sensor, or one % sensor per cell). Collapse them to one:
 *
 *  - prefer a numeric level from a sensor, then an attribute, then binary
 *  - among numeric readings, the lowest level wins (the weakest cell matters)
 *  - if ANY binary sensor says low, the combined reading is flagged low
 */
export function combineBatteryReadings(readings: BatteryReading[]): BatteryReading | undefined {
  if (readings.length === 0) return undefined;

  const anyBinaryLow = readings.some((r) => r.source === 'binary' && r.isLow);

  const best = [...readings].sort((a, b) => {
    const rank = SOURCE_RANK[a.source] - SOURCE_RANK[b.source];
    if (rank !== 0) return rank;
    return (a.level ?? 101) - (b.level ?? 101);
  })[0];

  // `best` cannot be undefined here because the array is non-empty, but
  // `noUncheckedIndexedAccess` makes TS ask us to prove it.
  if (!best) return undefined;

  return { ...best, isLow: best.isLow || anyBinaryLow };
}

/**
 * Scan a device's entity states and return its single battery reading.
 *
 * `registry` is `hass.entities`. When given, entities marked
 * `entity_category: config` are skipped: those are settings (an inverter's
 * "minimum state of charge", a thermostat's "battery type" selector), and
 * some integrations label them `device_class: battery` because the unit is %.
 */
export function detectBattery(
  states: HassEntityState[],
  registry: Record<string, HassEntityRegistryEntry> = {},
): BatteryReading | undefined {
  const readings: BatteryReading[] = [];
  for (const s of states) {
    if (registry[s.entity_id]?.entity_category === 'config') continue;
    const r = readBattery(s);
    if (r) readings.push(r);
  }
  const combined = combineBatteryReadings(readings);
  if (combined && detectCharging(states)) combined.isCharging = true;
  return combined;
}

/** States that integrations use to say "plugged in". */
const CHARGING_STATES = new Set(['charging', 'full']);

/**
 * Is any entity on this device saying it is charging? Integrations spell
 * this many ways; these cover the common ones:
 *
 *  - binary_sensor with device_class battery_charging (the HA standard)
 *  - a "battery state" sensor reading charging/full (companion app)
 *  - a vacuum that is docked
 *  - boolean attributes: is_charging, charging, battery_charging
 *  - a battery_state attribute reading charging
 */
export function detectCharging(states: HassEntityState[]): boolean {
  for (const s of states) {
    const domain = domainOf(s.entity_id);
    const attrs = s.attributes;

    if (domain === 'binary_sensor' && attrs.device_class === 'battery_charging') {
      if (s.state === 'on') return true;
      continue;
    }
    if (domain === 'sensor' && s.entity_id.includes('battery') && CHARGING_STATES.has(s.state)) {
      return true;
    }
    if (domain === 'vacuum' && s.state === 'docked') return true;
    if (attrs.is_charging === true || attrs.charging === true || attrs.battery_charging === true) {
      return true;
    }
    if (typeof attrs.battery_state === 'string' && CHARGING_STATES.has(attrs.battery_state)) {
      return true;
    }
  }
  return false;
}
