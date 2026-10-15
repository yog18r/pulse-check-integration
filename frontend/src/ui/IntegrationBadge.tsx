/**
 * A small pill showing which integration a device comes from.
 *
 * React note: this is a "function component". It receives `props` (an
 * object of inputs, typed below) and returns JSX, the HTML-like syntax that
 * compiles to `React.createElement` calls. Components are the building
 * blocks you compose into a UI.
 */
import { integrationLabel } from './labels';

interface Props {
  platform: string;
}

export function IntegrationBadge({ platform }: Props) {
  return (
    <span className="badge" title={`Integration: ${platform}`}>
      {integrationLabel(platform)}
    </span>
  );
}
