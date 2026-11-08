/**
 * The card's version: the integration's manifest.json version, baked in at
 * build time. Kept in its own module so components can compare it with the
 * installed version without importing the entry point, which registers the
 * custom elements as a side effect.
 */
export const CARD_VERSION: string = __CARD_VERSION__;
