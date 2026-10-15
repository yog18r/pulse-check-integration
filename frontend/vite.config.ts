/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// The integration's manifest.json is the one place the version lives.
import manifest from '../custom_components/pulse_check/manifest.json' with { type: 'json' };

/**
 * Vite does two jobs here:
 *  1. `vite dev`   serves the demo page (index.html) with hot reload.
 *  2. `vite build` produces ONE JavaScript file, pulse-check-card.js, with
 *     React and all CSS bundled in, written straight into the integration's
 *     folder. The integration serves that file and registers it with the
 *     dashboards, so it ships inside the same HACS download.
 */
export default defineConfig({
  plugins: [react()],

  define: {
    // React reads process.env.NODE_ENV at runtime. Home Assistant has no Node
    // environment, so we bake the value in at build time.
    'process.env.NODE_ENV': JSON.stringify('production'),
    // Shown in the browser console banner (see src/index.ts).
    __CARD_VERSION__: JSON.stringify(manifest.version),
  },

  build: {
    // Outside this folder, so Vite needs telling that emptying it is fine.
    // It holds nothing but the bundle.
    outDir: '../custom_components/pulse_check/frontend',
    emptyOutDir: true,
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
      include: ['src/core/**', 'src/card/**'],
    },
  },
});
