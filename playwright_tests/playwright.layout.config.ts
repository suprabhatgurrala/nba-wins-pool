import { defineConfig, devices } from '@playwright/test';

/** One Chromium project per device, together covering the narrow edge of each breakpoint range. */
export default defineConfig({
  testDir: '.',
  testMatch: 'layout.spec.ts',
  globalSetup: './layout.setup.ts',
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}-{projectName}{ext}',
  fullyParallel: true,
  workers: '100%',
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: 'line',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8000',
    browserName: 'chromium',
    trace: 'retain-on-failure',
    reducedMotion: 'reduce',
    timezoneId: 'UTC',
    locale: 'en-US',
  },
  projects: [
    { name: 'iphone-se', use: { ...devices['iPhone SE'], browserName: 'chromium' } },
    { name: 'galaxy-s8', use: { ...devices['Galaxy S8'], browserName: 'chromium' } },
    { name: 'iphone', use: { ...devices['iPhone 15'], browserName: 'chromium' } },
    { name: 'galaxy-s5-landscape', use: { ...devices['Galaxy S5 landscape'], browserName: 'chromium' } },
    { name: 'galaxy-s9-landscape', use: { ...devices['Galaxy S9+ landscape'], browserName: 'chromium' } },
    { name: 'ipad-mini', use: { ...devices['iPad Mini'], browserName: 'chromium' } },
    { name: 'ipad-mini-landscape', use: { ...devices['iPad Mini landscape'], browserName: 'chromium' } },
    { name: 'ipad-pro-landscape', use: { ...devices['iPad Pro 11 landscape'], browserName: 'chromium' } },
    {
      name: 'galaxy-tab-s7-landscape',
      use: {
        ...devices['Galaxy Tab S4 landscape'],
        browserName: 'chromium',
        viewport: { width: 1280, height: 712 },
        screen: { width: 1280, height: 800 },
        deviceScaleFactor: 2.1875,
      },
    },
    { name: 'laptop-1280', use: { ...devices['Desktop Chrome'], browserName: 'chromium' } },
    {
      name: 'macbook-13',
      use: {
        ...devices['Desktop Chrome HiDPI'],
        browserName: 'chromium',
        viewport: { width: 1470, height: 832 },
        screen: { width: 1470, height: 956 },
        deviceScaleFactor: 2,
      },
    },
    {
      name: 'laptop-1536',
      use: {
        ...devices['Desktop Chrome'],
        browserName: 'chromium',
        viewport: { width: 1536, height: 730 },
        screen: { width: 1536, height: 864 },
        deviceScaleFactor: 1.25,
      },
    },
    {
      name: 'monitor-4k-27',
      use: {
        ...devices['Desktop Chrome'],
        browserName: 'chromium',
        viewport: { width: 2560, height: 1305 },
        screen: { width: 2560, height: 1440 },
        deviceScaleFactor: 1.5,
      },
    },
  ],
});
