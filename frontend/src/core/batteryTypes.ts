/**
 * How a battery type is shown.
 *
 * The stored value is free text, usually a standard size ("CR2032", "AA"),
 * set in the integration's per-device settings. A few common types are
 * words rather than sizes; those are translated for display.
 */

import { EN, type MessageKey, type Translator } from '../i18n';

// Types that are words rather than standard sizes. The stored value stays
// English (it is data, and the shopping list groups by it); only the label
// shown is translated.
const WORD_TYPES: Partial<Record<string, MessageKey>> = {
  'Built-in rechargeable': 'battery_type.builtin',
  'Li-ion pack': 'battery_type.li_ion_pack',
  'NiMH pack': 'battery_type.nimh_pack',
};

/** How a battery type is shown: "CR2032" as it is, "Built-in rechargeable" translated. */
export function batteryTypeLabel(type: string, t: Translator = EN): string {
  const key = WORD_TYPES[type];
  return key ? t.t(key) : type;
}
