/**
 * The 🛒 Shopping tab: batteries to buy, grouped by type.
 */
import type { ResolvedConfig } from '../card/config';
import type { ShoppingGroup } from '../core/shopping';
import { batterySeverity } from '../core/thresholds';
import type { DeviceHealth } from '../core/types';
import { DeviceRow } from './DeviceRow';
import { EmptyState } from './EmptyState';

interface Props {
  groups: ShoppingGroup[];
  config: ResolvedConfig;
  now: Date;
  onOpen?: ((device: DeviceHealth) => void) | undefined;
}

export function ShoppingTab({ groups, config, now, onOpen }: Props) {
  if (groups.length === 0) {
    return (
      <EmptyState
        emoji="🛒"
        lead="Nothing to buy"
        detail="Every battery is above the warning threshold."
      />
    );
  }

  return (
    <div className="shopping">
      {groups.map((group) => (
        <section key={group.batteryType} className="group">
          <h3 className="groupTitle">
            {group.batteryType}
            <span className="count">{group.devices.length}</span>
          </h3>
          {group.isUnknown && (
            <p className="hint">
              Set <code>battery_type</code> in <code>device_overrides</code> to group these.
            </p>
          )}
          <ul className="rows">
            {group.devices.map((d) => (
              <DeviceRow
                key={d.deviceId}
                device={d}
                severity={batterySeverity(d.battery, config)}
                mode="battery"
                now={now}
                onOpen={onOpen}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
