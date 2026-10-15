// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CardConfig } from '../../src/card/config';
import { EditorForm } from '../../src/ui/EditorForm';
import { hass } from '../fixtures/hass';

afterEach(cleanup);

/**
 * Home Assistant owns the config and re-renders the editor with every
 * `config-changed`. This little harness does the same, so typing several
 * characters builds on the previous keystroke instead of the stale prop.
 */
function Harness({ initial, onEmit }: { initial: CardConfig; onEmit: (c: CardConfig) => void }) {
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
  const onEmit = vi.fn();
  render(<Harness initial={initial} onEmit={onEmit} />);
  const latest = () => onEmit.mock.lastCall?.[0] as CardConfig;
  return { onEmit, latest };
}

describe('EditorForm', () => {
  it('emits a minimal config: set fields appear, cleared fields disappear', async () => {
    const { latest } = renderEditor();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText('Title'), 'Health');
    expect(latest()).toMatchObject({ title: 'Health' });

    await user.clear(screen.getByLabelText('Title'));
    expect(latest()).not.toHaveProperty('title');
    expect(latest()).toMatchObject({ type: 'custom:pulse-check-card' });
  });

  it('adds a per-device row with a searchable picker and writes device_settings', async () => {
    const { latest } = renderEditor();
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: '+ Add device' }));
    expect(latest().device_settings).toHaveLength(1);

    const picker = screen.getByRole('combobox', { name: 'Device' });
    await user.click(picker);
    await user.type(picker, 'kitchen');
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(1);
    await user.keyboard('{Enter}');
    expect(latest().device_settings?.[0]).toMatchObject({ device_id: 'dev_shelly_ht' });

    // The area select is pre-filled from the registry, and leaving it alone
    // writes no override.
    expect(screen.getByLabelText('Area')).toHaveValue('Kitchen');
    expect(latest().device_settings?.[0]).not.toHaveProperty('area');

    await user.selectOptions(screen.getByLabelText('Area'), 'Garage');
    expect(latest().device_settings?.[0]).toMatchObject({ area: 'Garage' });

    await user.selectOptions(screen.getByLabelText('Battery type'), 'AA');
    await user.type(screen.getByLabelText('Battery count'), '2');
    await user.click(screen.getByLabelText('Rechargeable'));
    expect(latest().device_settings?.[0]).toEqual({
      device_id: 'dev_shelly_ht',
      area: 'Garage',
      battery_type: 'AA',
      battery_count: 2,
      rechargeable: true,
    });
  });

  it('areas and integrations are ticked by default; unticking writes an exclusion', async () => {
    const { latest } = renderEditor();
    const user = userEvent.setup();

    const garage = screen.getByRole('checkbox', { name: 'Garage' });
    expect(garage).toBeChecked();
    await user.click(garage);
    expect(latest().exclude_areas).toEqual(['garage']);
    expect(latest()).not.toHaveProperty('include_areas');

    await user.click(screen.getByRole('checkbox', { name: 'mobile_app' }));
    expect(latest().exclude_integrations).toEqual(['mobile_app']);

    // Ticking it again removes the exclusion, and an empty list is dropped.
    await user.click(screen.getByRole('checkbox', { name: 'Garage' }));
    expect(latest()).not.toHaveProperty('exclude_areas');
  });

  it('folds a YAML allow-list into exclusions on the first change', async () => {
    const { latest } = renderEditor({ include_areas: ['Bedroom', 'Garage'] });
    const user = userEvent.setup();
    expect(screen.getByRole('checkbox', { name: 'Bedroom' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Kitchen' })).not.toBeChecked();

    await user.click(screen.getByRole('checkbox', { name: 'Garage' })); // untick Garage too
    const config = latest();
    expect(config).not.toHaveProperty('include_areas');
    expect([...(config.exclude_areas ?? [])].sort()).toEqual(
      ['garage', 'hallway', 'kitchen', 'living_room', 'office'].sort(),
    );
    expect(screen.getByRole('checkbox', { name: 'Bedroom' })).toBeChecked();
  });

  it('shows the validation message the card would show', () => {
    renderEditor({ battery_warning: 10, battery_critical: 20 });
    expect(screen.getByRole('alert')).toHaveTextContent(/must not be higher/);
  });
});
