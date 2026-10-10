import { test, expect, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

/**
 * Regenerates the docs screenshots. Not an assertion suite: it drives the app into the state each
 * docs section describes and writes a WebP per figure into frontend/src/assets/docs.
 *
 * Run with `make docs-screenshots` against the seeded e2e stack. It uses the seeded `sg` pool (renamed
 * "Demo Pool" on the throwaway stack) for the history/standings shots and builds a brand-new pool for the
 * setup and auction shots.
 */

const OUT_DIR = process.env.DOCS_OUT_DIR || path.resolve(__dirname, '../frontend/src/assets/docs');

const VALUATION = fs.readFileSync(path.join(__dirname, 'fixtures/auction-valuation.json'), 'utf8');

const PARTICIPANTS = ['Alice', 'Ben', 'Cara', 'Dev'];
const SEEDED_POOL = 'sg';
const SEEDED_SEASON = '2025-26';
const NEW_SEASON = '2026-27';
const FEATURED_PARTICIPANT = 'Ejnar';
const DEMO_POOL_NAME = 'Demo Pool';

test.describe.configure({ mode: 'serial' });

let converter: Page;

test.beforeAll(async ({ browser }) => {
  converter = await browser.newPage();
});

test.beforeEach(async ({ context }) => {
  await stubExternalAssets(context);
});

/** Headless Chromium gets ERR_HTTP2_PROTOCOL_ERROR from the NBA CDN, so fetch logos from Node instead. */
async function stubExternalAssets(context: BrowserContext) {
  const cache = new Map<string, { body: Buffer; contentType: string } | null>();
  await context.route(/cdn\.nba\.com/, async (route) => {
    const url = route.request().url();
    if (!cache.has(url)) {
      try {
        const res = await route.fetch();
        cache.set(url, { body: await res.body(), contentType: res.headers()['content-type'] ?? 'image/svg+xml' });
      } catch {
        cache.set(url, null);
      }
    }
    const hit = cache.get(url);
    return hit ? route.fulfill(hit) : route.abort();
  });
}

async function settle(page: Page) {
  await page.evaluate(async () => {
    document.querySelectorAll('img[loading=lazy]').forEach((i) => ((i as HTMLImageElement).loading = 'eager'));
    await Promise.all(
      [...document.images].map((i) =>
        i.complete ? 0 : new Promise((r) => { i.onload = i.onerror = r; setTimeout(r, 8000); }),
      ),
    );
  });
  await page.waitForTimeout(800);
}

/** PNG -> WebP via canvas, so the repo needs no image tooling. */
async function toWebp(png: Buffer): Promise<Buffer> {
  const b64 = await converter.evaluate(async (data) => {
    const bitmap = await createImageBitmap(await (await fetch(`data:image/png;base64,${data}`)).blob());
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0);
    const blob = await canvas.convertToBlob({ type: 'image/webp', quality: 0.82 });
    return await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve((reader.result as string).split(',')[1]);
      reader.readAsDataURL(blob);
    });
  }, png.toString('base64'));
  return Buffer.from(b64, 'base64');
}

type Shot = { fullPage?: boolean; height?: number; top?: number };

/** `height` crops to N CSS px from `top` (default: the top of the page); `fullPage` captures everything below the fold too. */
async function shoot(page: Page, name: string, { fullPage, height, top = 0 }: Shot = {}) {
  const png = await page.screenshot({
    fullPage,
    clip: height ? { x: 0, y: top, width: 393, height } : undefined,
  });
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(path.join(OUT_DIR, `${name}.webp`), await toWebp(png));
}

/** Crops to just below an element, so shots keep working when its content changes height. */
async function shootThrough(page: Page, name: string, locator: ReturnType<Page['locator']>) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  await shoot(page, name, { height: Math.ceil(box!.y + box!.height) + 12 });
}

async function visit(page: Page, url: string) {
  await page.goto(url);
  await page.waitForLoadState('networkidle');
  await settle(page);
}

test('rename the seeded pool', async ({ request }) => {
  const pool = await api(request, 'get', `/pools/slug/${SEEDED_POOL}`);
  await api(request, 'patch', `/pools/${pool.id}`, { name: DEMO_POOL_NAME });
});

