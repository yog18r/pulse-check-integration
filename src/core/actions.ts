/**
 * The action list: what to actually do about each low battery.
 *
 *   replace   "Replace 2 × AA in Kitchen Mini Switch"
 *   charge    "Charge Office 1 Large"  (rechargeable: true in the device's settings)
 *
 * plus a shopping summary: how many of each battery type to buy, totalled
 * across the devices that need replacing. The integration builds the list;
 * these are the shapes it sends.
 */
import type { Severity } from './types';

export const UNKNOWN_BATTERY_TYPE = 'Unknown type';

export type ActionKind = 'replace' | 'charge';

export interface ActionItem {
  kind: ActionKind;
  deviceId: string;
  name: string;
  severity: Severity;
  /** Battery type, or UNKNOWN_BATTERY_TYPE when not configured. */
  batteryType: string;
  /** Cells to replace (1 when not configured). Meaningless for "charge". */
  count: number;
  /** "Replace 2 × AA in Kitchen Mini Switch" */
  label: string;
}

export interface ShoppingLine {
  batteryType: string;
  /** Total cells across every device needing this type. */
  count: number;
  devices: number;
}

export interface ActionList {
  replace: ActionItem[];
  charge: ActionItem[];
  /** Totals for the "to buy" summary, biggest first, unknown last. */
  shopping: ShoppingLine[];
}

export const EMPTY_ACTIONS: ActionList = { replace: [], charge: [], shopping: [] };
