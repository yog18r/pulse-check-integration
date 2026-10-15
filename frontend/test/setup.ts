/**
 * Shared Vitest setup. Adds Testing Library's DOM matchers
 * (toBeInTheDocument, toHaveTextContent, ...) to `expect`.
 * Harmless in node-environment tests; they simply never use them.
 */
import '@testing-library/jest-dom/vitest';
