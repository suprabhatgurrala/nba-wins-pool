import { test, expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { LIVE_POOL_SLUG, LIVE_SEASON, LIVE_TEAM } from './layout.setup';
import { stubExternalAssets } from './support';

/**
 * Responsive layout checks against the seeded e2e stack, run once per device project in playwright.layout.config.ts.
 *
 * Each screen fails on anything that overhangs at the device's viewport: the page scrolling sideways, an element
 * poking past the viewport, or content spilling out of the box that contains it. It is then compared full-page
 * against its committed baseline for that device; refresh them with `make layout-screenshots` after an intended UI
 * change.
 *
 * Mark an element `data-layout-ignore` to exempt it and its children from the check, e.g. a badge that overlaps its
 * parent's edge on purpose or a carousel that keeps slides off to the side.
 */

const SEEDED_POOL = 'sg';
const SEEDED_SEASON = '2025-26';
const SEEDED_PARTICIPANT = 'Ejnar';

const IGNORE_SELECTOR = '[data-layout-ignore], #__vue-devtools-container__, [class^="vue-devtools"]';

type Screen = {
  name: string;
  path: (request: APIRequestContext) => Promise<string>;
  ready: (page: Page) => Promise<void>;
  /** Long static pages are checked but not screenshotted, to keep the committed baselines small. */
  checkOnly?: boolean;
  /** Parts that change from run to run (clocks, times of day), covered in the screenshot. */
  mask?: (page: Page) => Locator[];
};

const SCREENS: Screen[] = [
  {
    name: 'home',
    path: async () => '/',
    ready: (page) => expect(page.getByRole('heading', { name: 'NBA Wins Pool' })).toBeVisible(),
  },
  {
    name: 'create-pool-dialog',
    path: async () => '/',
    ready: async (page) => {
      await page.getByRole('button', { name: 'Create a pool' }).first().click();
      await expect(page.getByRole('dialog')).toContainText('Create New Pool');
    },
  },
  {
    name: 'pools',
    path: async () => '/pools',
    ready: (page) => expect(page.locator(`a[href="/pools/${SEEDED_POOL}"]`).first()).toBeVisible(),
  },
  {
    name: 'docs',
    path: async () => '/docs',
    ready: (page) => expect(page.getByRole('heading', { name: 'Docs', exact: true })).toBeVisible(),
  },
  ...['pools', 'app', 'auction', 'auction-strategy', 'simulation'].map((article) => ({
    name: `docs-${article}`,
    path: async () => `/docs/${article}`,
    ready: (page: Page) => expect(page.locator('h1').first()).toBeVisible(),
    checkOnly: true,
  })),
  {
    name: 'pool',
    path: async () => `/pools/${SEEDED_POOL}`,
    ready: (page) => expect(page.getByText('Participant Stats')).toBeVisible(),
  },
  {
    name: 'season-standings',
    path: async () => `/pools/${SEEDED_POOL}/season/${SEEDED_SEASON}`,
    ready: (page) =>
      expect(page.locator('.p-card', { hasText: 'Wins Race' }).locator('svg text').first()).toBeVisible({
        timeout: 15_000,
      }),
  },
  {
    name: 'season-games',
    path: async () => `/pools/${SEEDED_POOL}/season/${SEEDED_SEASON}`,
    ready: async (page) => {
      await expect(page.getByText('Wins Race')).toBeVisible();
      await page.locator('button:has(.pi-calendar)').first().click();
    },
  },
  {
    name: 'participant',
    path: async () => `/pools/${SEEDED_POOL}/participant/${SEEDED_PARTICIPANT}`,
    ready: (page) => expect(page.getByText('Top Contributing Teams')).toBeVisible(),
  },
  {
    name: 'auction',
    path: async (request) => `/auctions/${await auctionId(request, SEEDED_POOL, SEEDED_SEASON)}`,
    ready: (page) => expect(page.getByText('Auction completed')).toBeVisible(),
  },
  {
    name: 'auction-live',
    path: async (request) => `/auctions/${await auctionId(request, LIVE_POOL_SLUG, LIVE_SEASON)}`,
    ready: async (page) => {
      await page.getByRole('button', { name: 'Menu' }).click();
      await page.getByRole('button', { name: 'Participate' }).click();
      await page.getByRole('dialog').getByRole('button', { name: /Alice/ }).click();
      await page.keyboard.press('Escape');
      await expect(page.getByPlaceholder('Enter bid amount')).toBeVisible();
      await expect(page.getByText(LIVE_TEAM).first()).toBeVisible();
      await page.addStyleTag({ content: '.p-toast { display: none !important; }' });
    },
    mask: (page) => [page.getByText(/Time since last bid/), page.locator('.p-card', { hasText: 'Activity' })],
  },
  {
    name: 'not-found',
    path: async () => '/404',
    ready: (page) => expect(page.getByText(/not found/i).first()).toBeVisible(),
  },
];

test.beforeEach(async ({ context }) => {
  await stubExternalAssets(context);
});

for (const screen of SCREENS) {
  test(screen.name, async ({ page, request }) => {
    const teamNames = await allTeamNames(request);
    await open(page, screen, request);

    const failures = (await findOverhangs(page, teamNames)).map(describeOverhang);
    expect(failures, `Layout overhangs on ${screen.name}:\n${failures.join('\n')}`).toEqual([]);

    if (screen.checkOnly) return;
    await growViewportToPage(page);
    await expect(page).toHaveScreenshot(`${screen.name}.png`, { maxDiffPixelRatio: 0.01, mask: screen.mask?.(page) });
  });
}

async function open(page: Page, screen: Screen, request: APIRequestContext) {
  const apiIdle = trackApiCalls(page);
  await page.goto(await screen.path(request));
  await screen.ready(page);
  await apiIdle();
  await page.evaluate(async () => {
    document.querySelectorAll('img[loading=lazy]').forEach((i) => ((i as HTMLImageElement).loading = 'eager'));
    await Promise.all(
      [...document.images].map((i) =>
        i.complete ? 0 : new Promise((r) => { i.onload = i.onerror = r; setTimeout(r, 8000); }),
      ),
    );
    await document.fonts.ready;
  });
  await page.waitForTimeout(800);
}

/**
 * Returns a function that resolves once no fetch/XHR has been in flight for half a second. A ready check only proves
 * one part of the screen rendered; under load the rest of its data can still be arriving. Server-sent event streams
 * never finish, so they aren't counted.
 */
function trackApiCalls(page: Page): () => Promise<void> {
  let inflight = 0;
  let lastChange = Date.now();
  const isApi = (r: { resourceType(): string }) => ['fetch', 'xhr'].includes(r.resourceType());
  page.on('request', (r) => {
    if (isApi(r)) (inflight++, (lastChange = Date.now()));
  });
  const done = (r: { resourceType(): string }) => {
    if (isApi(r)) (inflight--, (lastChange = Date.now()));
  };
  page.on('requestfinished', done);
  page.on('requestfailed', done);
  return async () => {
    const deadline = Date.now() + 15_000;
    while (Date.now() < deadline && (inflight > 0 || Date.now() - lastChange < 500)) await page.waitForTimeout(100);
  };
}

/**
 * Makes the viewport as tall as the page so a plain screenshot captures all of it. A `fullPage` capture resizes the
 * page mid-capture under mobile emulation, which makes charts redraw and sometimes get caught blank.
 */
async function growViewportToPage(page: Page) {
  const { width } = page.viewportSize()!;
  for (let i = 0; i < 5; i++) {
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    if (height === page.viewportSize()!.height) return;
    await page.setViewportSize({ width, height });
    await waitForLayout(page);
    await page.waitForTimeout(400);
  }
}

async function waitForLayout(page: Page) {
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 100)))),
  );
}

