import { describe, expect, it } from 'vitest';
import {
  loadSnoozes,
  pruneSnoozes,
  saveSnoozes,
  SNOOZE_STORAGE_KEY,
  snoozeUntil,
  withoutSnooze,
  withSnooze,
  type StorageLike,
} from '../../src/card/snoozeStore';
import { FIXED_NOW } from '../fixtures/hass';

class FakeStorage implements StorageLike {
  data = new Map<string, string>();
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.data.set(key, value);
  }
}

const now = FIXED_NOW;
const future = new Date('2027-01-01T00:00:00Z');
const past = new Date('2020-01-01T00:00:00Z');

describe('pure helpers', () => {
  it('adds, removes and prunes without mutating the input', () => {
    const empty = new Map<string, Date>();
    const one = withSnooze(empty, 'a', future);
    expect(empty.size).toBe(0);
    expect(one.get('a')).toEqual(future);
    const none = withoutSnooze(one, 'a');
    expect(one.size).toBe(1);
    expect(none.size).toBe(0);
    const mixed = withSnooze(withSnooze(empty, 'old', past), 'new', future);
    expect([...pruneSnoozes(mixed, now).keys()]).toEqual(['new']);
  });

  it('computes the end of a snooze in days', () => {
    expect(snoozeUntil(now, 7).getTime() - now.getTime()).toBe(7 * 24 * 60 * 60 * 1000);
  });
});

describe('storage round trip', () => {
  it('saves ISO strings and loads them back, dropping expired ones', () => {
    const storage = new FakeStorage();
    saveSnoozes(
      new Map([
        ['a', future],
        ['b', past],
      ]),
      storage,
    );
    expect(JSON.parse(storage.getItem(SNOOZE_STORAGE_KEY)!)).toEqual({
      a: future.toISOString(),
      b: past.toISOString(),
    });
    const loaded = loadSnoozes(now, storage);
    expect([...loaded.entries()]).toEqual([['a', future]]);
  });

  it('survives garbage and missing storage', () => {
    const storage = new FakeStorage();
    storage.setItem(SNOOZE_STORAGE_KEY, '{not json');
    expect(loadSnoozes(now, storage).size).toBe(0);
    storage.setItem(SNOOZE_STORAGE_KEY, JSON.stringify({ a: 'not a date', b: 42 }));
    expect(loadSnoozes(now, storage).size).toBe(0);
    expect(loadSnoozes(now, undefined).size).toBe(0);
    expect(() => {
      saveSnoozes(new Map(), undefined);
    }).not.toThrow();
  });
});
