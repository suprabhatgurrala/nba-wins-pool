"""Public routes that serve rich social embeds and OG preview images for pools.

Social crawlers (iMessage, Slack, Discord, WhatsApp, Facebook, Twitter/X) don't
execute JavaScript, so per-pool `<meta>` tags have to be in the initial HTML
response. These routes sit in front of the SPA static mount and inject the tags
before returning the same `index.html` the SPA would.
"""

import html
import logging
import re
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse

from nba_wins_pool.models.pool import Pool
from nba_wins_pool.repositories.pool_repository import PoolRepository, get_pool_repository
from nba_wins_pool.repositories.roster_repository import RosterRepository, get_roster_repository
from nba_wins_pool.services.leaderboard_service import LeaderboardService, get_leaderboard_service
from nba_wins_pool.services.nba_data_service import NbaDataService, get_nba_data_service
from nba_wins_pool.services.og_image_service import LeaderboardEntry, render_pool_card
from nba_wins_pool.types.season_str import SeasonStr

router = APIRouter(tags=["social"])
logger = logging.getLogger(__name__)

_SPA_INDEX_PATH = Path("static/index.html")

# Strips the site-wide default OG/Twitter/description tags baked into
# frontend/index.html so pool-specific tags don't compete with them (crawler
# behavior on duplicate og:* properties varies).
_DEFAULT_META_RE = re.compile(
    r'[ \t]*<meta\s+(?:property|name)\s*=\s*"(?:og:[^"]+|twitter:[^"]+|description)"[^>]*/?>\s*',
    re.IGNORECASE,
)


@router.get("/pools/{slug}", response_class=HTMLResponse)
async def pool_page(
    slug: str,
    request: Request,
    pool_repo: PoolRepository = Depends(get_pool_repository),
    roster_repo: RosterRepository = Depends(get_roster_repository),
    leaderboard_service: LeaderboardService = Depends(get_leaderboard_service),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
) -> HTMLResponse:
    """Serve the SPA's index.html with pool-specific OG/Twitter tags injected."""
    return await _serve_pool_html(
        slug=slug,
        season=None,
        request=request,
        pool_repo=pool_repo,
        roster_repo=roster_repo,
        leaderboard_service=leaderboard_service,
        nba_data_service=nba_data_service,
    )


@router.get("/pools/{slug}/season/{season}", response_class=HTMLResponse)
async def pool_page_for_season(
    slug: str,
    season: SeasonStr,
    request: Request,
    pool_repo: PoolRepository = Depends(get_pool_repository),
    roster_repo: RosterRepository = Depends(get_roster_repository),
    leaderboard_service: LeaderboardService = Depends(get_leaderboard_service),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
) -> HTMLResponse:
    return await _serve_pool_html(
        slug=slug,
        season=season,
        request=request,
        pool_repo=pool_repo,
        roster_repo=roster_repo,
        leaderboard_service=leaderboard_service,
        nba_data_service=nba_data_service,
    )


@router.get("/og/pools/{slug}.png")
async def pool_og_image(
    slug: str,
    season: SeasonStr | None = None,
    pool_repo: PoolRepository = Depends(get_pool_repository),
    roster_repo: RosterRepository = Depends(get_roster_repository),
    leaderboard_service: LeaderboardService = Depends(get_leaderboard_service),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
) -> Response:
    """Render the 1200x630 preview PNG referenced by pool OG meta tags."""
    # Strip an optional trailing "-<digits>" cache-buster before DB lookup so
    # `/og/pools/kk-1728430000.png` resolves to the same pool as `/og/pools/kk.png`.
    real_slug = re.sub(r"-\d+$", "", slug)
    pool = await pool_repo.get_by_slug(real_slug)
    if not pool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pool '{real_slug}' not found")

    resolved_season = season or _resolve_current_season(nba_data_service)
    entries, total = await _pool_entries(leaderboard_service, roster_repo, pool.id, resolved_season)
    png = render_pool_card(
        pool_name=pool.name,
        season_label=_format_season_label(resolved_season),
        rows=entries,
        total_rosters=total,
    )
    return Response(content=png, media_type="image/png")


