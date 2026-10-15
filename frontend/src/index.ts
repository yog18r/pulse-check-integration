/**
 * Entry point for the Pulse Check Card bundle.
 *
 * This file runs once when Home Assistant loads the bundle, which the
 * integration serves at /pulse_check/pulse-check-card.js. It registers the
 * custom element and announces the card to the dashboard card picker.
 */
import { PulseCheckCardEditor } from './card/PulseCheckCardEditor';
import { EDITOR_TAG, PulseCheckCardElement } from './card/PulseCheckCardElement';
import { translator } from './i18n';

export const CARD_TAG = 'pulse-check-card';
/** The integration's version, read from its manifest.json at build time. */
export const CARD_VERSION = __CARD_VERSION__;

// Guard against double registration (HA can load a resource twice during
// dashboard edits; `customElements.define` throws on a duplicate name).
if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, PulseCheckCardElement);
}
if (!customElements.get(EDITOR_TAG)) {
  customElements.define(EDITOR_TAG, PulseCheckCardEditor);
}

/** The shape HA's card picker reads from `window.customCards`. */
interface CustomCardEntry {
  type: string;
  name: string;
  description: string;
  preview?: boolean;
  documentationURL?: string;
}

declare global {
  interface Window {
    customCards?: CustomCardEntry[];
  }
}

// The bundle loads before any card has a `hass`, so the picker entry takes
// the page's language, which Home Assistant's frontend sets on <html lang>.
const pickerText = translator(document.documentElement.lang || navigator.language);

window.customCards ??= [];
if (!window.customCards.some((c) => c.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: pickerText.t('card.name'),
    description: pickerText.t('card.description'),
    preview: true,
    documentationURL: 'https://github.com/yog18r/pulse-check-integration',
  });
}

console.info(
  `%c PULSE-CHECK-CARD %c v${CARD_VERSION} `,
  'color: white; background: #43a047; font-weight: 700;',
  'color: #43a047; background: white; font-weight: 700;',
);
