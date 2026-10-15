/**
 * Card configuration: the YAML a user writes, with defaults and validation.
 *
 * Home Assistant calls `setConfig(config)` with whatever the user typed. If
 * we throw an Error there, HA shows the message in a red box on the card,
 * which is far friendlier than silently misbehaving. So every check below
 * produces a sentence a person can act on.
 *
 * TypeScript note: `CardConfig` is what the user MAY give us (every field
 * optional). `ResolvedConfig` is what the rest of the card works with
 * (every field present). Converting one to the other once, up front, means
 * no `?? default` sprinkled through the UI.
 */

export const TAB_IDS = ['batteries', 'connectivity', 'shopping'] as const;

/**
 * How the Batteries tab is ordered.
 *  - level: lowest percentage first (the default; needs nothing but hass)
 *  - replace_soon: soonest to run out first, using drain rates from the
 *    recorder's statistics. Devices without enough history fall back to level.
 */
export const BATTERY_SORTS = ['level', 'replace_soon'] as const;
export type BatterySort = (typeof BATTERY_SORTS)[number];
/** "batteries" | "connectivity", derived from the array above so they can't drift apart. */
export type TabId = (typeof TAB_IDS)[number];

/**
 * Which devices can be flagged as "quiet".
 *  - battery: only battery-powered devices (the default). Mains devices
 *    announce failure by going unavailable; a light nobody has toggled for
 *    two days is fine, not quiet.
 *  - all: every device. Expect noise from lights, media players and bridges.
 */
export const QUIET_SCOPES = ['battery', 'all'] as const;
export type QuietScope = (typeof QUIET_SCOPES)[number];

export interface DeviceOverride {
  device_id: string;
  quiet_threshold_hours?: number;
  /** Free text, e.g. "CR2032" or "2x AA". Used for the shopping list (phase 3). */
  battery_type?: string;
}

/** Raw user input. All optional. */
export interface CardConfig {
  type?: string;
  title?: string;
  /** Battery % at or below which a device is a warning. */
  battery_warning?: number;
  /** Battery % at or below which a device is critical. */
  battery_critical?: number;
  /** Hours without an update before a device is "quiet". */
  quiet_threshold_hours?: number;
  /** Per-integration quiet thresholds, keyed by platform, e.g. { zwave_js: 48 }. */
  integration_thresholds?: Record<string, number>;
  device_overrides?: DeviceOverride[];
  exclude_integrations?: string[];
  exclude_devices?: string[];
  /** Entity ids to ignore entirely, e.g. a settings sensor mis-labelled as a battery. */
  exclude_entities?: string[];
  quiet_scope?: QuietScope;
  battery_sort?: BatterySort;
  /** Rows shown per tab before a "show more" control. A number, or "all". */
  max_rows?: number | 'all';
  /** Draw the 14-day trend next to each battery bar when history exists. */
  show_sparklines?: boolean;
  /** Allow-lists. Area names or ids; integration platforms. */
  include_areas?: string[];
  exclude_areas?: string[];
  include_integrations?: string[];
  show_tabs?: TabId[];
  default_tab?: TabId;
}

/** Fully resolved config with defaults applied. */
export interface ResolvedConfig {
  title: string;
  battery_warning: number;
  battery_critical: number;
  quiet_threshold_hours: number;
  integration_thresholds: Record<string, number>;
  device_overrides: DeviceOverride[];
  exclude_integrations: string[];
  exclude_devices: string[];
  exclude_entities: string[];
  quiet_scope: QuietScope;
  battery_sort: BatterySort;
  max_rows: number | 'all';
  show_sparklines: boolean;
  include_areas: string[];
  exclude_areas: string[];
  include_integrations: string[];
  show_tabs: TabId[];
  default_tab: TabId;
}

export const DEFAULT_CONFIG: ResolvedConfig = {
  title: 'Pulse Check',
  battery_warning: 30,
  battery_critical: 15,
  quiet_threshold_hours: 24,
  integration_thresholds: {},
  device_overrides: [],
  exclude_integrations: [],
  exclude_devices: [],
  exclude_entities: [],
  quiet_scope: 'battery',
  battery_sort: 'level',
  max_rows: 12,
  show_sparklines: true,
  include_areas: [],
  exclude_areas: [],
  include_integrations: [],
  show_tabs: ['batteries', 'connectivity'],
  default_tab: 'batteries',
};

