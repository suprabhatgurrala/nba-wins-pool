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

  /**
   * Asserts a seeded pool renders end to end.
   *
   * The SPA resolves the pool's latest season and rewrites the URL to it, and the
   * backend looks the slug up in the database to inject pool-specific OG tags into the
   * shell it serves. A pool missing from the database gets the plain SPA shell instead,
   * so the og:title assertion is what proves the seed reached the database — it was an
   * empty <title> on these two pages that the missing E2E database first showed up as.
   */
  for (const slug of ['sg', 'kk']) {
    test(`should load pool page by slug (${slug})`, async ({ page }) => {
      await page.goto(`/pools/${slug}`);

      await page.waitForLoadState('networkidle');

      await expect(page).toHaveURL(new RegExp(`/pools/${slug}/season/\\d{4}-\\d{2}$`));
      await expect(page).toHaveTitle(/NBA Wins Pool/);
      await expect(page.locator('meta[property="og:title"]')).toHaveAttribute(
        'content',
        new RegExp(`^${slug.toUpperCase()} · `),
      );
    });
  }

  test('should show 404 for invalid routes', async ({ page }) => {
    await page.goto('/invalid-route-that-does-not-exist');

    await page.waitForURL('/404');
    await expect(page).toHaveURL('/404');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });
});
