// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CardConfig } from '../../src/card/config';
import type { HassLike } from '../../src/core/types';
import { translator } from '../../src/i18n';
import { EditorForm, INTEGRATION_PAGE } from '../../src/ui/EditorForm';
import { fakeHass } from '../fixtures/snapshot';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * Home Assistant owns the config and re-renders the editor with every
 * `config-changed`. This little harness does the same, so typing several
 * characters builds on the previous keystroke instead of the stale prop.
 */
function Harness({
  initial,
  onEmit,
  hass,
}: {
  initial: CardConfig;
  onEmit: (c: CardConfig) => void;
  hass: HassLike;
}) {
  const [config, setConfig] = useState(initial);
  return (
    <EditorForm
      config={config}
      hass={hass}
      onChange={(next) => {
        setConfig(next);
        onEmit(next);
      }}
    />
  );
}

function renderEditor(initial: CardConfig = { type: 'custom:pulse-check-card' }) {
  const fake = fakeHass();
  const onEmit = vi.fn();
  render(<Harness initial={initial} onEmit={onEmit} hass={fake.hass} />);
  const latest = () => onEmit.mock.lastCall?.[0] as CardConfig;
  return { ...fake, onEmit, latest };
}

describe('EditorForm: language', () => {
  it("labels every field in the user's language", () => {
    const fake = fakeHass();
    fake.hass.locale = { language: 'fr' };
    render(<Harness initial={{}} onEmit={vi.fn()} hass={fake.hass} />);
    const fr = translator('fr');
    expect(screen.getByLabelText(fr.t('editor.title'))).toBeInTheDocument();
    expect(screen.getByText(fr.t('editor.device_settings'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: fr.t('editor.device_settings_link') })).toBeVisible();
    expect(screen.getByRole('checkbox', { name: fr.t('tab.actions') })).toBeInTheDocument();
  });

  it('shows config errors in that language too', () => {
    const fake = fakeHass();
    fake.hass.locale = { language: 'de' };
    render(<Harness initial={{ max_rows: 0 }} onEmit={vi.fn()} hass={fake.hass} />);
    expect(screen.getByRole('alert')).toHaveTextContent(translator('de').t('config.max_rows'));
  });
});

describe('EditorForm: presentation options', () => {
  it('emits a minimal config: set fields appear, cleared fields disappear', async () => {
    const { latest } = renderEditor();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText('Title'), 'Health');
    expect(latest()).toMatchObject({ title: 'Health' });

    await user.clear(screen.getByLabelText('Title'));
    expect(latest()).not.toHaveProperty('title');
    expect(latest()).toMatchObject({ type: 'custom:pulse-check-card' });
  });

  it('writes tabs, grouping, sort and row options', async () => {
    const { latest } = renderEditor();
    const user = userEvent.setup();

    await user.click(screen.getByRole('checkbox', { name: 'Actions' }));
    expect(latest().show_tabs).toEqual(['batteries', 'connectivity', 'actions']);

    await user.selectOptions(screen.getByLabelText('Group by'), 'area');
    expect(latest().group_by).toBe('area');
    await user.selectOptions(screen.getByLabelText('Group by'), 'none');
    expect(latest()).not.toHaveProperty('group_by');

    await user.selectOptions(screen.getByLabelText('Sort order'), 'replace_soon');
    expect(latest().sort).toBe('replace_soon');
    expect(latest()).not.toHaveProperty('battery_sort');

    await user.click(screen.getByRole('checkbox', { name: 'Show all rows' }));
    expect(latest().max_rows).toBe('all');

    await user.click(screen.getByRole('checkbox', { name: 'Batteries tab: problems only' }));
    expect(latest().problems_only).toBe(true);
  });

  it('view filters are tick-to-keep lists that write only what is still ticked', async () => {
    const { latest } = renderEditor();
    const user = userEvent.setup();

    const garage = screen.getByRole('checkbox', { name: 'Garage' });
    expect(garage).toBeChecked();
    await user.click(garage);
    expect([...(latest().areas ?? [])].sort()).toEqual([
      'bedroom',
      'hallway',
      'kitchen',
      'living_room',
      'office',
    ]);
    // Ticking it again means "all areas": the key disappears.
    await user.click(screen.getByRole('checkbox', { name: 'Garage' }));
    expect(latest()).not.toHaveProperty('areas');

    await user.click(screen.getByRole('checkbox', { name: 'Locks' }));
    expect(latest().device_types).toHaveLength(11);
    expect(latest().device_types).not.toContain('lock');

    await user.click(screen.getByRole('checkbox', { name: 'mobile_app' }));
    expect(latest().integrations).not.toContain('mobile_app');
  });

  it('shows the validation message the card would show', () => {
    renderEditor({ default_tab: 'actions', show_tabs: ['batteries'] });
    expect(screen.getByRole('alert')).toHaveTextContent(/not in "show_tabs"/);
  });

  it('offers view filters but no thresholds: those belong to the integration', async () => {
    renderEditor();
    await screen.findByText(/set in\s+the integration/);
    expect(screen.queryByLabelText(/Battery warning/)).not.toBeInTheDocument();
    expect(screen.getByText('Areas shown on this card')).toBeInTheDocument();
  });

  it('switches the older battery_sort spelling to sort when it opens', async () => {
    const { latest } = renderEditor({
      type: 'custom:pulse-check-card',
      battery_sort: 'replace_soon',
    });
    await waitFor(() => {
      expect(latest()).toEqual({ type: 'custom:pulse-check-card', sort: 'replace_soon' });
    });
    expect(screen.getByLabelText('Sort order')).toHaveValue('replace_soon');
    expect(screen.getByRole('option', { name: 'Soonest to replace first' })).toBeInTheDocument();
  });
});