async def _serve_pool_html(
    slug: str,
    season: SeasonStr | None,
    request: Request,
    pool_repo: PoolRepository,
    roster_repo: RosterRepository,
    leaderboard_service: LeaderboardService,
    nba_data_service: NbaDataService,
) -> HTMLResponse:
    pool = await pool_repo.get_by_slug(slug)
    if not pool:
        # Fall back to the plain SPA so the client-side 404 UI renders.
        return HTMLResponse(_spa_index_html())

    resolved_season = season or _resolve_current_season(nba_data_service)
    entries, _ = await _pool_entries(leaderboard_service, roster_repo, pool.id, resolved_season)

    canonical_url = str(request.url).split("?", 1)[0]
    og_image_url = _og_image_url(request, slug, season)
    meta_block = _build_meta_tags(
        pool=pool,
        season_label=_format_season_label(resolved_season),
        leader=entries[0] if entries else None,
        canonical_url=canonical_url,
        og_image_url=og_image_url,
    )
    shell = _DEFAULT_META_RE.sub("", _spa_index_html())
    injected = shell.replace("</head>", f"{meta_block}\n</head>", 1)
    return HTMLResponse(injected)


async def _pool_entries(
    leaderboard_service: LeaderboardService,
    roster_repo: RosterRepository,
    pool_id,
    season: SeasonStr,
) -> tuple[list[LeaderboardEntry], int]:
    """Return ranked entries with W-L records when available; otherwise raw roster names.

    Standings are computed from NBA game data at request time and can fail when the CDN
    is unreachable or hasn't loaded any games yet. In those cases we still want a useful
    preview, so we fall back to the roster list from the DB with no rank or record.
    """
    try:
        data = await leaderboard_service.get_leaderboard(pool_id, season)
        roster_rows = data.get("roster", [])
        if roster_rows:
            entries = []
            for i, row in enumerate(roster_rows):
                # LeaderboardService returns rank=None for the "Undrafted" pseudo-roster;
                # suppress its number so it doesn't take slot N in the visible standings.
                rank = None if row.get("rank") is None else i + 1
                entries.append(
                    LeaderboardEntry(
                        name=str(row["name"]),
                        wins=int(row["wins"]),
                        losses=int(row["losses"]),
                        rank=rank,
                    )
                )
            return entries, len(entries)
    except Exception:  # noqa: BLE001 — previews must degrade gracefully, not 500
        logger.exception("Leaderboard fetch failed for pool_id=%s season=%s; falling back to roster names", pool_id, season)

    rosters = await roster_repo.get_all(pool_id=pool_id, season=season)
    entries = [LeaderboardEntry(name=r.name) for r in rosters]
    return entries, len(entries)


def _resolve_current_season(nba_data_service: NbaDataService) -> str:
    """Ask NbaDataService, or fall back to a date-derived season string if the CDN is unreachable."""
    try:
        return nba_data_service.get_current_season()
    except Exception:  # noqa: BLE001
        today = date.today()
        start_year = today.year if today.month >= 10 else today.year - 1
        return f"{start_year}-{str(start_year + 1)[-2:]}"


def _og_image_url(request: Request, slug: str, season: SeasonStr | None) -> str:
    # Embed a fresh timestamp in the path so crawlers that cache image bytes by
    # URL (e.g. Discord) see a new image URL on each HTML scrape. The route
    # handler strips the trailing digits and looks up the pool by real slug.
    base = str(request.base_url).rstrip("/")
    url = f"{base}/og/pools/{slug}-{int(time.time())}.png"
    if season:
        url = f"{url}?season={season}"
    return url


def _format_season_label(season: SeasonStr) -> str:
    # SeasonStr is validated as "YYYY-YY"; keep it stable but render an en-dash.
    return season.replace("-", "–")


def _build_meta_tags(
    pool: Pool,
    season_label: str,
    leader: LeaderboardEntry | None,
    canonical_url: str,
    og_image_url: str,
) -> str:
    title = f"{pool.name} · {season_label}"
    if leader is not None and leader.has_record:
        description = f"Standings for {pool.name} — leader: {leader.name} ({leader.wins}–{leader.losses})"
    else:
        description = f"Standings for {pool.name}"

    e = html.escape
    tags = [
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(description)}">',
        f'<meta property="og:image" content="{e(og_image_url)}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:url" content="{e(canonical_url)}">',
        '<meta property="og:type" content="website">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(description)}">',
        f'<meta name="twitter:image" content="{e(og_image_url)}">',
        f'<meta name="description" content="{e(description)}">',
    ]
    return "\n    ".join(tags)


@lru_cache(maxsize=1)
def _spa_index_html() -> str:
    """Load the built SPA index.html once. Falls back to a minimal shell if absent."""
    if _SPA_INDEX_PATH.exists():
        return _SPA_INDEX_PATH.read_text(encoding="utf-8")
    return "<!doctype html><html><head></head><body></body></html>"