/** Thrown for bad config. A separate class lets callers tell it apart from bugs. */
export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

/* ------------------------------------------------------------------------ */
/* Small validators                                                         */
/* ------------------------------------------------------------------------ */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function numberOrDefault(value: unknown, key: string, fallback: number, min: number, max: number) {
  if (value === undefined) return fallback;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new ConfigError(`"${key}" must be a number, got ${JSON.stringify(value)}.`);
  }
  if (value < min || value > max) {
    throw new ConfigError(`"${key}" must be between ${String(min)} and ${String(max)}.`);
  }
  return value;
}

function stringArrayOrDefault(value: unknown, key: string, fallback: string[]): string[] {
  if (value === undefined) return fallback;
  if (!Array.isArray(value) || !value.every((v) => typeof v === 'string')) {
    throw new ConfigError(`"${key}" must be a list of strings.`);
  }
  return value;
}

function isTabId(value: unknown): value is TabId {
  return typeof value === 'string' && (TAB_IDS as readonly string[]).includes(value);
}

/* ------------------------------------------------------------------------ */
/* Main entry                                                               */
/* ------------------------------------------------------------------------ */

/**
 * Validate raw config and fill in defaults.
 * @throws ConfigError with a human-readable message
 */
export function resolveConfig(raw: unknown): ResolvedConfig {
  if (!isRecord(raw)) {
    throw new ConfigError('Card config must be a YAML mapping (key: value pairs).');
  }

  const title = raw.title === undefined ? DEFAULT_CONFIG.title : raw.title;
  if (typeof title !== 'string') throw new ConfigError('"title" must be text.');

  const battery_warning = numberOrDefault(
    raw.battery_warning,
    'battery_warning',
    DEFAULT_CONFIG.battery_warning,
    0,
    100,
  );
  const battery_critical = numberOrDefault(
    raw.battery_critical,
    'battery_critical',
    DEFAULT_CONFIG.battery_critical,
    0,
    100,
  );
  if (battery_critical > battery_warning) {
    throw new ConfigError(
      `"battery_critical" (${String(battery_critical)}) must not be higher than "battery_warning" (${String(battery_warning)}).`,
    );
  }

  const quiet_threshold_hours = numberOrDefault(
    raw.quiet_threshold_hours,
    'quiet_threshold_hours',
    DEFAULT_CONFIG.quiet_threshold_hours,
    0.01,
    24 * 365,
  );

  // integration_thresholds: { platform: hours }
  const integration_thresholds: Record<string, number> = {};
  const rawIntegration = raw.integration_thresholds;
  if (rawIntegration !== undefined) {
    if (!isRecord(rawIntegration)) {
      throw new ConfigError('"integration_thresholds" must be a mapping of integration: hours.');
    }
    for (const [platform, hours] of Object.entries(rawIntegration)) {
      integration_thresholds[platform] = numberOrDefault(
        hours,
        `integration_thresholds.${platform}`,
        quiet_threshold_hours,
        0.01,
        24 * 365,
      );
    }
  }

  // device_overrides: list of { device_id, quiet_threshold_hours?, battery_type? }
  const device_overrides: DeviceOverride[] = [];
  const rawOverrides = raw.device_overrides;
  if (rawOverrides !== undefined) {
    if (!Array.isArray(rawOverrides)) {
      throw new ConfigError('"device_overrides" must be a list.');
    }
    rawOverrides.forEach((item: unknown, i) => {
      const where = `device_overrides[${String(i)}]`;
      if (!isRecord(item) || typeof item.device_id !== 'string' || item.device_id === '') {
        throw new ConfigError(`${where} needs a "device_id".`);
      }
      const override: DeviceOverride = { device_id: item.device_id };
      if (item.quiet_threshold_hours !== undefined) {
        override.quiet_threshold_hours = numberOrDefault(
          item.quiet_threshold_hours,
          `${where}.quiet_threshold_hours`,
          quiet_threshold_hours,
          0.01,
          24 * 365,
        );
      }
      if (item.battery_type !== undefined) {
        if (typeof item.battery_type !== 'string') {
          throw new ConfigError(`${where}.battery_type must be text, e.g. "CR2032".`);
        }
        override.battery_type = item.battery_type;
      }
      device_overrides.push(override);
    });
  }

  const exclude_integrations = stringArrayOrDefault(
    raw.exclude_integrations,
    'exclude_integrations',
    DEFAULT_CONFIG.exclude_integrations,
  );
  const exclude_devices = stringArrayOrDefault(
    raw.exclude_devices,
    'exclude_devices',
    DEFAULT_CONFIG.exclude_devices,
  );

  const exclude_entities = stringArrayOrDefault(
    raw.exclude_entities,
    'exclude_entities',
    DEFAULT_CONFIG.exclude_entities,
  );

  // quiet_scope
  let quiet_scope: QuietScope = DEFAULT_CONFIG.quiet_scope;
  const rawScope = raw.quiet_scope;
  if (rawScope !== undefined) {
    if (typeof rawScope !== 'string' || !(QUIET_SCOPES as readonly string[]).includes(rawScope)) {
      throw new ConfigError(`"quiet_scope" must be one of: ${QUIET_SCOPES.join(', ')}.`);
    }
    quiet_scope = rawScope as QuietScope;
  }

  // battery_sort
  let battery_sort: BatterySort = DEFAULT_CONFIG.battery_sort;
  const rawSort = raw.battery_sort;
  if (rawSort !== undefined) {
    if (typeof rawSort !== 'string' || !(BATTERY_SORTS as readonly string[]).includes(rawSort)) {
      throw new ConfigError(`"battery_sort" must be one of: ${BATTERY_SORTS.join(', ')}.`);
    }
    battery_sort = rawSort as BatterySort;
  }

  // max_rows: a positive whole number, or "all"
  let max_rows: number | 'all' = DEFAULT_CONFIG.max_rows;
  const rawMax = raw.max_rows;
  if (rawMax !== undefined) {
    if (rawMax === 'all') {
      max_rows = 'all';
    } else if (typeof rawMax === 'number' && Number.isInteger(rawMax) && rawMax >= 1) {
      max_rows = rawMax;
    } else {
      throw new ConfigError('"max_rows" must be a whole number of at least 1, or "all".');
    }
  }

  // show_sparklines
  let show_sparklines = DEFAULT_CONFIG.show_sparklines;
  if (raw.show_sparklines !== undefined) {
    if (typeof raw.show_sparklines !== 'boolean') {
      throw new ConfigError('"show_sparklines" must be true or false.');
    }
    show_sparklines = raw.show_sparklines;
  }

  const include_areas = stringArrayOrDefault(
    raw.include_areas,
    'include_areas',
    DEFAULT_CONFIG.include_areas,
  );
  const exclude_areas = stringArrayOrDefault(
    raw.exclude_areas,
    'exclude_areas',
    DEFAULT_CONFIG.exclude_areas,
  );
  const include_integrations = stringArrayOrDefault(
    raw.include_integrations,
    'include_integrations',
    DEFAULT_CONFIG.include_integrations,
  );

  // show_tabs
  let show_tabs: TabId[] = DEFAULT_CONFIG.show_tabs;
  const rawTabs = raw.show_tabs;
  if (rawTabs !== undefined) {
    if (!Array.isArray(rawTabs) || rawTabs.length === 0 || !rawTabs.every(isTabId)) {
      throw new ConfigError(
        `"show_tabs" must be a non-empty list containing only: ${TAB_IDS.join(', ')}.`,
      );
    }
    show_tabs = [...new Set(rawTabs)];
  }

  // default_tab
  let default_tab: TabId = show_tabs.includes(DEFAULT_CONFIG.default_tab)
    ? DEFAULT_CONFIG.default_tab
    : (show_tabs[0] ?? DEFAULT_CONFIG.default_tab);
  const rawDefault = raw.default_tab;
  if (rawDefault !== undefined) {
    if (!isTabId(rawDefault)) {
      throw new ConfigError(`"default_tab" must be one of: ${TAB_IDS.join(', ')}.`);
    }
    if (!show_tabs.includes(rawDefault)) {
      throw new ConfigError(`"default_tab" (${rawDefault}) is not in "show_tabs".`);
    }
    default_tab = rawDefault;
  }

  return {
    title,
    battery_warning,
    battery_critical,
    quiet_threshold_hours,
    integration_thresholds,
    device_overrides,
    exclude_integrations,
    exclude_devices,
    exclude_entities,
    quiet_scope,
    battery_sort,
    max_rows,
    show_sparklines,
    include_areas,
    exclude_areas,
    include_integrations,
    show_tabs,
    default_tab,
  };
}
