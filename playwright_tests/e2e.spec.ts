import { test, expect } from '@playwright/test';

test.describe('NBA Wins Pool E2E Tests', () => {
  test('should load the landing page', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveURL('/');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
    await expect(page.getByRole('heading', { name: 'NBA Wins Pool' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create a pool' }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Browse pools' })).toBeVisible();
  });

  test('should provide landing page actions', async ({ page }) => {
    await page.goto('/');

    await page.getByRole('button', { name: 'Create a pool' }).first().click();
    await expect(page).toHaveURL('/');
    await expect(page.getByRole('dialog')).toContainText('Create New Pool');

    await page.goto('/');
    await page.getByRole('button', { name: 'Browse pools' }).click();
    await expect(page).toHaveURL('/pools');

    await page.goto('/');
    await page.getByRole('link', { name: 'Learn More' }).click();
    await expect(page).toHaveURL('/docs');
  });

  test('should redirect to the created pool page after submitting from the modal', async ({ page }) => {
    await page.goto('/');

    const uniqueSlug = `redirect-${Date.now().toString().slice(-6)}`;

    await page.getByRole('button', { name: 'Create a pool' }).first().click();
    await expect(page.getByRole('dialog')).toContainText('Create New Pool');

    await page.locator('#name').fill('Test Redirect Pool');
    await page.locator('#slug').fill(uniqueSlug);
    await page.getByRole('dialog').locator('button[type="submit"]').click();

    await page.waitForURL(new RegExp(`\\/pools\\/${uniqueSlug}\\/season\\/\\d{4}-\\d{2}$`));
    await expect(page).toHaveURL(new RegExp(`\\/pools\\/${uniqueSlug}\\/season\\/\\d{4}-\\d{2}$`));
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
    test(`should load pool history page by slug (${slug})`, async ({ page }) => {
      await page.goto(`/pools/${slug}`);

      await page.waitForLoadState('networkidle');

      // /pools/:slug is the pool's history hub — it stays put rather than redirecting
      // into a season, unlike /pools/:slug/season/:season.
      await expect(page).toHaveURL(`/pools/${slug}`);
      await expect(page).toHaveTitle(/NBA Wins Pool/);
      await expect(page.locator('meta[property="og:title"]')).toHaveAttribute(
        'content',
        new RegExp(`^${slug.toUpperCase()} · `),
      );
      await expect(page.getByText('Seasons', { exact: true }).first()).toBeVisible();
    });

    test(`should navigate from pool history to a season's standings (${slug})`, async ({ page }) => {
      await page.goto(`/pools/${slug}`);
      await page.waitForLoadState('networkidle');

      await page.locator(`a[href*="/pools/${slug}/season/"]`).first().click();

      await expect(page).toHaveURL(new RegExp(`/pools/${slug}/season/\\d{4}-\\d{2}$`));
    });
  }

  test('should show 404 for invalid routes', async ({ page }) => {
    await page.goto('/invalid-route-that-does-not-exist');

    await page.waitForURL('/404');
    await expect(page).toHaveURL('/404');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });
});
