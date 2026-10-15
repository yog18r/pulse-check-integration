/**
 * The card's translations.
 *
 * Home Assistant gives every card the user's language on `hass.locale.language`
 * (older versions: `hass.language`), as a code such as `de` or `pt-BR`.
 * `translator(language)` returns the strings for the closest catalog: the
 * exact code, else its base language (`de-CH` reads `de`), else a regional
 * variant of the base (`pt` reads `pt-BR`), else English. A key missing from
 * a catalog falls back to English too, so a half-finished translation shows
 * English words rather than nothing.
 *
 * Dates, times and "5m ago" use the browser's `Intl` formatters in the same
 * language, so they need no catalog entries.
 */
import { cs } from './cs';
import { de } from './de';
import { en, type PluralForms } from './en';
import { es } from './es';
import { fr } from './fr';
import { it } from './it';
import { nl } from './nl';
import { pl } from './pl';
import { ptBR } from './pt-BR';
import { zhHans } from './zh-Hans';

export type { PluralForms } from './en';

type English = typeof en;
/** Keys whose English value is a plain string. */
export type MessageKey = {
  [K in keyof English]: English[K] extends string ? K : never;
}[keyof English];
/** Keys whose wording depends on a count. */
export type PluralKey = Exclude<keyof English, MessageKey>;

/** A translation: every key, with a string or plural forms as in English. */
export type Catalog = { [K in keyof English]: English[K] extends string ? string : PluralForms };

export type Params = Record<string, string | number>;

export const CATALOGS: Readonly<Record<string, Catalog>> = {
  en,
  de,
  fr,
  es,
  nl,
  it,
  'pt-BR': ptBR,
  pl,
  'zh-Hans': zhHans,
  cs,
};

export const FALLBACK_LANGUAGE = 'en';

/** The catalog code to use for a Home Assistant language code. */
export function pickLanguage(language: string | undefined, available = Object.keys(CATALOGS)) {
  if (!language) return FALLBACK_LANGUAGE;
  const wanted = language.toLowerCase();
  const exact = available.find((code) => code.toLowerCase() === wanted);
  if (exact) return exact;
  const base = wanted.split('-')[0] ?? wanted;
  const sameBase = available.filter((code) => code.toLowerCase().split('-')[0] === base);
  return sameBase.find((code) => code.toLowerCase() === base) ?? sameBase[0] ?? FALLBACK_LANGUAGE;
}

/** The parts of `hass` that say which language the user reads. */
export interface LanguageSource {
  locale?: { language?: string } | undefined;
  language?: string | undefined;
}

/** The user's language: `hass.locale.language`, then `hass.language`, then English. */
export function languageOf(hass: LanguageSource | undefined): string {
  return hass?.locale?.language ?? hass?.language ?? FALLBACK_LANGUAGE;
}

function fill(template: string, params: Params): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

export interface Translator {
  /** The catalog's language code, also used for `Intl` formatting. */
  readonly language: string;
  /** A plain message, with `{placeholders}` filled in. */
  t(key: MessageKey, params?: Params): string;
  /** A message that depends on `count`, which is also available as `{count}`. */
  tn(key: PluralKey, count: number, params?: Params): string;
}

const cache = new Map<string, Translator>();

/** The translator for a Home Assistant language code. Cached per catalog. */
export function translator(language?: string): Translator {
  const code = pickLanguage(language);
  const cached = cache.get(code);
  if (cached) return cached;
  const catalog = CATALOGS[code] ?? en;
  const plurals = new Intl.PluralRules(code);
  const made: Translator = {
    language: code,
    t(key, params = {}) {
      return fill(catalog[key] || en[key], params);
    },
    tn(key, count, params = {}) {
      const forms: PluralForms = catalog[key];
      const category = plurals.select(count);
      const template = forms[category] ?? forms.other;
      return fill(template, { count, ...params });
    },
  };
  cache.set(code, made);
  return made;
}

/** English, for code that runs before any `hass` is known, and for tests. */
export const EN: Translator = translator(FALLBACK_LANGUAGE);
