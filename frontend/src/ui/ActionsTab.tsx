/**
 * The 🛠️ Actions tab: what to do, and what to buy.
 *
 *   To buy      4 × AAA · 1 × CR2450 · 1 × unknown
 *   Replace     one row per device, "Replace 2 × AA in …"
 *   Charge      one row per rechargeable device, "Charge …"
 *
 * The list comes from the integration; each item names a device by id,
 * which is looked up in the snapshot's device list for the row.
 */
import {
  actionLabel,
  UNKNOWN_BATTERY_TYPE,
  type ActionItem,
  type ActionKind,
  type ActionList,
} from '../core/actions';
import { batteryTypeLabel } from '../core/batteryTypes';
import type { DeviceHealth } from '../core/types';
import { DeviceRow } from './DeviceRow';
import { EmptyState } from './EmptyState';
import { useT } from './i18n';

interface Props {
  actions: ActionList;
  devices: ReadonlyMap<string, DeviceHealth>;
  now: Date;
  onOpen?: ((device: DeviceHealth) => void) | undefined;
  onSnooze?: ((device: DeviceHealth, days: number) => void) | undefined;
  onUnsnooze?: ((device: DeviceHealth) => void) | undefined;
  /** "I did it": records a replacement or charge with the integration. */
  onDone?: ((device: DeviceHealth, kind: ActionKind) => void) | undefined;
}

function Section({
  title,
  items,
  devices,
  onDone,
  rowProps,
}: {
  title: string;
  items: ActionItem[];
  devices: ReadonlyMap<string, DeviceHealth>;
  onDone: Props['onDone'];
  rowProps: Omit<Props, 'actions' | 'devices' | 'onDone'>;
}) {
  const t = useT();
  const rows = items.flatMap((item) => {
    const device = devices.get(item.deviceId);
    return device ? [{ item, device }] : [];
  });
  if (rows.length === 0) return null;
  return (
    <section className="group">
      <h3 className="groupTitle">
        {title}
        <span className="count">{rows.length}</span>
      </h3>
      <ul className="rows">
        {rows.map(({ item, device }) => (
          <DeviceRow
            key={device.deviceId}
            device={device}
            severity={item.severity}
            mode="battery"
            sparkline={false}
            action={actionLabel(item, t)}
            onDone={
              onDone
                ? () => {
                    onDone(device, item.kind);
                  }
                : undefined
            }
            {...rowProps}
          />
        ))}
      </ul>
    </section>
  );
}

export function ActionsTab({ actions, devices, onDone, ...rowProps }: Props) {
  const t = useT();
  const { replace, charge, shopping } = actions;

  if (replace.length === 0 && charge.length === 0) {
    return (
      <EmptyState
        emoji="🛠️"
        lead={t.t('empty.actions')}
        detail={t.t('empty.batteries_ok_detail')}
      />
    );
  }

  const hasUnknown = shopping.some((l) => l.batteryType === UNKNOWN_BATTERY_TYPE);

  return (
    <div className="actions">
      {shopping.length > 0 && (
        <p className="tobuy">
          <strong>{t.t('actions.to_buy')}</strong>{' '}
          {shopping.map((line, i) => (
            <span key={line.batteryType}>
              {i > 0 && ' · '}
              {String(line.count)} ×{' '}
              {line.batteryType === UNKNOWN_BATTERY_TYPE
                ? t.t('actions.unknown_type')
                : batteryTypeLabel(line.batteryType, t)}
            </span>
          ))}
        </p>
      )}
      {hasUnknown && <p className="hint tobuyhint">{t.t('actions.hint')}</p>}
      <Section
        title={t.t('actions.replace')}
        items={replace}
        devices={devices}
        onDone={onDone}
        rowProps={rowProps}
      />
      <Section
        title={t.t('actions.charge')}
        items={charge}
        devices={devices}
        onDone={onDone}
        rowProps={rowProps}
      />
    </div>
  );
}