test('pool history and participant history', async ({ page }) => {
  await visit(page, `/pools/${SEEDED_POOL}`);
  await expect(page.getByText('Participant Stats')).toBeVisible();
  await shoot(page, 'pool-history', { fullPage: true });

  await visit(page, `/pools/${SEEDED_POOL}/participant/${FEATURED_PARTICIPANT}`);
  await expect(page.getByText('Top Contributing Teams')).toBeVisible();
  await shoot(page, 'participant-history', { fullPage: true });
});

test('season standings and games', async ({ page }) => {
  await visit(page, `/pools/${SEEDED_POOL}/season/${SEEDED_SEASON}`);
  await expect(page.getByText('Wins Race')).toBeVisible();
  await shoot(page, 'season-standings', { fullPage: true });

  await page.locator('button:has(.pi-calendar)').first().click();
  await page.waitForLoadState('networkidle');
  await settle(page);
  await shootThrough(page, 'season-games', page.locator('.p-card').first());

  await page.getByRole('button', { name: 'Menu' }).click();
  await expect(page.getByRole('button', { name: 'Share' })).toBeVisible();
  await page.waitForTimeout(500);
  await shoot(page, 'season-share');
});

test.describe('new pool setup and auction', () => {
  let auctionId = '';

  test('setup checklist', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Create a pool' }).first().click();
    await page.locator('#name').fill(DEMO_POOL_NAME);
    await page.locator('#slug').fill(`demo-${Date.now().toString().slice(-6)}`);
    await page.getByRole('dialog').locator('button[type="submit"]').click();
    await page.waitForURL(/\/season\/\d{4}-\d{2}$/);

    const setup = page.getByTestId('season-setup');
    await expect(setup).toBeVisible();

    await page.getByRole('button', { name: 'Manage Rosters' }).click();
    for (const name of PARTICIPANTS) {
      await page.getByRole('button', { name: 'Add Roster' }).click();
      await page.locator('#roster-form-name').fill(name);
      await page.getByRole('dialog').getByRole('button', { name: 'Create' }).click();
      await expect(page.getByTestId('rosters')).toContainText(name);
    }
    await expect(page.getByRole('dialog')).toHaveCount(1);
    await shootThrough(page, 'setup-manage-rosters', page.getByRole('dialog'));

    await page.keyboard.press('Escape');
    await expect(page.getByTestId('setup-participants')).toContainText(PARTICIPANTS[3]);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await shootThrough(page, 'setup-participants', setup);

    await page.getByRole('button', { name: 'Next' }).click();
    await expect(setup).toContainText('Auction settings');
    await shootThrough(page, 'setup-auction', setup);

    await page.getByRole('button', { name: 'Create' }).click();
    await expect(setup).toContainText('Min Bid Increment');
    await page.getByText('Open auction').click();
    await page.waitForURL(/\/auctions\//);
    auctionId = page.url().split('/auctions/')[1];
  });

  test('auction room', async ({ page, request }) => {
    const teams: { id: string; name: string; abbreviation: string }[] = await api(request, 'get', '/teams');
    const valuation = JSON.parse(VALUATION);
    for (const row of valuation.data) {
      const team = teams.find((t) => t.name === row.team_name);
      row.team_id = team?.id ?? row.team_id;
      row.abbreviation = team?.abbreviation ?? row.abbreviation;
    }
    await page.route('**/valuation-data', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify(valuation) }),
    );
    await api(request, 'patch', `/auctions/${auctionId}`, { max_lots_per_participant: 5 });

    await page.goto(`/auctions/${auctionId}`);
    await page.getByRole('button', { name: 'Menu' }).click();
    await expect(page.getByRole('button', { name: 'Start Auction' })).toBeVisible();
    await page.waitForTimeout(500);
    await settle(page);
    await shoot(page, 'auction-start', { height: 346 });

    await api(request, 'patch', `/auctions/${auctionId}`, { status: 'active' });
    await page.reload();
    await page.getByRole('button', { name: 'Menu' }).click();
    const participate = page.getByRole('button', { name: 'Participate' });
    await expect(participate).toBeVisible();
    await participate.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await settle(page);
    await shoot(page, 'auction-participate', { height: 688 });

    await participate.click();
    await page.getByText('Alice', { exact: true }).first().click();
    await page.keyboard.press('Escape');
    await page.getByRole('row', { name: /BOS/ }).click();
    const nominate = page.getByRole('dialog');
    await expect(nominate).toContainText('Nominate Team');
    await page.waitForTimeout(500);
    await settle(page);
    await shootThrough(page, 'auction-nominate', nominate);
    await page.keyboard.press('Escape');
    await expect(nominate).toHaveCount(0);

    await runAuction(request, auctionId);
    await page.goto(`/auctions/${auctionId}`);
    await expect(page.getByText('New York Knicks').first()).toBeVisible();
    await settle(page);
    await shoot(page, 'auction-room', { height: 695 });

    await page.getByRole('button', { name: 'Menu' }).click();
    await page.getByRole('button', { name: 'Participate' }).click();
    await page.locator('.p-drawer').getByText('Alice', { exact: true }).first().click();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: /^Min:/ }).click();
    const bidInput = page.getByPlaceholder('Enter bid amount');
    await bidInput.fill('25');
    await bidInput.blur();
    const submit = page.getByRole('button', { name: 'Submit Bid' });
    await expect(submit).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    const lotCard = page.locator('.p-card', { has: submit });
    const box = (await lotCard.boundingBox())!;
    await shoot(page, 'auction-bidding', { fullPage: true, top: Math.floor(box.y) - 8, height: Math.ceil(box.height) + 16 });

    await page.getByRole('button', { name: 'Menu' }).click();
    const closeLot = page.getByRole('button', { name: 'Close Lot' });
    await expect(closeLot).toBeVisible();
    await expect(page.getByRole('button', { name: 'Complete Auction' })).toBeVisible();
    await page.waitForTimeout(500);
    await settle(page);
    await shootThrough(page, 'auction-close', closeLot);
  });
});

