/**
 * Common battery sizes, offered as a dropdown in the editor.
 *
 * The config value is free text, so anything not listed can be typed under
 * "Other". The list follows the usual consumer names (IEC names in
 * brackets where people might search by them).
 */

export interface BatteryTypeGroup {
  label: string;
  types: string[];
}

export const BATTERY_TYPE_GROUPS: BatteryTypeGroup[] = [
  {
    label: 'Cylindrical',
    types: ['AA', 'AAA', 'AAAA', 'C', 'D', 'N (LR1)', '1/2 AA', '9V (PP3)'],
  },
  {
    label: 'Coin cells',
    types: [
      'CR2032',
      'CR2025',
      'CR2016',
      'CR2450',
      'CR2477',
      'CR2430',
      'CR1632',
      'CR1620',
      'CR1616',
      'CR1220',
      'LR44 (AG13)',
      'LR41 (AG3)',
      'SR626SW (377)',
    ],
  },
  {
    label: 'Lithium photo',
    types: ['CR123A', 'CR2', 'CR-P2', 'CR-V3'],
  },
  {
    label: 'Lithium-ion cells',
    types: ['18650', '21700', '14500', '16340 (RCR123)', '26650'],
  },
  {
    label: 'Packs',
    types: ['Built-in rechargeable', 'Li-ion pack', 'NiMH pack', 'A23 (12V)', 'A27 (12V)'],
  },
];

/** Every listed type, flat, for membership checks. */
export const BATTERY_TYPES: readonly string[] = BATTERY_TYPE_GROUPS.flatMap((g) => g.types);

/** Sentinel used by the editor's dropdown for "Other…". Never stored in config. */
export const OTHER_BATTERY_TYPE = '__other__';

export function isKnownBatteryType(type: string): boolean {
  const wanted = type.trim().toLowerCase();
  return BATTERY_TYPES.some((t) => t.toLowerCase() === wanted);
}
