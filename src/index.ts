/**
 * Entry point for the Pulse Check Card bundle.
 *
 * This file runs once when Home Assistant loads /local/pulse-check-card.js.
 * It registers the custom element and announces the card to the dashboard
 * card picker.
 */
import { PulseCheckCardEditor } from './card/PulseCheckCardEditor';
import { EDITOR_TAG, PulseCheckCardElement } from './card/PulseCheckCardElement';

export const CARD_TAG = 'pulse-check-card';
export const CARD_VERSION = '0.2.0';

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

window.customCards ??= [];
if (!window.customCards.some((c) => c.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: 'Pulse Check Card',
    description: 'Battery levels, offline and gone-quiet devices across every integration.',
    preview: true,
    documentationURL: 'https://github.com/yog18r/pulse-check-card',
  });
}

console.info(
  `%c PULSE-CHECK-CARD %c v${CARD_VERSION} `,
  'color: white; background: #43a047; font-weight: 700;',
  'color: #43a047; background: white; font-weight: 700;',
);
