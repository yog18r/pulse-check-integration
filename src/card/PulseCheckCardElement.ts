/**
 * The custom element Home Assistant talks to.
 *
 * HA knows nothing about React. It expects a plain HTML element with a
 * handful of methods and properties (the "card contract"):
 *
 *   setConfig(config)   called once with the user's YAML; throw to show an error
 *   hass = ...          called VERY often with the latest state of everything
 *   getCardSize()       rough height in 50px rows, for the masonry layout
 *   getGridOptions()    sizing hints for the newer sections layout
 *   static getStubConfig()  default config for the card picker preview
 *
 * This class is the bridge: it owns a shadow root (so CSS is isolated) and a
 * React root inside it, and decides WHEN React should re-render. React then
 * decides WHAT to draw.
 */
import { createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { fingerprint, registriesChanged } from '../core/fingerprint';
import type { HassLike } from '../core/types';
import { ENHANCERS } from '../enhancers';
import { App } from '../ui/App';
import styles from '../ui/styles.css?inline';
import { resolveConfig, type CardConfig, type ResolvedConfig } from './config';
import { analyseDevices } from '../core/analyse';
import { batteryList, connectivityList } from '../core/sort';

export class PulseCheckCardElement extends HTMLElement {
  private readonly shadow: ShadowRoot;
  private readonly mountPoint: HTMLDivElement;
  private reactRoot: Root | null = null;

  private config: ResolvedConfig | null = null;
  private _hass: HassLike | undefined = undefined;
  private lastFingerprint = '';

  constructor() {
    super();
    // mode: 'open' lets devtools (and tests) inspect the shadow DOM.
    this.shadow = this.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = styles;
    this.shadow.appendChild(style);

    this.mountPoint = document.createElement('div');
    this.shadow.appendChild(this.mountPoint);
  }

  /** Default config shown when the user picks the card in the UI. */
  static getStubConfig(): CardConfig {
    return { title: 'Pulse Check' };
  }

  /* ---- HA contract ---------------------------------------------------- */

  setConfig(config: unknown): void {
    // resolveConfig throws ConfigError with a readable message; HA catches
    // whatever we throw here and shows it on the card.
    this.config = resolveConfig(config);
    this.lastFingerprint = ''; // force a render with the new config
    this.render();
  }

  set hass(hass: HassLike | undefined) {
    const previous = this._hass;
    this._hass = hass;
    if (!hass) return;

    // Skip the (relatively) expensive path when nothing we care about moved.
    if (!registriesChanged(previous, hass)) {
      const fp = fingerprint(hass);
      if (fp === this.lastFingerprint) return;
      this.lastFingerprint = fp;
    } else {
      this.lastFingerprint = fingerprint(hass);
    }

    this.render();
  }

  get hass(): HassLike | undefined {
    return this._hass;
  }

  /** Approximate height in units of ~50px, used by the masonry layout. */
  getCardSize(): number {
    if (!this.config || !this._hass) return 3;
    const devices = analyseDevices(this._hass, this.config, { now: new Date() });
    const rows = Math.max(
      batteryList(devices, this.config).length,
      connectivityList(devices).length,
    );
    // header + tabs ≈ 2 rows, each device row ≈ 1 row, cap so we don't dominate.
    return 2 + Math.min(rows, 10);
  }

  /** Sizing for the sections (grid) layout. */
  getGridOptions(): { columns: number; min_columns: number; rows: 'auto' } {
    return { columns: 12, min_columns: 6, rows: 'auto' };
  }

  /* ---- lifecycle ------------------------------------------------------ */

  connectedCallback(): void {
    this.render();
  }

  disconnectedCallback(): void {
    // HA removes and re-adds cards when editing dashboards. Unmount React so
    // its timers (useNow) stop, and remount on the next connect.
    this.reactRoot?.unmount();
    this.reactRoot = null;
  }

  /* ---- rendering ------------------------------------------------------ */

  private render(): void {
    if (!this.isConnected || !this.config || !this._hass) return;

    this.reactRoot ??= createRoot(this.mountPoint);
    this.reactRoot.render(
      createElement(App, { hass: this._hass, config: this.config, enhancers: ENHANCERS }),
    );
  }
}
