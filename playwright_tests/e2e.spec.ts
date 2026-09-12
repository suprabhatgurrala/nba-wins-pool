import { test, expect } from '@playwright/test';

test.describe('NBA Wins Pool E2E Tests', () => {
  test('should load root and redirect to pools list', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveURL('/pools');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });

  test('should load pools list page directly', async ({ page }) => {
    await page.goto('/pools');

    await expect(page).toHaveURL('/pools');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });

  /**
   * A pool the backend can't find still serves the plain SPA shell with a 200, so
   * og:title — injected only on a database hit — is the assertion that proves the pool
   * was seeded.
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
