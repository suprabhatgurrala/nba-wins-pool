import { test, expect } from '@playwright/test';

[
  { page_path: '/', expected_url: '/sg' },
  { page_path: '/sg', expected_url: '/sg' },
  { page_path: '/kk', expected_url: '/kk' },
].forEach(({ page_path, expected_url }) => {
  test('load page', async ({ page }) => {
    await page.goto(page_path);

    // Expect a title "to contain" a substring.
    await expect(page).toHaveURL(expected_url)
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });
}
);
