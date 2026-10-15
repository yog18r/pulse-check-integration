// @vitest-environment jsdom
/**
 * The custom element is what Home Assistant actually talks to, so test it
 * the way HA uses it: create it, call setConfig, assign hass, look inside
 * the shadow root.
 */
import { act, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PulseCheckCardElement } from '../../src/card/PulseCheckCardElement';
import { fakeHass } from '../fixtures/snapshot';

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
  it('renders the subscription into its shadow root once it has config and hass', async () => {
    const el = mount({ type: 'custom:pulse-check-card', title: 'Shadow' });
    expect(el.shadowRoot?.querySelector('.card')).toBeNull(); // no hass yet
    const fake = fakeHass();
    act(() => {
      el.hass = fake.hass;
    });
    await waitFor(() => {
      expect(el.shadowRoot?.querySelectorAll('.row').length).toBeGreaterThan(0);
    });
    expect(el.shadowRoot?.querySelector('.title')?.textContent).toBe('Shadow');
    expect(el.getCardSize()).toBeGreaterThan(2);
  });

  it('throws a readable error for bad config', () => {
    expect(() => mount({ group_by: 'colour' })).toThrow(/group_by/);
  });

  it('does not re-render for new hass objects on the same connection', async () => {
    const el = mount({ type: 'custom:pulse-check-card' });
    const fake = fakeHass();
    act(() => {
      el.hass = fake.hass;
    });
    await waitFor(() => {
      expect(el.shadowRoot?.querySelector('.row')).not.toBeNull();
    });
    const renderSpy = vi.spyOn(el as unknown as { render: () => void }, 'render');
    act(() => {
      el.hass = { ...fake.hass }; // HA does this several times a second
    });
    expect(renderSpy).not.toHaveBeenCalled();
    expect(el.hass).not.toBe(fake.hass); // but the latest hass is kept for service calls
  });

  it('unsubscribes when removed from the page', async () => {
    const el = mount({ type: 'custom:pulse-check-card' });
    const fake = fakeHass();
    act(() => {
      el.hass = fake.hass;
    });
    await waitFor(() => {
      expect(fake.subscribed()).toBe(true);
    });
    act(() => {
      el.remove();
    });
    expect(fake.unsubscribe).toHaveBeenCalledOnce();
  });
});
