/**
 * Every language has every string. TypeScript already refuses a catalog
 * with a missing key; these tests add what types cannot see: the plural
 * forms each language needs, the placeholders, and nothing left empty.
 */
import { describe, expect, it } from 'vitest';
import { formatRelative } from '../../src/core/time';
import { en } from '../../src/i18n/en';
import {
  CATALOGS,
  EN,
  languageOf,
  pickLanguage,
  translator,
  type PluralForms,
} from '../../src/i18n';
import { translateBasis, translateUnusual } from '../../src/i18n/serverText';
import { FIXED_NOW, minutesAgo } from '../fixtures/hass';

const LANGUAGES = ['en', 'de', 'fr', 'es', 'nl', 'it', 'pt-BR', 'pl', 'zh-Hans', 'cs'];

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1] ?? '').sort();
}

/** The plural categories a language uses for whole numbers. */
function categoriesFor(language: string): Set<string> {
  const rules = new Intl.PluralRules(language);
  const used = new Set<string>(['other']);
  for (let n = 0; n < 200; n += 1) used.add(rules.select(n));
  return used;
}

describe('catalogs', () => {
  it('ships the ten languages', () => {
    expect(Object.keys(CATALOGS).sort()).toEqual([...LANGUAGES].sort());
  });

  for (const language of LANGUAGES) {
    it(`${language} has every key, every plural form and the same placeholders`, () => {
      const catalog = CATALOGS[language]!;
      expect(Object.keys(catalog).sort()).toEqual(Object.keys(en).sort());
      for (const [key, english] of Object.entries(en)) {
        const translated: string | PluralForms = catalog[key as keyof typeof en];
        if (typeof english === 'string') {
          expect(typeof translated, key).toBe('string');
          const text = translated as string;
          expect(text.trim(), key).not.toBe('');
          expect(placeholders(text), key).toEqual(placeholders(english));
          continue;
        }
        expect(typeof translated, key).toBe('object');
        const forms = translated as PluralForms;
        for (const category of categoriesFor(language)) {
          expect(forms[category as Intl.LDMLPluralRule], `${key}.${category}`).toBeTruthy();
        }
        const wanted = placeholders(english.other).filter((p) => p !== 'count');
        for (const [category, text] of Object.entries(forms)) {
          const got = placeholders(text).filter((p) => p !== 'count');
          expect(got, `${key}.${category}`).toEqual(wanted);
        }
      }
    });
  }

  it('is not English under another name', () => {
    for (const language of LANGUAGES.filter((l) => l !== 'en')) {
      expect(translator(language).t('app.connecting'), language).not.toBe(en['app.connecting']);
    }
  });
});

describe('choosing a language', () => {
  it('falls back from region to base, base to region, and then to English', () => {
    expect(pickLanguage('de')).toBe('de');
    expect(pickLanguage('de-CH')).toBe('de');
    expect(pickLanguage('pt')).toBe('pt-BR');
    expect(pickLanguage('zh-Hant')).toBe('zh-Hans');
    expect(pickLanguage('ja')).toBe('en');
    expect(pickLanguage(undefined)).toBe('en');
  });

  it('reads hass.locale.language, then hass.language', () => {
    expect(languageOf({ locale: { language: 'fr' }, language: 'de' })).toBe('fr');
    expect(languageOf({ language: 'de' })).toBe('de');
    expect(languageOf(undefined)).toBe('en');
  });

  it('formats plurals with the language rules', () => {
    const pl = translator('pl');
    // Polish has three forms for whole numbers: 1, 2-4 and 5+.
    const forms = [1, 3, 5].map((n) => pl.tn('snooze.days', n));
    expect(new Set(forms).size).toBe(3);
    expect(EN.tn('snooze.days', 1)).toBe('1 day');
    expect(EN.tn('snooze.days', 7)).toBe('7 days');
  });

  it('words relative times with Intl in the language', () => {
    const fiveMinutes = new Date(minutesAgo(FIXED_NOW, 5));
    expect(formatRelative(fiveMinutes, FIXED_NOW)).toBe('5m ago');
    const german = formatRelative(fiveMinutes, FIXED_NOW, translator('de'));
    expect(german).toContain('5');
    expect(german).not.toBe('5m ago');
  });
});

describe('phrases the integration sends in English', () => {
  // Exactly as core/cycles.py and replacements.py write them.
  const BASES = [
    'trend over current cycle',
    'flat for 120 days',
    'slow drain over 21 days',
    'from 1 previous cycle of ~200 days',
    'from 3 previous cycles of ~45 days',
    'until charge needed',
  ];

  it('read back unchanged in English, so every pattern matches', () => {
    for (const basis of BASES) expect(translateBasis(basis, EN)).toBe(basis);
    expect(translateUnusual('draining 3× faster than usual', EN)).toBe(
      'draining 3× faster than usual',
    );
    expect(translateUnusual('level dropped suddenly', EN)).toBe('level dropped suddenly');
  });

  it('are translated with their numbers kept', () => {
    const de = translator('de');
    expect(translateBasis('from 3 previous cycles of ~45 days', de)).toMatch(/3.*45/);
    expect(translateBasis('trend over current cycle', de)).not.toBe('trend over current cycle');
    expect(translateUnusual('draining 3× faster than usual', de)).toContain('3');
  });

  it('pass anything unknown through as sent', () => {
    expect(translateBasis('a new phrase', translator('fr'))).toBe('a new phrase');
  });
});
