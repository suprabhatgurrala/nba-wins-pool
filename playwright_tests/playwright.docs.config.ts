import { defineConfig, devices } from '@playwright/test';

/**
 * Regenerates the screenshots embedded in the docs pages (frontend/src/assets/docs).
 * Run it with `make docs-screenshots`; the default config skips docs-screenshots.spec.ts.
 */
export default defineConfig({
  testDir: '.',
  testMatch: 'docs-screenshots.spec.ts',
  workers: 1,
  timeout: 180_000,
  reporter: 'line',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8000',
    ...devices['iPhone 15'],
    viewport: { width: 393, height: 852 },
    deviceScaleFactor: 2,
  },
});
