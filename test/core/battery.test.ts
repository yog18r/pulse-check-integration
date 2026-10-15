import { describe, expect, it } from 'vitest';
import {
  combineBatteryReadings,
  detectBattery,
  detectCharging,
  parseNumeric,
  readBattery,
} from '../../src/core/battery';
import { FIXED_NOW, hass, makeState } from '../fixtures/hass';

const now = FIXED_NOW;

describe('parseNumeric', () => {
  it('parses plain and decimal numeric strings', () => {
    expect(parseNumeric('87')).toBe(87);
    expect(parseNumeric('87.5')).toBe(87.5);
    expect(parseNumeric(' 12 ')).toBe(12);
    expect(parseNumeric(44)).toBe(44);
  });

  it('rejects non-numeric states', () => {
    expect(parseNumeric('unavailable')).toBeUndefined();
    expect(parseNumeric('unknown')).toBeUndefined();
    expect(parseNumeric('')).toBeUndefined();
    expect(parseNumeric(null)).toBeUndefined();
    expect(parseNumeric(undefined)).toBeUndefined();
    expect(parseNumeric(NaN)).toBeUndefined();
  });
});

describe('readBattery', () => {
  it('rule 1: reads a numeric battery sensor', () => {
    const r = readBattery(hass.states['sensor.front_door_battery']!);
    expect(r).toEqual({
      level: 87,
      isLow: false,
      source: 'sensor',
      entityId: 'sensor.front_door_battery',
    });
  });

  it('rule 1: clamps and rounds out-of-range values', () => {
    const over = makeState('sensor.x', '104.6', now, { attributes: { device_class: 'battery' } });
    const under = makeState('sensor.y', '-3', now, { attributes: { device_class: 'battery' } });
    expect(readBattery(over)?.level).toBe(100);
    expect(readBattery(under)?.level).toBe(0);
  });

  it('rule 1: ignores an unavailable battery sensor', () => {
    expect(readBattery(hass.states['sensor.front_door_lock_battery_level']!)).toBeUndefined();
  });

  it('rule 1 falls through to the attribute when the battery sensor state is not numeric', () => {
    const odd = makeState('sensor.odd_battery', 'unknown', now, {
      attributes: { device_class: 'battery', battery_level: 55 },
    });
    expect(readBattery(odd)).toEqual({
      level: 55,
      isLow: false,
      source: 'attribute',
      entityId: 'sensor.odd_battery',
    });
  });

  it('rule 2: reads a binary low-battery sensor', () => {
    const r = readBattery(hass.states['binary_sensor.hallway_smoke_alarm_battery_low']!);
    expect(r).toEqual({
      isLow: true,
      source: 'binary',
      entityId: 'binary_sensor.hallway_smoke_alarm_battery_low',
    });

    const ok = makeState('binary_sensor.z', 'off', now, {
      attributes: { device_class: 'battery' },
    });
    expect(readBattery(ok)?.isLow).toBe(false);
  });

  it('rule 3: falls back to a battery_level attribute', () => {
    const r = readBattery(hass.states['device_tracker.dog_collar']!);
    expect(r).toEqual({
      level: 44,
      isLow: false,
      source: 'attribute',
      entityId: 'device_tracker.dog_collar',
    });
  });

  it('returns undefined for entities that say nothing about battery', () => {
    expect(readBattery(hass.states['sensor.bedroom_climate_temperature']!)).toBeUndefined();
    expect(readBattery(hass.states['binary_sensor.front_door_contact']!)).toBeUndefined();
    expect(readBattery(hass.states['switch.office_plug']!)).toBeUndefined();
  });
});

