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
    
    // Should either load the pool page or redirect to 404 if pool doesn't exist
    await page.waitForLoadState('networkidle');
    
    const url = page.url();
    // Accept either the pool page or 404
    expect(url).toMatch(/\/(pools\/sg|404)/);
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });

  test('should load pool page by slug (kk)', async ({ page }) => {
    await page.goto('/pools/kk');
    
    // Should either load the pool page or redirect to 404 if pool doesn't exist
    await page.waitForLoadState('networkidle');
    
    const url = page.url();
    // Accept either the pool page or 404
    expect(url).toMatch(/\/(pools\/kk|404)/);
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });

  test('should show 404 for invalid routes', async ({ page }) => {
    await page.goto('/invalid-route-that-does-not-exist');
    
    await page.waitForURL('/404');
    await expect(page).toHaveURL('/404');
    await expect(page).toHaveTitle(/NBA Wins Pool/);
  });
});
