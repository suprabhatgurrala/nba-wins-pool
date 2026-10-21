import { request, type APIRequestContext, type FullConfig } from '@playwright/test';

/** Creates a live auction with an open bid so the bid pane is checked; the returned teardown deletes it. */
export const LIVE_POOL_SLUG = 'layout-live';
export const LIVE_SEASON = '2025-26';
export const LIVE_TEAM = 'Minnesota Timberwolves';

export default async function globalSetup(config: FullConfig) {
  const api = await request.newContext({ baseURL: config.projects[0].use.baseURL });
  await removeLivePool(api);

  const pool = await call(api, 'post', '/pools', { slug: LIVE_POOL_SLUG, name: 'Layout Live Draft' });
  await call(api, 'post', `/pools/${pool.id}/seasons`, { pool_id: pool.id, season: LIVE_SEASON });
  for (const name of ['Alice', 'Ben', 'Cara', 'Dev']) {
    await call(api, 'post', '/rosters', { name, pool_id: pool.id, season: LIVE_SEASON });
  }
  const auction = await call(api, 'post', '/auctions', {
    pool_id: pool.id,
    season: LIVE_SEASON,
    max_lots_per_participant: 5,
    starting_participant_budget: 200,
  });
  await call(api, 'post', '/auction-participants/batch', { source: 'pool', auction_id: auction.id });
  await call(api, 'post', '/auction-lots/batch', { source: 'league', source_id: 'nba', auction_id: auction.id });
  await call(api, 'patch', `/auctions/${auction.id}`, { status: 'active' });

  const overview = await call(api, 'get', `/auctions/${auction.id}/overview`);
  const lot = overview.lots.find((l: any) => l.team.name === LIVE_TEAM).id;
  const who = Object.fromEntries(overview.participants.map((p: any) => [p.name, p.id]));
  await call(api, 'post', '/bids', { lot_id: lot, participant_id: who.Dev, amount: 18 });
  await call(api, 'post', '/bids', { lot_id: lot, participant_id: who.Ben, amount: 150 });

  return async () => {
    await removeLivePool(api);
    await api.dispose();
  };
}

/** Deletes the live pool and its auction, if a previous run left them behind. */
async function removeLivePool(api: APIRequestContext) {
  const res = await api.get(`/api/pools/slug/${LIVE_POOL_SLUG}`);
  if (!res.ok()) return;
  const pool = await res.json();
  for (const auction of await call(api, 'get', `/auctions?pool_id=${pool.id}`)) {
    await call(api, 'delete', `/auctions/${auction.id}`);
  }
  await call(api, 'delete', `/pools/${pool.id}`);
}

async function call(api: APIRequestContext, method: 'get' | 'post' | 'patch' | 'delete', url: string, data?: unknown) {
  const res = await api[method](`/api${url}`, { data });
  if (!res.ok()) throw new Error(`${method} ${url}: ${res.status()} ${await res.text()}`);
  return res.status() === 204 ? null : res.json();
}
