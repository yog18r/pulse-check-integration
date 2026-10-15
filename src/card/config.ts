/**
 * Card configuration: the YAML a user writes, with defaults and validation.
 *
 * Everything here is presentation. What counts as a low battery, how long
 * a device may stay quiet, which devices to ignore and what batteries they
 * take all live in the Pulse Check integration (Settings → Devices &
 * services → Pulse Check → Configure, and the card editor's per-device
 * panel, which saves through the integration's services).
 *
 * Home Assistant calls `setConfig(config)` with whatever the user typed. If
 * we throw an Error there, HA shows the message in a red box on the card,
 * which is far friendlier than silently misbehaving. So every check below
 * produces a sentence a person can act on.
 *
 * TypeScript note: `CardConfig` is what the user MAY give us (every field
 * optional). `ResolvedConfig` is what the rest of the card works with
 * (every field present).
 */
import { GROUP_BYS, type GroupBy } from '../core/grouping';

export const TAB_IDS = ['batteries', 'connectivity', 'actions'] as const;
export type TabId = (typeof TAB_IDS)[number];

/**
 * How the Batteries tab is ordered, within each severity band.
 *  - level: lowest percentage first (the default)
 *  - name: alphabetical by display name
 *  - replace_soon: soonest to run out first. Devices without an estimate
 *    get a stand-in of level × 3.65 days (about a year from 100 %), so a
 *    1 % battery with no history still sorts near the top.
 */
export const SORT_ORDERS = ['level', 'name', 'replace_soon'] as const;
export type SortOrder = (typeof SORT_ORDERS)[number];

/** Raw user input. All optional. */
export interface CardConfig {
  type?: string;
  title?: string;
  show_tabs?: TabId[];
  default_tab?: TabId;
  /** Rows shown per tab before a "show more" control. A number, or "all". */
  max_rows?: number | 'all';
  sort?: SortOrder;
  /** Older name for `sort`, still accepted. */
  battery_sort?: SortOrder;
  /** View filters: what this card shows. Names or ids; empty means all. */
  areas?: string[];
  integrations?: string[];
  device_types?: string[];
  /** Split the lists into sections: none, area, integration or device_type. */
  group_by?: GroupBy;
  /** Start the Batteries tab showing only devices that need attention. */
  problems_only?: boolean;
  /** Draw a trend line next to each battery bar when history exists. */
  show_sparklines?: boolean;
  /** How many days of history the sparkline covers (1-365). Default 14. */
  sparkline_days?: number;
}

/** Fully resolved config with defaults applied. */
export interface ResolvedConfig {
  title: string;
  show_tabs: TabId[];
  default_tab: TabId;
  max_rows: number | 'all';
  sort: SortOrder;
  group_by: GroupBy;
  areas: string[];
  integrations: string[];
  device_types: string[];
  problems_only: boolean;
  show_sparklines: boolean;
  sparkline_days: number;
}

export const DEFAULT_CONFIG: ResolvedConfig = {
  title: '',
  show_tabs: ['batteries', 'connectivity'],
  default_tab: 'batteries',
  max_rows: 12,
  sort: 'level',
  group_by: 'none',
  areas: [],
  integrations: [],
  device_types: [],
  problems_only: false,
  show_sparklines: true,
  sparkline_days: 14,
};

export const MAX_SPARKLINE_DAYS = 365;

/** Thrown for bad config. A separate class lets callers tell it apart from bugs. */
export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isTabId(value: unknown): value is TabId {
  return typeof value === 'string' && (TAB_IDS as readonly string[]).includes(value);
}

function oneOf<T extends string>(
  value: unknown,
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  if (value === undefined) return fallback;
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    throw new ConfigError(`"${key}" must be one of: ${allowed.join(', ')}.`);
  }
  return value as T;
}

function stringList(value: unknown, key: string): string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || !value.every((v) => typeof v === 'string')) {
    throw new ConfigError(`"${key}" must be a list of names or ids.`);
  }
  return value;
}

function booleanOr(value: unknown, key: string, fallback: boolean): boolean {
  if (value === undefined) return fallback;
  if (typeof value !== 'boolean') throw new ConfigError(`"${key}" must be true or false.`);
  return value;
}

/**
 * Validate raw config and fill in defaults.
 * @throws ConfigError with a human-readable message
 */
export function resolveConfig(raw: unknown): ResolvedConfig {
  if (!isRecord(raw)) {
    throw new ConfigError('Card config must be a YAML mapping (key: value pairs).');
  }

  // Blank or absent means "no title row" rather than a default name.
  const title = raw.title === undefined ? DEFAULT_CONFIG.title : raw.title;
  if (typeof title !== 'string') throw new ConfigError('"title" must be text.');

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

  // `sort` wins; `battery_sort` is the older spelling.
  const sort = oneOf(raw.sort ?? raw.battery_sort, 'sort', SORT_ORDERS, 'level');
  const group_by = oneOf(raw.group_by, 'group_by', GROUP_BYS, 'none');
  const areas = stringList(raw.areas, 'areas');
  const integrations = stringList(raw.integrations, 'integrations');
  const device_types = stringList(raw.device_types, 'device_types');
  const problems_only = booleanOr(raw.problems_only, 'problems_only', false);
  const show_sparklines = booleanOr(raw.show_sparklines, 'show_sparklines', true);

  let sparkline_days = DEFAULT_CONFIG.sparkline_days;
  const rawDays = raw.sparkline_days;
  if (rawDays !== undefined) {
    if (
      typeof rawDays !== 'number' ||
      !Number.isInteger(rawDays) ||
      rawDays < 1 ||
      rawDays > MAX_SPARKLINE_DAYS
    ) {
      throw new ConfigError(
        `"sparkline_days" must be a whole number of days from 1 to ${String(MAX_SPARKLINE_DAYS)}.`,
      );
    }
    sparkline_days = rawDays;
  }

  return {
    title,
    show_tabs,
    default_tab,
    max_rows,
    sort,
    group_by,
    areas,
    integrations,
    device_types,
    problems_only,
    show_sparklines,
    sparkline_days,
  };
}
