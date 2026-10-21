import type { BrowserContext } from '@playwright/test';

const cache = new Map<string, { body: Buffer; contentType: string } | null>();

/** Fetches NBA CDN logos from Node, since headless Chromium gets ERR_HTTP2_PROTOCOL_ERROR from it. */
export async function stubExternalAssets(context: BrowserContext) {
  await context.route(/cdn\.nba\.com/, async (route) => {
    const url = route.request().url();
    if (!cache.has(url)) {
      try {
        const res = await context.request.get(url, { timeout: 10_000 });
        if (!res.ok()) throw new Error(`${res.status()} ${url}`);
        cache.set(url, { body: await res.body(), contentType: res.headers()['content-type'] ?? 'image/svg+xml' });
      } catch {
        cache.set(url, null);
      }
    }
    const hit = cache.get(url);
    return hit ? route.fulfill(hit) : route.abort();
  });
}