describe('detectCharging', () => {
  const attrs = (a: Record<string, unknown>, id = 'sensor.x', state = '50') =>
    makeState(id, state, now, { attributes: a });

  it('recognises the HA standard binary sensor', () => {
    expect(
      detectCharging([attrs({ device_class: 'battery_charging' }, 'binary_sensor.c', 'on')]),
    ).toBe(true);
    expect(
      detectCharging([attrs({ device_class: 'battery_charging' }, 'binary_sensor.c', 'off')]),
    ).toBe(false);
  });

  it('recognises companion-app battery state sensors and attributes', () => {
    expect(detectCharging([attrs({}, 'sensor.phone_battery_state', 'charging')])).toBe(true);
    expect(detectCharging([attrs({}, 'sensor.phone_battery_state', 'full')])).toBe(true);
    expect(detectCharging([attrs({}, 'sensor.phone_battery_state', 'discharging')])).toBe(false);
    expect(detectCharging([attrs({ battery_state: 'charging' }, 'device_tracker.p', 'home')])).toBe(
      true,
    );
    expect(detectCharging([attrs({ is_charging: true })])).toBe(true);
    expect(detectCharging([attrs({ charging: false })])).toBe(false);
  });

  it('recognises a docked vacuum but not a cleaning one', () => {
    expect(detectCharging([attrs({}, 'vacuum.v', 'docked')])).toBe(true);
    expect(detectCharging([attrs({}, 'vacuum.v', 'cleaning')])).toBe(false);
  });

  it('does not mistake unrelated "full" states', () => {
    expect(detectCharging([attrs({}, 'sensor.bin_level', 'full')])).toBe(false);
  });
});

describe('combineBatteryReadings', () => {
  it('returns undefined for no readings', () => {
    expect(combineBatteryReadings([])).toBeUndefined();
  });

  it('prefers a sensor over an attribute over a binary sensor', () => {
    const combined = combineBatteryReadings([
      { isLow: false, source: 'binary', entityId: 'binary_sensor.a' },
      { level: 50, isLow: false, source: 'attribute', entityId: 'device_tracker.b' },
      { level: 70, isLow: false, source: 'sensor', entityId: 'sensor.c' },
    ]);
    expect(combined?.source).toBe('sensor');
    expect(combined?.level).toBe(70);
  });

  it('picks the lowest level among several sensors (weakest cell wins)', () => {
    const combined = combineBatteryReadings([
      { level: 80, isLow: false, source: 'sensor', entityId: 'sensor.cell_1' },
      { level: 35, isLow: false, source: 'sensor', entityId: 'sensor.cell_2' },
    ]);
    expect(combined?.level).toBe(35);
    expect(combined?.entityId).toBe('sensor.cell_2');
  });

  it('flags low when any binary sensor says low, even with a numeric level', () => {
    const combined = combineBatteryReadings([
      { level: 60, isLow: false, source: 'sensor', entityId: 'sensor.level' },
      { isLow: true, source: 'binary', entityId: 'binary_sensor.low' },
    ]);
    expect(combined).toEqual({
      level: 60,
      isLow: true,
      source: 'sensor',
      entityId: 'sensor.level',
    });
  });
});

describe('detectBattery', () => {
  it('scans a device and reads the phone from its dedicated sensor, not the tracker attribute', () => {
    const states = [
      hass.states['sensor.pixel_9_battery_level']!,
      hass.states['sensor.pixel_9_battery_state']!,
      hass.states['device_tracker.pixel_9']!,
    ];
    const r = detectBattery(states);
    expect(r?.source).toBe('sensor');
    expect(r?.level).toBe(71);
  });

  it('ignores config-category entities when given the registry', () => {
    const states = [hass.states['sensor.inverter_min_soc']!];
    expect(detectBattery(states)).toMatchObject({ level: 10 }); // no registry: looks like a battery
    expect(detectBattery(states, hass.entities)).toBeUndefined(); // registry says it is a setting
  });

  it('marks a docked vacuum as charging', () => {
    const states = [hass.states['vacuum.mr_roboto']!, hass.states['sensor.mr_roboto_battery']!];
    expect(detectBattery(states, hass.entities)).toMatchObject({ level: 18, isCharging: true });
  });

  it('returns undefined for a mains-powered device', () => {
    const states = [
      hass.states['sensor.plant_monitor_soil_moisture']!,
      hass.states['sensor.plant_monitor_wifi_signal']!,
    ];
    expect(detectBattery(states)).toBeUndefined();
  });
});
