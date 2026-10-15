/**
 * Realistic mock `hass` data covering every integration the card supports.
 *
 * Used by the unit tests AND by the local demo page, so the card can be
 * developed and shown without a live Home Assistant instance.
 *
 * Every timestamp is relative to a `now` you pass in, so tests are
 * deterministic and the demo always looks fresh.
 */
import type {
  HassAreaRegistryEntry,
  HassDeviceRegistryEntry,
  HassEntityRegistryEntry,
  HassEntityState,
  HassLike,
} from '../../src/core/types';

/* ------------------------------------------------------------------------ */
/* Small builders                                                            */
/* ------------------------------------------------------------------------ */

export function hoursAgo(now: Date, hours: number): string {
  return new Date(now.getTime() - hours * 60 * 60 * 1000).toISOString();
}

export function minutesAgo(now: Date, minutes: number): string {
  return new Date(now.getTime() - minutes * 60 * 1000).toISOString();
}

interface StateOptions {
  attributes?: Record<string, unknown>;
  /** ISO timestamp. Defaults to `now`. */
  lastUpdated?: string;
}

export function makeState(
  entityId: string,
  state: string,
  now: Date,
  options: StateOptions = {},
): HassEntityState {
  const ts = options.lastUpdated ?? now.toISOString();
  return {
    entity_id: entityId,
    state,
    attributes: { friendly_name: entityId, ...options.attributes },
    last_changed: ts,
    last_updated: ts,
  };
}

export function makeEntity(
  entityId: string,
  platform: string,
  deviceId: string | undefined,
  extra: Partial<HassEntityRegistryEntry> = {},
): HassEntityRegistryEntry {
  const entry: HassEntityRegistryEntry = { entity_id: entityId, platform, ...extra };
  if (deviceId !== undefined) entry.device_id = deviceId;
  return entry;
}

export function makeDevice(
  id: string,
  name: string,
  extra: Partial<HassDeviceRegistryEntry> = {},
): HassDeviceRegistryEntry {
  return {
    id,
    name,
    name_by_user: null,
    manufacturer: null,
    model: null,
    area_id: null,
    entry_type: null,
    disabled_by: null,
    ...extra,
  };
}

/** Collects entries into the Record<string, T> maps the real `hass` uses. */
function byKey<T>(items: T[], key: (item: T) => string): Record<string, T> {
  return Object.fromEntries(items.map((item) => [key(item), item]));
}

/* ------------------------------------------------------------------------ */
/* The fixture                                                              */
/* ------------------------------------------------------------------------ */

export const AREAS: HassAreaRegistryEntry[] = [
  { area_id: 'living_room', name: 'Living Room' },
  { area_id: 'kitchen', name: 'Kitchen' },
  { area_id: 'bedroom', name: 'Bedroom' },
  { area_id: 'garage', name: 'Garage' },
  { area_id: 'office', name: 'Office' },
  { area_id: 'hallway', name: 'Hallway' },
];

/** Device ids, exported so tests can refer to them by name. */
export const DEV = {
  z2mDoor: 'dev_z2m_door',
  z2mMotion: 'dev_z2m_motion',
  zhaTemp: 'dev_zha_temp',
  zwaveMulti: 'dev_zwave_multi',
  zwaveLock: 'dev_zwave_lock',
  esphomePlant: 'dev_esphome_plant',
  shellyHt: 'dev_shelly_ht',
  shellyPlug: 'dev_shelly_plug',
  matterContact: 'dev_matter_contact',
  phone: 'dev_phone',
  smokeAlarm: 'dev_smoke_alarm',
  legacyTracker: 'dev_legacy_tracker',
  sun: 'dev_sun',
  disabledSensor: 'dev_disabled',
  mqttLight: 'dev_mqtt_light',
  vacuum: 'dev_vacuum',
} as const;

/**
 * Build the full fixture. Each block below is one physical device and
 * documents which detection rule or edge case it exercises.
 */
