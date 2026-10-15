/** Shown when a tab has nothing to complain about. */

interface Props {
  emoji: string;
  lead: string;
  detail: string;
}

export function EmptyState({ emoji, lead, detail }: Props) {
  return (
    <div className="empty" role="status">
      <div className="emoji" aria-hidden="true">
        {emoji}
      </div>
      <div className="lead">{lead}</div>
      <div>{detail}</div>
    </div>
  );
}
