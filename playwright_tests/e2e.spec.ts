import { test, expect } from '@playwright/test';

test.describe('NBA Wins Pool E2E Tests', () => {
  test('should load root and redirect to pools list', async ({ page }) => {
    await page.goto('/');

    // Should redirect to /pools
    await expect(page).toHaveURL('/pools');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });

  test('should load pools list page directly', async ({ page }) => {
    await page.goto('/pools');

    await expect(page).toHaveURL('/pools');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });

  test('should load pool page by slug (sg)', async ({ page }) => {
    await page.goto('/pools/sg');

    await page.waitForLoadState('networkidle');

    // The SPA resolves the pool's latest season and rewrites the URL to it.
    await expect(page).toHaveURL(/\/pools\/sg\/season\/\d{4}-\d{2}$/);
    await expect(page).toHaveTitle(/NBA Wins Pool/);
    // The backend looks the pool up in the database and injects pool-specific OG
    // tags into the SPA shell, so this also asserts the pool was seeded.
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute('content', /^SG · /);
  });

  test('should load pool page by slug (kk)', async ({ page }) => {
    await page.goto('/pools/kk');

    await page.waitForLoadState('networkidle');

    await expect(page).toHaveURL(/\/pools\/kk\/season\/\d{4}-\d{2}$/);
    await expect(page).toHaveTitle(/NBA Wins Pool/);
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute('content', /^KK · /);
  });

  test('should show 404 for invalid routes', async ({ page }) => {
    await page.goto('/invalid-route-that-does-not-exist');

    await page.waitForURL('/404');
    await expect(page).toHaveURL('/404');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });
});
