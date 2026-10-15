import { describe, expect, it } from 'vitest';
import {
  detectLastHeard,
  detectOffline,
  isQuiet,
  isStaticEntity,
  parseTimestamp,
} from '../../src/core/availability';
import { FIXED_NOW, hass, hoursAgo, makeEntity, makeState } from '../fixtures/hass';

const now = FIXED_NOW;

function entitiesOf(deviceId: string) {
  return Object.values(hass.entities).filter((e) => e.device_id === deviceId);
}

describe('detectOffline', () => {
  it('is offline when every primary entity is unavailable', () => {
    expect(detectOffline(entitiesOf('dev_zwave_lock'), hass.states)).toBe(true);
  });

  it('is online when primary entities have real states', () => {
    expect(detectOffline(entitiesOf('dev_z2m_door'), hass.states)).toBe(false);
  });

  it('ignores unavailable diagnostic entities when a primary entity is fine', () => {
    const entities = [
      makeEntity('sensor.temp', 'zha', 'd1'),
      makeEntity('sensor.rssi', 'zha', 'd1', { entity_category: 'diagnostic' }),
    ];
    const states = {
      'sensor.temp': makeState('sensor.temp', '21', now),
      'sensor.rssi': makeState('sensor.rssi', 'unavailable', now),
    };
    expect(detectOffline(entities, states)).toBe(false);
  });

  it('falls back to diagnostic entities when there are no primary ones', () => {
    const entities = [makeEntity('sensor.rssi', 'zha', 'd1', { entity_category: 'diagnostic' })];
    expect(
      detectOffline(entities, { 'sensor.rssi': makeState('sensor.rssi', 'unavailable', now) }),
    ).toBe(true);
    expect(detectOffline(entities, { 'sensor.rssi': makeState('sensor.rssi', '-60', now) })).toBe(
      false,
    );
  });

  it('is not offline when no entity has a state object at all', () => {
    expect(detectOffline([makeEntity('sensor.ghost', 'zha', 'd1')], {})).toBe(false);
  });
});

describe('parseTimestamp', () => {
  it('parses ISO strings and rejects garbage', () => {
    expect(parseTimestamp('2026-10-15T10:00:00.000Z')?.toISOString()).toBe(
      '2026-10-15T10:00:00.000Z',
    );
    expect(parseTimestamp('not a date')).toBeUndefined();
    expect(parseTimestamp('')).toBeUndefined();
    expect(parseTimestamp(undefined)).toBeUndefined();
  });
});

describe('detectLastHeard', () => {
  const zhaStates = () => entitiesOf('dev_zha_temp').map((e) => hass.states[e.entity_id]!);

  it('returns the newest last_updated across live entities', () => {
    // Temperature, lqi and rssi updated 30h ago; humidity 31h; battery 32h.
    // The identify button (config) was pressed 1h ago and must be ignored.
    expect(detectLastHeard(zhaStates(), hass.entities)?.toISOString()).toBe(hoursAgo(now, 30));
  });

  it('filters static domains (button, number...) even without a registry', () => {
    expect(detectLastHeard(zhaStates())?.toISOString()).toBe(hoursAgo(now, 30));
  });

  it('needs the registry to recognise a config-category sensor as static', () => {
    const states = [
      makeState('sensor.temp', '21', now, { lastUpdated: hoursAgo(now, 30) }),
      makeState('sensor.setting', '10', now, { lastUpdated: hoursAgo(now, 1) }),
    ];
    const registry = {
      'sensor.setting': makeEntity('sensor.setting', 'x', 'd', { entity_category: 'config' }),
    };
    expect(detectLastHeard(states)?.toISOString()).toBe(hoursAgo(now, 1));
    expect(detectLastHeard(states, registry)?.toISOString()).toBe(hoursAgo(now, 30));
  });

  it('falls back to static entities when a device has nothing else', () => {
    const states = [makeState('number.only_setting', '5', now, { lastUpdated: hoursAgo(now, 2) })];
    expect(detectLastHeard(states, {})?.toISOString()).toBe(hoursAgo(now, 2));
  });

  it('returns undefined when no timestamps parse', () => {
    const bad = makeState('sensor.a', '1', now, { lastUpdated: 'garbage' });
    expect(detectLastHeard([bad])).toBeUndefined();
    expect(detectLastHeard([])).toBeUndefined();
  });
});

describe('isStaticEntity', () => {
  it('treats config entities and setting-like domains as static', () => {
    expect(isStaticEntity('sensor.temp', { entity_id: 'sensor.temp' })).toBe(false);
    expect(isStaticEntity('sensor.temp', undefined)).toBe(false);
    expect(
      isStaticEntity('sensor.min_soc', { entity_id: 'sensor.min_soc', entity_category: 'config' }),
    ).toBe(true);
    for (const id of ['number.x', 'select.x', 'button.x', 'update.x', 'text.x']) {
      expect(isStaticEntity(id, undefined)).toBe(true);
    }
    expect(isStaticEntity('light.x', undefined)).toBe(false);
  });
});

describe('isQuiet', () => {
  it('compares age against the threshold in hours', () => {
    const thirtyHoursAgo = new Date(hoursAgo(now, 30));
    expect(isQuiet(thirtyHoursAgo, now, 24)).toBe(true);
    expect(isQuiet(thirtyHoursAgo, now, 48)).toBe(false);
  });

  it('treats exactly-at-threshold as not quiet', () => {
    const exactly = new Date(hoursAgo(now, 24));
    expect(isQuiet(exactly, now, 24)).toBe(false);
  });

  it('never calls an unknown timestamp quiet', () => {
    expect(isQuiet(undefined, now, 1)).toBe(false);
  });
});