test('returning to a pool for a new season', async ({ page }) => {
  await visit(page, `/pools/${SEEDED_POOL}`);
  await shootThrough(page, 'returning-create', page.locator('.p-card').first());
  await page.getByRole('button', { name: '+ Create' }).click();
  await page.locator(`a[href$="/pools/${SEEDED_POOL}/season/${NEW_SEASON}"]`).click();
  await page.waitForURL(new RegExp(`/season/${NEW_SEASON}$`));

  const setup = page.getByTestId('season-setup');
  await expect(setup).toBeVisible();
  await expect(page.getByRole('button', { name: 'Import from Season' })).toBeVisible();
  await settle(page);
  await shootThrough(page, 'returning-start', setup);
});

/** Plays a partial draft on an already-started auction: five lots sold, one still open with competing bids. */
async function runAuction(request: APIRequestContext, auctionId: string) {
  const call = (method: 'get' | 'post' | 'patch', url: string, data?: unknown) => api(request, method, url, data);

  const overview = await call('get', `/auctions/${auctionId}/overview`);
  const lots: Record<string, string> = Object.fromEntries(overview.lots.map((l: any) => [l.team.name, l.id]));
  const who: Record<string, string> = Object.fromEntries(overview.participants.map((p: any) => [p.name, p.id]));
  const bid = (team: string, name: string, amount: number) =>
    call('post', '/bids', { lot_id: lots[team], participant_id: who[name], amount });

  const sold: [string, string, number][] = [
    ['Oklahoma City Thunder', 'Ben', 62],
    ['San Antonio Spurs', 'Alice', 55],
    ['Boston Celtics', 'Cara', 41],
    ['Denver Nuggets', 'Dev', 38],
    ['Cleveland Cavaliers', 'Alice', 30],
  ];
  for (const [team, winner, price] of sold) {
    const runnerUp = winner === 'Cara' ? 'Dev' : 'Cara';
    await bid(team, winner, price - 5);
    await bid(team, runnerUp, price - 2);
    await bid(team, winner, price);
    await call('patch', `/auction-lots/${lots[team]}`, { status: 'closed' });
  }

  await bid('New York Knicks', 'Dev', 18);
  await bid('New York Knicks', 'Ben', 21);
}

async function api(request: APIRequestContext, method: 'get' | 'post' | 'patch', url: string, data?: unknown) {
  const res = await request[method](`/api${url}`, { data });
  expect(res.ok(), `${method} ${url}: ${await res.text()}`).toBeTruthy();
  return res.json();
}
