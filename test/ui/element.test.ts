// @vitest-environment jsdom
/**
 * The custom element is what Home Assistant actually talks to, so test it
 * the way HA uses it: create it, call setConfig, assign hass, look inside
 * the shadow root.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act } from '@testing-library/react';
import { PulseCheckCardElement } from '../../src/card/PulseCheckCardElement';
import { buildHass, FIXED_NOW } from '../fixtures/hass';

if (!customElements.get('pulse-check-card-test')) {
  customElements.define('pulse-check-card-test', PulseCheckCardElement);
}

function mount(config: unknown) {
  const el = document.createElement('pulse-check-card-test') as PulseCheckCardElement;
  el.setConfig(config);
  document.body.appendChild(el);
  return el;
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('PulseCheckCardElement', () => {
  it('renders into its shadow root once it has config and hass', () => {
    const el = mount({ type: 'custom:pulse-check-card', title: 'Shadow' });
    expect(el.shadowRoot?.querySelector('.card')).toBeNull(); // no hass yet
    act(() => {
      el.hass = buildHass(FIXED_NOW);
    });
    expect(el.shadowRoot?.querySelector('.title')?.textContent).toBe('Shadow');
    expect(el.shadowRoot?.querySelectorAll('.row').length).toBeGreaterThan(0);
  });

  it('throws a readable error for bad config', () => {
    expect(() => mount({ battery_warning: 'lots' })).toThrow(/battery_warning/);
  });

  it('does not re-render when an irrelevant entity changes', () => {
    const el = mount({ type: 'custom:pulse-check-card' });
    const first = buildHass(FIXED_NOW);
    act(() => {
      el.hass = first;
    });
    const root = el.shadowRoot!;
    const rowsBefore = root.querySelector('.rows');

    // Same registries, one unrelated template sensor ticks: same fingerprint.
    const noise = {
      ...first,
      states: {
        ...first.states,
        'sensor.random_template': { ...first.states['sensor.random_template']!, state: '43' },
      },
    };
    const renderSpy = vi.spyOn(el as unknown as { render: () => void }, 'render');
    act(() => {
      el.hass = noise;
    });
    expect(renderSpy).not.toHaveBeenCalled();
    expect(root.querySelector('.rows')).toBe(rowsBefore);
  });

  it('reports a card size that grows with the rows', () => {
    const el = mount({ type: 'custom:pulse-check-card' });
    expect(el.getCardSize()).toBe(3);
    act(() => {
      el.hass = buildHass(FIXED_NOW);
    });
    expect(el.getCardSize()).toBeGreaterThan(3);
    expect(el.getGridOptions()).toEqual({ columns: 12, min_columns: 6, rows: 'auto' });
  });
});
