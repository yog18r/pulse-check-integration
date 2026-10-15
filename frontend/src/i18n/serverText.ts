/**
 * The few phrases the integration sends as English text.
 *
 * A days-left estimate carries a `basis` ("trend over current cycle") and a
 * battery can carry an `unusual` note ("draining 3× faster than usual").
 * They are made on the server (`core/cycles.py`, `replacements.py`), which
 * has no idea who will read them, and they are not part of the frozen
 * golden output. These patterns are the complete set the integration
 * produces; each is translated here with its numbers kept. Anything else
 * is shown exactly as sent, so a new phrase on the server degrades to
 * English instead of disappearing.
 */
import type { Translator } from './index';

type Rule = [RegExp, (t: Translator, match: RegExpMatchArray) => string];

const n = (text: string | undefined) => Number(text ?? 0);

const BASIS: Rule[] = [
  [/^trend over current cycle$/, (t) => t.t('basis.trend')],
  [/^flat for (\d+) days?$/, (t, m) => t.tn('basis.flat', n(m[1]))],
  [/^slow drain over (\d+) days?$/, (t, m) => t.tn('basis.slow', n(m[1]))],
  [
    /^from (\d+) previous cycles? of ~(\d+) days$/,
    (t, m) => t.tn('basis.cycles', n(m[1]), { days: m[2] ?? '' }),
  ],
  [/^until charge needed$/, (t) => t.t('basis.charge')],
];

const UNUSUAL: Rule[] = [
  [/^draining (\d+)× faster than usual$/, (t, m) => t.t('unusual.faster', { factor: m[1] ?? '' })],
  [/^level dropped suddenly$/, (t) => t.t('unusual.drop')],
];

function translate(rules: Rule[], text: string, t: Translator): string {
  for (const [pattern, render] of rules) {
    const match = pattern.exec(text);
    if (match) return render(t, match);
  }
  return text;
}

/** An estimate's `basis` in the user's language. */
export function translateBasis(basis: string, t: Translator): string {
  return translate(BASIS, basis, t);
}

/** A battery's `unusual` note in the user's language. */
export function translateUnusual(note: string, t: Translator): string {
  return translate(UNUSUAL, note, t);
}
