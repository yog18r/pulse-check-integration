/**
 * Snoozes: "I know about this one, stop telling me until <date>".
 *
 * Stored in the browser's localStorage, so they are per browser rather than
 * per Home Assistant user, and they need no YAML edit. That trade-off is
 * deliberate: a snooze is a personal, temporary "I'll deal with it", not
 * configuration. Expired snoozes are pruned on load.
 *
 * The pure helpers take and return Maps so the React hook and the tests
 * never touch storage directly.
 */

export const SNOOZE_STORAGE_KEY = 'pulse-check-card:snoozes';

/** Options offered in the UI, in days. */
export const SNOOZE_CHOICES_DAYS = [1, 7, 30] as const;

export type SnoozeMap = ReadonlyMap<string, Date>;

/** Drop entries whose time has passed. */
export function pruneSnoozes(snoozes: SnoozeMap, now: Date): Map<string, Date> {
  const live = new Map<string, Date>();
  for (const [id, until] of snoozes) {
    if (until > now) live.set(id, until);
  }
  return live;
}

export function withSnooze(snoozes: SnoozeMap, deviceId: string, until: Date): Map<string, Date> {
  const next = new Map(snoozes);
  next.set(deviceId, until);
  return next;
}

export function withoutSnooze(snoozes: SnoozeMap, deviceId: string): Map<string, Date> {
  const next = new Map(snoozes);
  next.delete(deviceId);
  return next;
}

export function snoozeUntil(now: Date, days: number): Date {
  return new Date(now.getTime() + days * 24 * 60 * 60 * 1000);
}

/* ---- storage ----------------------------------------------------------- */

/** A minimal localStorage-like interface, so tests can pass a fake. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function defaultStorage(): StorageLike | undefined {
  try {
    return typeof localStorage === 'undefined' ? undefined : localStorage;
  } catch {
    return undefined; // some embedded browsers throw on access
  }
}

export function loadSnoozes(now: Date, storage = defaultStorage()): Map<string, Date> {
  if (!storage) return new Map();
  try {
    const raw = storage.getItem(SNOOZE_STORAGE_KEY);
    if (!raw) return new Map();
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return new Map();
    const result = new Map<string, Date>();
    for (const [id, iso] of Object.entries(parsed)) {
      if (typeof iso !== 'string') continue;
      const d = new Date(iso);
      if (!Number.isNaN(d.getTime())) result.set(id, d);
    }
    return pruneSnoozes(result, now);
  } catch {
    return new Map();
  }
}

export function saveSnoozes(snoozes: SnoozeMap, storage = defaultStorage()): void {
  if (!storage) return;
  try {
    const plain: Record<string, string> = {};
    for (const [id, until] of snoozes) plain[id] = until.toISOString();
    storage.setItem(SNOOZE_STORAGE_KEY, JSON.stringify(plain));
  } catch {
    // Storage full or blocked: the snooze still works for this page load.
  }
}