describe('EditorForm: per-device settings', () => {
  it('points to the integration instead of editing them here', () => {
    renderEditor();
    expect(screen.getByRole('heading', { name: 'Per-device settings' })).toBeInTheDocument();
    expect(screen.getByText(/Configure → Per-device settings/)).toBeInTheDocument();
    // The old panel is gone: no device search, no fields that save to Pulse Check.
    expect(screen.queryByRole('combobox', { name: 'Device' })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Search devices/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Battery type')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Rechargeable')).not.toBeInTheDocument();
  });

  it("opens the integration's page the way Home Assistant navigates", async () => {
    const { callService } = renderEditor();
    const pushState = vi.spyOn(history, 'pushState').mockImplementation(() => undefined);
    const dispatch = vi.spyOn(window, 'dispatchEvent');
    const user = userEvent.setup();

    const link = screen.getByRole('link', { name: 'Open Pulse Check settings' });
    // A real href, so middle-click and "open in new tab" still work.
    expect(link).toHaveAttribute('href', '/config/integrations/integration/pulse_check');
    await user.click(link);

    expect(pushState).toHaveBeenCalledWith(null, '', INTEGRATION_PAGE);
    const event = dispatch.mock.calls.map(([e]) => e).find((e) => e.type === 'location-changed');
    expect(event).toBeInstanceOf(CustomEvent);
    expect((event as CustomEvent).detail).toEqual({ replace: false });
    // Nothing is saved through the integration's services from the editor.
    expect(callService).not.toHaveBeenCalled();
  });

  it('leaves a Ctrl+click to the browser (new tab)', async () => {
    renderEditor();
    const pushState = vi.spyOn(history, 'pushState').mockImplementation(() => undefined);
    // Note whether the card cancelled the click, then cancel it ourselves:
    // jsdom cannot open a new tab and would only log "not implemented".
    let cancelledByCard: boolean | undefined;
    const browser = (e: MouseEvent) => {
      cancelledByCard = e.defaultPrevented;
      e.preventDefault();
    };
    document.addEventListener('click', browser);
    const user = userEvent.setup();
    await user.keyboard('{Control>}');
    await user.click(screen.getByRole('link', { name: 'Open Pulse Check settings' }));
    await user.keyboard('{/Control}');
    document.removeEventListener('click', browser);
    expect(cancelledByCard).toBe(false);
    expect(pushState).not.toHaveBeenCalled();
  });
});
