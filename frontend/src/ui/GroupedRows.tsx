/**
 * A row list, optionally split into titled groups (by area, integration
 * or device type). With `group_by: none` it is just a RowList; otherwise
 * each group gets a heading and its own "show more" cap.
 */
import type { ReactNode } from 'react';
import { groupDevices, type GroupBy } from '../core/grouping';
import type { DeviceHealth } from '../core/types';
import { useT } from './i18n';
import { integrationLabel } from './labels';
import { RowList } from './RowList';

interface Props {
  items: DeviceHealth[];
  groupBy: GroupBy;
  maxRows: number | 'all';
  renderRow: (device: DeviceHealth) => ReactNode;
  resetKey: string;
}

export function GroupedRows({ items, groupBy, maxRows, renderRow, resetKey }: Props) {
  const t = useT();
  if (groupBy === 'none') {
    return <RowList items={items} maxRows={maxRows} renderRow={renderRow} resetKey={resetKey} />;
  }
  const groups = groupDevices(
    items,
    groupBy,
    { integration: (platform) => integrationLabel(platform, t) },
    t,
  );
  return (
    <>
      {groups.map((group) => (
        <section key={group.key} className="group">
          <h3 className="groupTitle">
            {group.label}
            <span className="count">{group.items.length}</span>
          </h3>
          <RowList
            items={group.items}
            maxRows={maxRows}
            renderRow={renderRow}
            resetKey={`${resetKey}:${group.key}`}
          />
        </section>
      ))}
    </>
  );
}
