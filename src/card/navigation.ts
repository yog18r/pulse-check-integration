/**
 * Opening things in Home Assistant from inside a card.
 *
 * HA's frontend is a single-page app. Cards don't link to pages; they
 * push a URL and fire a `location-changed` event, and HA's router picks it
 * up. Likewise the "more info" dialog for an entity opens by firing a
 * `hass-more-info` event that bubbles up out of the card (through the
 * shadow DOM, hence `composed: true`).
 *
 * Both are plain DOM events, so the demo page can listen for them too.
 */
import { ORPHAN_PREFIX } from '../core/group';
import type { DeviceHealth } from '../core/types';

export function navigateTo(path: string): void {
  history.pushState(null, '', path);
  window.dispatchEvent(new CustomEvent('location-changed', { detail: { replace: false } }));
}

export function showMoreInfo(host: HTMLElement, entityId: string): void {
  host.dispatchEvent(
    new CustomEvent('hass-more-info', {
      detail: { entityId },
      bubbles: true,
      composed: true,
    }),
  );
}

/**
 * Open the best page for a device: its device page when it has one, or the
 * more-info dialog for a device-less entity.
 */
export function openDevice(host: HTMLElement, device: DeviceHealth): void {
  if (device.deviceId.startsWith(ORPHAN_PREFIX)) {
    const entityId = device.entityIds[0] ?? device.deviceId.slice(ORPHAN_PREFIX.length);
    showMoreInfo(host, entityId);
    return;
  }
  navigateTo(`/config/devices/device/${encodeURIComponent(device.deviceId)}`);
}
