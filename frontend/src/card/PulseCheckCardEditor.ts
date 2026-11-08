/**
 * The visual editor element Home Assistant opens when a user clicks
 * "Edit" on the card and stays in the visual (non-YAML) mode.
 *
 * HA's contract for an editor element:
 *   setConfig(config)   the current raw config
 *   hass = ...          same as the card
 *   fire "config-changed" with { config } whenever the user changes something
 *
 * Like the card itself it is a thin shell around a React tree. Every
 * option goes into the card's YAML through `config-changed`.
 */
import { createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { HassLike } from '../core/types';
import { languageOf } from '../i18n';
import { EditorForm } from '../ui/EditorForm';
import styles from '../ui/editor.css?inline';
import type { CardConfig } from './config';

export class PulseCheckCardEditor extends HTMLElement {
  private readonly mountPoint: HTMLDivElement;
  private reactRoot: Root | null = null;
  private config: CardConfig = {};
  private latestHass: HassLike | undefined;

  private readonly handleChange = (config: CardConfig): void => {
    this.config = config;
    this.dispatchEvent(
      new CustomEvent('config-changed', {
        detail: { config },
        bubbles: true,
        composed: true,
      }),
    );
    this.render();
  };

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = styles;
    shadow.appendChild(style);
    this.mountPoint = document.createElement('div');
    shadow.appendChild(this.mountPoint);
  }

  setConfig(config: CardConfig): void {
    this.config = { ...config };
    this.render();
  }

  set hass(hass: HassLike | undefined) {
    const previous = this.latestHass;
    this.latestHass = hass;
    // HA sets `hass` on every state change anywhere. The form only uses the
    // registries (for the filter lists, replaced as objects when they change)
    // and the language, so re-render only when one of those changed.
    const changed =
      previous?.entities !== hass?.entities ||
      previous?.areas !== hass?.areas ||
      languageOf(previous) !== languageOf(hass);
    if (changed) this.render();
  }

  get hass(): HassLike | undefined {
    return this.latestHass;
  }

  connectedCallback(): void {
    this.render();
  }

  disconnectedCallback(): void {
    this.reactRoot?.unmount();
    this.reactRoot = null;
  }

  private render(): void {
    if (!this.isConnected) return;
    this.reactRoot ??= createRoot(this.mountPoint);
    this.reactRoot.render(
      createElement(EditorForm, {
        config: this.config,
        onChange: this.handleChange,
        hass: this.latestHass,
      }),
    );
  }
}
