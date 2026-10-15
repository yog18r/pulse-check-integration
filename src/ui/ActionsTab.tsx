/**
 * The 🛠️ Actions tab: what to do, and what to buy.
 *
 *   To buy      4 × AAA · 1 × CR2450 · 1 × unknown
 *   Replace     one row per device, "Replace 2 × AA in …"
 *   Charge      one row per rechargeable device, "Charge …"
 */
import type { ActionItem, ActionList } from '../core/actions';
import { UNKNOWN_BATTERY_TYPE } from '../core/actions';
import type { DeviceHealth } from '../core/types';
import { DeviceRow } from './DeviceRow';
import { EmptyState } from './EmptyState';

interface Props {
  actions: ActionList;
  now: Date;
  onOpen?: ((device: DeviceHealth) => void) | undefined;
  onSnooze?: ((device: DeviceHealth, days: number) => void) | undefined;
  onUnsnooze?: ((device: DeviceHealth) => void) | undefined;
}

function Section({
  title,
  items,
  rowProps,
}: {
  title: string;
  items: ActionItem[];
  rowProps: Omit<Props, 'actions'>;
}) {
  if (items.length === 0) return null;
  return (
    <section className="group">
      <h3 className="groupTitle">
        {title}
        <span className="count">{items.length}</span>
      </h3>
      <ul className="rows">
        {items.map((item) => (
          <DeviceRow
            key={item.device.deviceId}
            device={item.device}
            severity={item.severity}
            mode="battery"
            sparkline={false}
            action={item.label}
            {...rowProps}
          />
        ))}
      </ul>
    </section>
  );
}

export function ActionsTab({ actions, ...rowProps }: Props) {
  const { replace, charge, shopping } = actions;

  if (replace.length === 0 && charge.length === 0) {
    return (
      <EmptyState
        emoji="🛠️"
        lead="Nothing to do"
        detail="Every battery is above the warning threshold."
      />
    );
  }

  const hasUnknown = shopping.some((l) => l.batteryType === UNKNOWN_BATTERY_TYPE);

  return (
    <div className="actions">
      {shopping.length > 0 && (
        <p className="tobuy">
          <strong>To buy:</strong>{' '}
          {shopping.map((line, i) => (
            <span key={line.batteryType}>
              {i > 0 && ' · '}
              {String(line.count)} ×{' '}
              {line.batteryType === UNKNOWN_BATTERY_TYPE ? 'unknown' : line.batteryType}
            </span>
          ))}
        </p>
      )}
      {hasUnknown && (
        <p className="hint tobuyhint">
          Set the battery type and count under <code>device_settings</code> (or in the visual
          editor) to make the list exact.
        </p>
      )}
      <Section title="Replace" items={replace} rowProps={rowProps} />
      <Section title="Charge" items={charge} rowProps={rowProps} />
    </div>
  );
}
