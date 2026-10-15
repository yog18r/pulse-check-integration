/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * Vite does two jobs here:
 *  1. `vite dev`   serves the demo page (index.html) with hot reload.
 *  2. `vite build` produces ONE JavaScript file, dist/pulse-check-card.js,
 *     with React and all CSS bundled in. That single file is what a user
 *     copies into Home Assistant's /config/www/ folder.
 */
export default defineConfig({
  plugins: [react()],

  // React reads process.env.NODE_ENV at runtime. Home Assistant has no Node
  // environment, so we bake the value in at build time.
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },

  build: {
    // "Library mode": bundle an entry module instead of an HTML page.
    lib: {
      entry: 'src/index.ts',
      formats: ['es'],
      fileName: () => 'pulse-check-card.js',
    },
    rollupOptions: {
      output: {
        // Never split into chunks. HA loads the card as a single resource URL.
        codeSplitting: false,
        // Library builds keep whitespace by default (nice for consumers who
        // bundle again). Nobody re-bundles a HA card, so squeeze it fully.
        minify: true,
      },
    },
    // CSS is imported with `?inline` and injected into the shadow root,
    // so there is no separate stylesheet to emit.
    cssCodeSplit: false,
    sourcemap: false,
    target: 'es2022',
  },

  test: {
    environment: 'node',
    passWithNoTests: true,
    include: ['test/**/*.test.{ts,tsx}', 'src/**/*.test.{ts,tsx}'],
    // Component tests opt into jsdom per file with `// @vitest-environment jsdom`.
    setupFiles: ['test/setup.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/core/**', 'src/enhancers/**', 'src/card/config.ts'],
    },
  },
});