export function buildHass(now: Date): HassLike {
  const states: HassEntityState[] = [];
  const entities: HassEntityRegistryEntry[] = [];
  const devices: HassDeviceRegistryEntry[] = [];

  // --- Zigbee2MQTT door sensor (mqtt): healthy, 87%, has linkquality + last_seen
  devices.push(
    makeDevice(DEV.z2mDoor, 'Front Door Sensor', {
      manufacturer: 'Aqara',
      model: 'MCCGQ11LM',
      area_id: 'hallway',
    }),
  );
  entities.push(
    makeEntity('binary_sensor.front_door_contact', 'mqtt', DEV.z2mDoor),
    makeEntity('sensor.front_door_battery', 'mqtt', DEV.z2mDoor, { entity_category: 'diagnostic' }),
    makeEntity('sensor.front_door_linkquality', 'mqtt', DEV.z2mDoor, {
      entity_category: 'diagnostic',
    }),
    makeEntity('sensor.front_door_last_seen', 'mqtt', DEV.z2mDoor, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('binary_sensor.front_door_contact', 'off', now, {
      attributes: { device_class: 'door' },
      lastUpdated: minutesAgo(now, 12),
    }),
    makeState('sensor.front_door_battery', '87', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 3),
    }),
    makeState('sensor.front_door_linkquality', '120', now, {
      attributes: { unit_of_measurement: 'lqi' },
      lastUpdated: minutesAgo(now, 12),
    }),
    makeState('sensor.front_door_last_seen', minutesAgo(now, 12), now, {
      attributes: { device_class: 'timestamp' },
      lastUpdated: minutesAgo(now, 12),
    }),
  );

  // --- Zigbee2MQTT motion sensor (mqtt): CRITICAL battery 12%, weak link
  devices.push(
    makeDevice(DEV.z2mMotion, 'Living Room Motion', {
      manufacturer: 'Philips',
      model: 'SML001',
      area_id: 'living_room',
    }),
  );
  entities.push(
    makeEntity('binary_sensor.living_room_motion_occupancy', 'mqtt', DEV.z2mMotion),
    makeEntity('sensor.living_room_motion_battery', 'mqtt', DEV.z2mMotion, {
      entity_category: 'diagnostic',
    }),
    makeEntity('sensor.living_room_motion_linkquality', 'mqtt', DEV.z2mMotion, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('binary_sensor.living_room_motion_occupancy', 'off', now, {
      attributes: { device_class: 'occupancy' },
      lastUpdated: minutesAgo(now, 40),
    }),
    makeState('sensor.living_room_motion_battery', '12', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 1),
    }),
    makeState('sensor.living_room_motion_linkquality', '45', now, {
      attributes: { unit_of_measurement: 'lqi' },
      lastUpdated: minutesAgo(now, 40),
    }),
  );

  // --- ZHA temperature sensor: WARNING battery 28%, QUIET for 30h, has lqi/rssi
  devices.push(
    makeDevice(DEV.zhaTemp, 'Bedroom Climate', {
      manufacturer: 'SONOFF',
      model: 'SNZB-02',
      area_id: 'bedroom',
      name_by_user: 'Bedroom Temp & Humidity',
    }),
  );
  entities.push(
    makeEntity('sensor.bedroom_climate_temperature', 'zha', DEV.zhaTemp),
    makeEntity('sensor.bedroom_climate_humidity', 'zha', DEV.zhaTemp),
    makeEntity('sensor.bedroom_climate_battery', 'zha', DEV.zhaTemp, {
      entity_category: 'diagnostic',
    }),
    makeEntity('sensor.bedroom_climate_lqi', 'zha', DEV.zhaTemp, { entity_category: 'diagnostic' }),
    makeEntity('sensor.bedroom_climate_rssi', 'zha', DEV.zhaTemp, {
      entity_category: 'diagnostic',
    }),
    // A config button pressed recently must NOT count as "heard from".
    makeEntity('button.bedroom_climate_identify', 'zha', DEV.zhaTemp, {
      entity_category: 'config',
    }),
  );
  states.push(
    makeState('sensor.bedroom_climate_temperature', '19.4', now, {
      attributes: { device_class: 'temperature', unit_of_measurement: '°C' },
      lastUpdated: hoursAgo(now, 30),
    }),
    makeState('sensor.bedroom_climate_humidity', '58', now, {
      attributes: { device_class: 'humidity', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 31),
    }),
    makeState('sensor.bedroom_climate_battery', '28', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 32),
    }),
    makeState('sensor.bedroom_climate_lqi', '88', now, { lastUpdated: hoursAgo(now, 30) }),
    makeState('sensor.bedroom_climate_rssi', '-71', now, {
      attributes: { unit_of_measurement: 'dBm' },
      lastUpdated: hoursAgo(now, 30),
    }),
    makeState('button.bedroom_climate_identify', hoursAgo(now, 1), now, {
      lastUpdated: hoursAgo(now, 1),
    }),
  );

  // --- Z-Wave JS multisensor: battery 55%, node ASLEEP, last heard 40h ago.
  //     Quiet under the 24h default, but NOT quiet with a zwave_js override of 48h.
  devices.push(
    makeDevice(DEV.zwaveMulti, 'Garage Multisensor', {
      manufacturer: 'Aeotec',
      model: 'ZWA039',
      area_id: 'garage',
    }),
  );
  entities.push(
    makeEntity('binary_sensor.garage_multisensor_motion', 'zwave_js', DEV.zwaveMulti),
    makeEntity('sensor.garage_multisensor_temperature', 'zwave_js', DEV.zwaveMulti),
    makeEntity('sensor.garage_multisensor_battery_level', 'zwave_js', DEV.zwaveMulti, {
      entity_category: 'diagnostic',
    }),
    makeEntity('sensor.garage_multisensor_node_status', 'zwave_js', DEV.zwaveMulti, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('binary_sensor.garage_multisensor_motion', 'off', now, {
      attributes: { device_class: 'motion' },
      lastUpdated: hoursAgo(now, 40),
    }),
    makeState('sensor.garage_multisensor_temperature', '14.0', now, {
      attributes: { device_class: 'temperature', unit_of_measurement: '°C' },
      lastUpdated: hoursAgo(now, 40),
    }),
    makeState('sensor.garage_multisensor_battery_level', '55', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 40),
    }),
    makeState('sensor.garage_multisensor_node_status', 'asleep', now, {
      lastUpdated: hoursAgo(now, 40),
    }),
  );

  // --- Z-Wave JS lock: OFFLINE. All primary entities unavailable, node DEAD.
  devices.push(
    makeDevice(DEV.zwaveLock, 'Front Door Lock', {
      manufacturer: 'Yale',
      model: 'YRD256',
      area_id: 'hallway',
    }),
  );
  entities.push(
    makeEntity('lock.front_door_lock', 'zwave_js', DEV.zwaveLock),
    makeEntity('sensor.front_door_lock_battery_level', 'zwave_js', DEV.zwaveLock, {
      entity_category: 'diagnostic',
    }),
    makeEntity('sensor.front_door_lock_node_status', 'zwave_js', DEV.zwaveLock, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('lock.front_door_lock', 'unavailable', now, { lastUpdated: hoursAgo(now, 6) }),
    makeState('sensor.front_door_lock_battery_level', 'unavailable', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 6),
    }),
    makeState('sensor.front_door_lock_node_status', 'dead', now, {
      lastUpdated: hoursAgo(now, 6),
    }),
  );

  // --- ESPHome plant monitor: mains powered, healthy. Should appear nowhere.
  devices.push(
    makeDevice(DEV.esphomePlant, 'Plant Monitor', {
      manufacturer: 'espressif',
      model: 'esp32dev',
      area_id: 'office',
    }),
  );
  entities.push(
    makeEntity('sensor.plant_monitor_soil_moisture', 'esphome', DEV.esphomePlant),
    makeEntity('sensor.plant_monitor_wifi_signal', 'esphome', DEV.esphomePlant, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('sensor.plant_monitor_soil_moisture', '41', now, {
      attributes: { unit_of_measurement: '%' },
      lastUpdated: minutesAgo(now, 2),
    }),
    makeState('sensor.plant_monitor_wifi_signal', '-58', now, {
      attributes: { device_class: 'signal_strength', unit_of_measurement: 'dBm' },
      lastUpdated: minutesAgo(now, 2),
    }),
  );

  // --- Shelly H&T: battery 92%, healthy
  devices.push(
    makeDevice(DEV.shellyHt, 'Kitchen H&T', {
      manufacturer: 'Shelly',
      model: 'SHHT-1',
      area_id: 'kitchen',
    }),
  );
  entities.push(
    makeEntity('sensor.kitchen_ht_temperature', 'shelly', DEV.shellyHt),
    makeEntity('sensor.kitchen_ht_battery', 'shelly', DEV.shellyHt, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('sensor.kitchen_ht_temperature', '21.7', now, {
      attributes: { device_class: 'temperature', unit_of_measurement: '°C' },
      lastUpdated: hoursAgo(now, 2),
    }),
    makeState('sensor.kitchen_ht_battery', '92', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 2),
    }),
  );

  // --- Shelly plug (Wi-Fi, mains): online but QUIET for 3 days
  devices.push(
    makeDevice(DEV.shellyPlug, 'Office Plug', {
      manufacturer: 'Shelly',
      model: 'SHPLG-S',
      area_id: 'office',
    }),
  );
  entities.push(
    makeEntity('switch.office_plug', 'shelly', DEV.shellyPlug),
    makeEntity('sensor.office_plug_power', 'shelly', DEV.shellyPlug),
  );
  states.push(
    makeState('switch.office_plug', 'on', now, { lastUpdated: hoursAgo(now, 72) }),
    makeState('sensor.office_plug_power', '4.2', now, {
      attributes: { device_class: 'power', unit_of_measurement: 'W' },
      lastUpdated: hoursAgo(now, 72),
    }),
  );

  // --- Matter contact sensor: battery 40%, healthy
  devices.push(
    makeDevice(DEV.matterContact, 'Window Sensor', {
      manufacturer: 'Eve',
      model: 'Eve Door & Window',
      area_id: 'bedroom',
    }),
  );
  entities.push(
    makeEntity('binary_sensor.window_sensor_opening', 'matter', DEV.matterContact),
    makeEntity('sensor.window_sensor_battery', 'matter', DEV.matterContact, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('binary_sensor.window_sensor_opening', 'off', now, {
      attributes: { device_class: 'opening' },
      lastUpdated: hoursAgo(now, 5),
    }),
    makeState('sensor.window_sensor_battery', '40', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 5),
    }),
  );

  // --- Companion app phone (mobile_app): battery 71%. Commonly excluded via config.
  devices.push(makeDevice(DEV.phone, 'Pixel 9', { manufacturer: 'Google', model: 'Pixel 9' }));
  entities.push(
    makeEntity('sensor.pixel_9_battery_level', 'mobile_app', DEV.phone),
    makeEntity('sensor.pixel_9_battery_state', 'mobile_app', DEV.phone),
    makeEntity('device_tracker.pixel_9', 'mobile_app', DEV.phone),
  );
  states.push(
    makeState('sensor.pixel_9_battery_level', '71', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: minutesAgo(now, 8),
    }),
    makeState('sensor.pixel_9_battery_state', 'discharging', now, {
      lastUpdated: minutesAgo(now, 8),
    }),
    makeState('device_tracker.pixel_9', 'home', now, {
      attributes: { source_type: 'gps', battery_level: 71 },
      lastUpdated: minutesAgo(now, 8),
    }),
  );

  // --- Smoke alarm with ONLY a binary low-battery sensor (rule 2): isLow, no level
  devices.push(
    makeDevice(DEV.smokeAlarm, 'Hallway Smoke Alarm', {
      manufacturer: 'Heiman',
      model: 'HS1SA',
      area_id: 'hallway',
    }),
  );
  entities.push(
    makeEntity('binary_sensor.hallway_smoke_alarm_smoke', 'zha', DEV.smokeAlarm),
    makeEntity('binary_sensor.hallway_smoke_alarm_battery_low', 'zha', DEV.smokeAlarm, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('binary_sensor.hallway_smoke_alarm_smoke', 'off', now, {
      attributes: { device_class: 'smoke' },
      lastUpdated: hoursAgo(now, 10),
    }),
    makeState('binary_sensor.hallway_smoke_alarm_battery_low', 'on', now, {
      attributes: { device_class: 'battery' },
      lastUpdated: hoursAgo(now, 10),
    }),
  );

  // --- Legacy tracker with a battery_level ATTRIBUTE only (rule 3 fallback): 44%
  devices.push(makeDevice(DEV.legacyTracker, 'Dog Collar Tracker', { manufacturer: 'Tractive' }));
  entities.push(makeEntity('device_tracker.dog_collar', 'tractive', DEV.legacyTracker));
  states.push(
    makeState('device_tracker.dog_collar', 'home', now, {
      attributes: { source_type: 'gps', battery_level: 44 },
      lastUpdated: hoursAgo(now, 1),
    }),
  );

  // --- Sun: a "service" device with no hardware. Must be skipped entirely.
  devices.push(makeDevice(DEV.sun, 'Sun', { entry_type: 'service' }));
  entities.push(makeEntity('sun.sun', 'sun', DEV.sun));
  states.push(
    makeState('sun.sun', 'above_horizon', now, {
      attributes: { elevation: 42.1 },
      lastUpdated: minutesAgo(now, 1),
    }),
  );

  // --- Disabled device: has a critical battery but is disabled, so skip it.
  devices.push(
    makeDevice(DEV.disabledSensor, 'Old Sensor', {
      disabled_by: 'user',
      area_id: 'garage',
    }),
  );
  entities.push(
    makeEntity('sensor.old_sensor_battery', 'zha', DEV.disabledSensor, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('sensor.old_sensor_battery', '3', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: hoursAgo(now, 200),
    }),
  );

  // --- Orphan entity with no device: a template battery sensor. Still worth showing.
  entities.push(makeEntity('sensor.remote_battery_template', 'template', undefined));
  states.push(
    makeState('sensor.remote_battery_template', '9', now, {
      attributes: {
        device_class: 'battery',
        unit_of_measurement: '%',
        friendly_name: 'TV Remote Battery',
      },
      lastUpdated: hoursAgo(now, 4),
    }),
  );

  // --- Robot vacuum: 18% but DOCKED and charging. Must not be flagged.
  devices.push(
    makeDevice(DEV.vacuum, 'Mr Roboto', {
      manufacturer: 'Ecovacs',
      model: 'DEEBOT',
      area_id: 'living_room',
    }),
  );
  entities.push(
    makeEntity('vacuum.mr_roboto', 'ecovacs', DEV.vacuum),
    makeEntity('sensor.mr_roboto_battery', 'ecovacs', DEV.vacuum, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('vacuum.mr_roboto', 'docked', now, {
      attributes: { battery_level: 18 },
      lastUpdated: minutesAgo(now, 3),
    }),
    makeState('sensor.mr_roboto_battery', '18', now, {
      attributes: { device_class: 'battery', unit_of_measurement: '%' },
      lastUpdated: minutesAgo(now, 3),
    }),
  );

  // --- MQTT light (mains): online, nobody has touched it for 50h.
  //     NOT quiet under the default quiet_scope: battery; quiet under "all".
  devices.push(
    makeDevice(DEV.mqttLight, 'Garage Lights', {
      manufacturer: 'IKEA',
      model: 'LED1836G9',
      area_id: 'garage',
    }),
  );
  entities.push(
    makeEntity('light.garage_lights', 'mqtt', DEV.mqttLight),
    makeEntity('sensor.garage_lights_linkquality', 'mqtt', DEV.mqttLight, {
      entity_category: 'diagnostic',
    }),
  );
  states.push(
    makeState('light.garage_lights', 'off', now, { lastUpdated: hoursAgo(now, 50) }),
    makeState('sensor.garage_lights_linkquality', '150', now, {
      attributes: { unit_of_measurement: 'lqi' },
      lastUpdated: hoursAgo(now, 50),
    }),
  );

  // --- Orphan CONFIG sensor labelled as a battery (an inverter's "minimum
  //     state of charge" setting). It is a setting, not a battery: skip it.
  entities.push(
    makeEntity('sensor.inverter_min_soc', 'foxess', undefined, { entity_category: 'config' }),
  );
  states.push(
    makeState('sensor.inverter_min_soc', '10', now, {
      attributes: {
        device_class: 'battery',
        unit_of_measurement: '%',
        friendly_name: 'Inverter Min SoC',
      },
      lastUpdated: hoursAgo(now, 30),
    }),
  );

  // --- Orphan entity with no device and no battery: pure noise, must be skipped.
  entities.push(makeEntity('sensor.random_template', 'template', undefined));
  states.push(makeState('sensor.random_template', '42', now, { lastUpdated: hoursAgo(now, 500) }));

  return {
    states: byKey(states, (s) => s.entity_id),
    entities: byKey(entities, (e) => e.entity_id),
    devices: byKey(devices, (d) => d.id),
    areas: byKey(AREAS, (a) => a.area_id),
  };
}

/** A fixed "now" so tests produce identical output every run. */
export const FIXED_NOW = new Date('2026-10-15T10:00:00.000Z');

/** Convenience: the fixture at the fixed time. */
export const hass = buildHass(FIXED_NOW);
