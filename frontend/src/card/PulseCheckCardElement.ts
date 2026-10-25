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
 * React root inside it. The data comes from the integration's websocket
 * subscription (started inside React), so the stream of `hass` objects HA
 * sends is only kept in a box for service calls; it never triggers a
 * re-render by itself.
 */
import { createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { hasConnectivityProblem } from '../core/thresholds';
import type { DeviceHealth, HassLike, HassBox } from '../core/types';
import { languageOf, translator } from '../i18n';
import { App } from '../ui/App';
import styles from '../ui/styles.css?inline';
import {
  ConfigError,
  configErrorText,
  resolveConfig,
  type CardConfig,
  type ResolvedConfig,
} from './config';
import { openDevice } from './navigation';
import type { Snapshot } from './snapshot';

/** Tag name of the editor element; registered alongside the card in index.ts. */
export const EDITOR_TAG = 'pulse-check-card-editor';

export class PulseCheckCardElement extends HTMLElement {
  private readonly shadow: ShadowRoot;
  private readonly mountPoint: HTMLDivElement;
  private reactRoot: Root | null = null;

  private config: ResolvedConfig | null = null;
  private readonly hassBox: HassBox = { latest: undefined };
  private lastSnapshot: Snapshot | undefined;

  // Arrow functions so `this` is bound when React calls them back.
  private readonly handleOpenDevice = (device: DeviceHealth): void => {
    openDevice(this, device);
  };
  private readonly handleSnapshot = (snapshot: Snapshot): void => {
    this.lastSnapshot = snapshot;
  };

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

  /** The visual editor. HA calls this when the user opens the card editor. */
  static getConfigElement(): HTMLElement {
    return document.createElement(EDITOR_TAG);
  }

  /* ---- HA contract ---------------------------------------------------- */

  setConfig(config: unknown): void {
    // resolveConfig throws ConfigError with a readable message; HA catches
    // whatever we throw here and shows it on the card, so it is reworded in
    // the user's language when hass has already told us which that is.
    try {
      this.config = resolveConfig(config);
    } catch (err) {
      if (err instanceof ConfigError && this.hassBox.latest) {
        throw new Error(configErrorText(err, translator(languageOf(this.hassBox.latest))), {
          cause: err,
        });
      }
      throw err;
    }
    this.render();
  }

  set hass(hass: HassLike | undefined) {
    const previous = this.hassBox.latest;
    this.hassBox.latest = hass;
    if (!hass) return;
    // Only a new connection (first hass, or a reconnect) or a new language
    // needs a render: the subscription is tied to the connection, and the
    // text to the language. Everything else is read on demand.
    if (previous?.connection !== hass.connection || languageOf(previous) !== languageOf(hass)) {
      this.render();
    }
  }

  get hass(): HassLike | undefined {
    return this.hassBox.latest;
  }

  /** Approximate height in units of ~50px, used by the masonry layout. */
  getCardSize(): number {
    const devices = this.lastSnapshot?.devices ?? [];
    const rows = Math.max(
      devices.filter((d) => d.battery).length,
      devices.filter(hasConnectivityProblem).length,
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
    // its subscription and timers stop, and remount on the next connect.
    this.reactRoot?.unmount();
    this.reactRoot = null;
  }

  /* ---- rendering ------------------------------------------------------ */

  private render(): void {
    if (!this.isConnected || !this.config || !this.hassBox.latest) return;

    this.reactRoot ??= createRoot(this.mountPoint);
    this.reactRoot.render(
      createElement(App, {
        hassBox: this.hassBox,
        config: this.config,
        onOpenDevice: this.handleOpenDevice,
        onSnapshot: this.handleSnapshot,
      }),
    );
  }
}