type Overhang = { element: string; kind: 'page' | 'viewport' | 'side' | 'bottom' | 'clipped' | 'team-ellipsis' | 'scrolls'; px: number };

/**
 * Lists what overhangs at the current viewport. Only the innermost offender of each nested chain is reported, since
 * that is the element whose size forces its ancestors out. A team name cut short with an ellipsis also counts: it
 * should switch to the team's abbreviation instead.
 */
async function findOverhangs(page: Page, teamNames: string[]): Promise<Overhang[]> {
  return page.evaluate(([IGNORE, TEAM_NAMES]) => {
    const TOLERANCE = 1;
    const viewportWidth = document.documentElement.clientWidth;
    const found: { el: Element; kind: Exclude<Overhang['kind'], 'page'>; px: number }[] = [];

    const isHidden = (style: CSSStyleDeclaration) =>
      style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0' || style.clip !== 'auto';

    const isBox = (style: CSSStyleDeclaration) =>
      ['top', 'right', 'bottom', 'left'].some((s) => parseFloat(style.getPropertyValue(`border-${s}-width`)) > 0) ||
      !/rgba\(0, 0, 0, 0\)|transparent/.test(style.backgroundColor) ||
      style.backgroundImage !== 'none' ||
      style.boxShadow !== 'none';

    type Clip = { left: number; right: number };
    const walk = (el: Element, clip: Clip, cutter: Clip | null) => {
      if (el.matches(IGNORE)) return;
      const style = getComputedStyle(el);
      if (isHidden(style)) return;

      const rect = el.getBoundingClientRect();
      const fixed = style.position === 'fixed';
      const ownClip = fixed ? { left: 0, right: viewportWidth } : clip;
      const ownCutter = fixed ? null : cutter;
      const left = Math.max(rect.left, ownClip.left);
      const right = Math.min(rect.right, ownClip.right);
      const visible = rect.width > 0 && rect.height > 0 && right > left;

      if (visible && (right > viewportWidth + TOLERANCE || left < -TOLERANCE)) {
        found.push({ el, kind: 'viewport', px: Math.round(Math.max(right - viewportWidth, -left)) });
      }

      const clipsX = style.overflowX !== 'visible';
      const clipsY = style.overflowY !== 'visible';
      if (visible && isBox(style) && !(el instanceof HTMLImageElement) && !(el instanceof SVGElement)) {
        const spillX = clipsX ? 0 : el.scrollWidth - el.clientWidth;
        const spillY = clipsY ? 0 : el.scrollHeight - el.clientHeight;
        if (el.clientWidth > 0 && spillX > TOLERANCE) found.push({ el, kind: 'side', px: spillX });
        if (el.clientHeight > 0 && spillY > TOLERANCE) found.push({ el, kind: 'bottom', px: spillY });
      }

      const isGraphic = el instanceof SVGElement && !(el instanceof SVGTextElement);
      if (visible && ownCutter && !isGraphic) {
        const cut = Math.max(rect.right - ownCutter.right, ownCutter.left - rect.left);
        if (cut > TOLERANCE) found.push({ el, kind: 'clipped', px: Math.round(cut) });
      }

      const cutsOff = style.overflowX === 'hidden' || style.overflowX === 'clip';
      const hasText = [...el.childNodes].some((n) => n.nodeType === Node.TEXT_NODE && n.textContent!.trim());
      if (visible && cutsOff && hasText && style.textOverflow !== 'ellipsis' && el.clientWidth > 0) {
        const cut = el.scrollWidth - el.clientWidth;
        if (cut > TOLERANCE) found.push({ el, kind: 'clipped', px: cut });
      }

      const childClip = clipsX
        ? { left: Math.max(ownClip.left, rect.left), right: Math.min(ownClip.right, rect.right) }
        : ownClip;
      const scrolls = style.overflowX === 'auto' || style.overflowX === 'scroll';
      if (visible && scrolls && !el.closest('[data-scroll-x]') && el.scrollWidth - el.clientWidth > TOLERANCE) {
        found.push({ el, kind: 'scrolls', px: el.scrollWidth - el.clientWidth });
      }
      const ellipsis = style.textOverflow === 'ellipsis';
      if (visible && cutsOff && ellipsis && el.scrollWidth - el.clientWidth > 0) {
        const text = el.textContent ?? '';
        if (TEAM_NAMES.some((name) => text.includes(name))) {
          found.push({ el, kind: 'team-ellipsis', px: el.scrollWidth - el.clientWidth });
        }
      }
      const childCutter = cutsOff && !ellipsis ? { left: rect.left, right: rect.right } : cutsOff || scrolls ? null : ownCutter;
      for (const child of el.children) walk(child, childClip, childCutter);
    };

    walk(document.body, { left: -Infinity, right: Infinity }, null);

    const describe = (el: Element) => {
      const id = el.id ? `#${el.id}` : '';
      const classes = [...el.classList].slice(0, 4).map((c) => `.${c}`).join('');
      const text = (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40);
      return `<${el.tagName.toLowerCase()}${id}${classes}>${text ? ` "${text}"` : ''}`;
    };

    const pageScroll = document.documentElement.scrollWidth - viewportWidth;
    return [
      ...(pageScroll > TOLERANCE ? [{ element: 'the page', kind: 'page' as const, px: pageScroll }] : []),
      ...found
        .filter(({ el, kind }) => !found.some((o) => o.el !== el && o.kind === kind && el.contains(o.el)))
        .map(({ el, kind, px }) => ({ element: describe(el), kind, px })),
    ];
  }, [IGNORE_SELECTOR, teamNames] as const);
}

function describeOverhang({ element, kind, px }: Overhang): string {
  const what = {
    page: 'the page scrolls horizontally',
    viewport: `${element} overhangs the viewport`,
    side: `content spills out the side of ${element}`,
    bottom: `content spills out the bottom of ${element}`,
    clipped: `content is cut off at the side of ${element}`,
    scrolls: `${element} scrolls sideways (mark it data-scroll-x if that's intended)`,
    'team-ellipsis': `team name is truncated with an ellipsis (use the abbreviation) in ${element}`,
  }[kind];
  return `${what} by ${px}px`;
}

let teamNamesCache: string[] | undefined;

async function allTeamNames(request: APIRequestContext): Promise<string[]> {
  teamNamesCache ??= ((await (await request.get('/api/teams')).json()) as { name: string }[]).map((t) => t.name);
  return teamNamesCache;
}

async function auctionId(request: APIRequestContext, poolSlug: string, season: string): Promise<string> {
  const pool = await (await request.get(`/api/pools/slug/${poolSlug}`)).json();
  const auctions = await (await request.get(`/api/auctions?pool_id=${pool.id}&season=${season}`)).json();
  return auctions[0].id;
}
