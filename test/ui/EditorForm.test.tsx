// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CardConfig } from '../../src/card/config';
import type { HassBox } from '../../src/core/types';
import { EditorForm } from '../../src/ui/EditorForm';
import { fakeHass, SNAPSHOT_PAYLOAD, type FakeHassOptions } from '../fixtures/snapshot';

afterEach(cleanup);

/**
 * Home Assistant owns the config and re-renders the editor with every
 * `config-changed`. This little harness does the same, so typing several
 * characters builds on the previous keystroke instead of the stale prop.
 */
function Harness({
  initial,
  onEmit,
  hassBox,
}: {
  initial: CardConfig;
  onEmit: (c: CardConfig) => void;
  hassBox: HassBox;
}) {
  const [config, setConfig] = useState(initial);
  return (
    <EditorForm
      config={config}
      hass={hassBox.latest}
      hassBox={hassBox}
      onChange={(next) => {
        setConfig(next);
        onEmit(next);
      }}
    />
  );
}

function renderEditor(
  initial: CardConfig = { type: 'custom:pulse-check-card' },
  options: FakeHassOptions = {},
) {
  const fake = fakeHass(options);
  const hassBox: HassBox = { latest: fake.hass };
  const onEmit = vi.fn();
  render(<Harness initial={initial} onEmit={onEmit} hassBox={hassBox} />);
  const latest = () => onEmit.mock.lastCall?.[0] as CardConfig;
  return { ...fake, onEmit, latest };
}

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

    await user.selectOptions(screen.getByLabelText('Battery order'), 'replace_soon');
    expect(latest().battery_sort).toBe('replace_soon');

    await user.click(screen.getByRole('checkbox', { name: 'Show all rows' }));
    expect(latest().max_rows).toBe('all');

    await user.click(screen.getByRole('checkbox', { name: 'Batteries tab: problems only' }));
    expect(latest().problems_only).toBe(true);
  });

  it('shows the validation message the card would show', () => {
    renderEditor({ default_tab: 'actions', show_tabs: ['batteries'] });
    expect(screen.getByRole('alert')).toHaveTextContent(/not in "show_tabs"/);
  });

  it('does not offer thresholds or filters: those belong to the integration', async () => {
    renderEditor();
    await screen.findByText(/Thresholds, quiet rules, filters and notifications are set/);
    expect(screen.queryByLabelText(/Battery warning/)).not.toBeInTheDocument();
    expect(screen.queryByText('Areas')).not.toBeInTheDocument();
  });
});

describe('EditorForm: per-device settings', () => {
  it('picks a device and saves each change through set_device_settings', async () => {
    const { callService } = renderEditor();
    const user = userEvent.setup();
    await screen.findByPlaceholderText('Search devices to edit…');

    const picker = screen.getByRole('combobox', { name: 'Device' });
    await user.click(picker);
    await user.type(picker, 'kitchen');
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(1);
    await user.keyboard('{Enter}');

    // The area select is pre-filled from the registry.
    expect(screen.getByLabelText('Area')).toHaveValue('Kitchen');

    await user.selectOptions(screen.getByLabelText('Battery type'), 'AA');
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'dev_shelly_ht',
      battery_type: 'AA',
    });

    await user.type(screen.getByLabelText('Battery count'), '2');
    await user.tab(); // leaving the field saves it
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'dev_shelly_ht',
      battery_count: 2,
    });

    await user.click(screen.getByLabelText('Rechargeable'));
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'dev_shelly_ht',
      rechargeable: true,
    });

    await user.selectOptions(screen.getByLabelText('Area'), 'Garage');
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'dev_shelly_ht',
      area: 'Garage',
    });
    // Back to the registry's own area clears the override.
    await user.selectOptions(screen.getByLabelText('Area'), 'Kitchen');
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'dev_shelly_ht',
      area: '',
    });

    await user.type(screen.getByLabelText('Trend days'), '3');
    await user.tab();
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'dev_shelly_ht',
      sparkline_days: 3,
    });

    await user.selectOptions(screen.getByLabelText('Notification policy'), 'weekly');
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'dev_shelly_ht',
      notify_policy: 'weekly',
    });

    await user.type(screen.getByLabelText('Display name'), 'Kitchen climate{Enter}');
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'dev_shelly_ht',
      name: 'Kitchen climate',
    });
  });

  it('shows the settings the integration already has, including device-less batteries', async () => {
    const { callService } = renderEditor(
      { type: 'custom:pulse-check-card' },
      {
        payload: {
          ...SNAPSHOT_PAYLOAD,
          device_settings: {
            dev_zha_temp: { battery_type: 'CR2450', battery_count: 2, notify_policy: 'none' },
            'entity:sensor.remote_battery_template': { name: 'TV Remote' },
          },
        },
      },
    );
    const user = userEvent.setup();
    const chips = await screen.findByLabelText('Devices with settings');
    await user.click(within(chips).getByRole('button', { name: 'Bedroom Temp & Humidity' }));
    expect(screen.getByLabelText('Battery type')).toHaveValue('CR2450');
    expect(screen.getByLabelText('Battery count')).toHaveValue(2);
    expect(screen.getByLabelText('Notification policy')).toHaveValue('none');

    await user.click(within(chips).getByRole('button', { name: 'TV Remote Battery' }));
    expect(screen.getByLabelText('Display name')).toHaveValue('TV Remote');
    await user.click(screen.getByLabelText('Rechargeable'));
    expect(callService).toHaveBeenLastCalledWith('pulse_check', 'set_device_settings', {
      device_id: 'entity:sensor.remote_battery_template',
      rechargeable: true,
    });
  });

  it('says so when the integration is missing', async () => {
    renderEditor(
      { type: 'custom:pulse-check-card' },
      { reject: { code: 'not_loaded', message: 'Pulse Check is not set up' } },
    );
    expect(await screen.findByText(/integration is not set up/)).toBeInTheDocument();
  });
});
