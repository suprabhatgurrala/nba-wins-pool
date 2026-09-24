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
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse

from nba_wins_pool.models.pool import Pool
from nba_wins_pool.repositories.pool_repository import PoolRepository, get_pool_repository
from nba_wins_pool.repositories.roster_repository import RosterRepository, get_roster_repository
from nba_wins_pool.services.leaderboard_service import LeaderboardService, get_leaderboard_service
from nba_wins_pool.services.nba_data_service import NbaDataService, get_nba_data_service
from nba_wins_pool.services.og_image_service import LeaderboardEntry, render_pool_card
from nba_wins_pool.services.pool_history_service import (
    ParticipantHistory,
    ParticipantHistorySeason,
    PoolHistory,
    PoolHistoryService,
    get_pool_history_service,
)
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
    pool_history_service: PoolHistoryService = Depends(get_pool_history_service),
) -> HTMLResponse:
    """Serve the SPA's index.html with overview (all-time history) OG/Twitter tags injected.

    This is the pool's landing page — it shows season history, not live standings — so its
    preview is built from `PoolHistoryService` rather than the current leaderboard.
    """
    pool = await pool_repo.get_by_slug(slug)
    if not pool:
        return HTMLResponse(_spa_index_html())

    history = await pool_history_service.get_pool_history(pool.id)

    canonical_url = str(request.url).split("?", 1)[0]
    og_image_url = _og_image_url(request, slug, season=None)
    meta_block = _build_overview_meta_tags(
        pool=pool,
        history=history,
        canonical_url=canonical_url,
        og_image_url=og_image_url,
    )
    shell = _DEFAULT_META_RE.sub("", _spa_index_html())
    injected = shell.replace("</head>", f"{meta_block}\n</head>", 1)
    return HTMLResponse(injected)


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


@router.get("/pools/{slug}/participant/{name}", response_class=HTMLResponse)
async def participant_page(
    slug: str,
    name: str,
    request: Request,
    pool_repo: PoolRepository = Depends(get_pool_repository),
    pool_history_service: PoolHistoryService = Depends(get_pool_history_service),
) -> HTMLResponse:
    """Serve the SPA's index.html with participant-history OG/Twitter tags injected."""
    pool = await pool_repo.get_by_slug(slug)
    if not pool:
        return HTMLResponse(_spa_index_html())

    history = await pool_history_service.get_participant_history(pool.id, name)
    if not history.seasons:
        return HTMLResponse(_spa_index_html())

    canonical_url = str(request.url).split("?", 1)[0]
    og_image_url = _og_participant_image_url(request, slug, name)
    meta_block = _build_participant_meta_tags(
        pool=pool,
        participant_name=name,
        history=history,
        canonical_url=canonical_url,
        og_image_url=og_image_url,
    )
    shell = _DEFAULT_META_RE.sub("", _spa_index_html())
    injected = shell.replace("</head>", f"{meta_block}\n</head>", 1)
    return HTMLResponse(injected)


@router.get("/og/pools/{slug}.png")
async def pool_og_image(
    slug: str,
    season: SeasonStr | None = None,
    pool_repo: PoolRepository = Depends(get_pool_repository),
    roster_repo: RosterRepository = Depends(get_roster_repository),
    leaderboard_service: LeaderboardService = Depends(get_leaderboard_service),
    pool_history_service: PoolHistoryService = Depends(get_pool_history_service),
) -> Response:
    """Render the 1200x630 preview PNG referenced by a pool page's OG meta tags.

    With no `season`, this is the overview page's link and renders the all-time
    participant card; with `season`, it renders that season's standings.
    """
    pool = await _pool_from_cache_busted_slug(slug, pool_repo)

    if season is None:
        png = _render_overview_card(pool, await pool_history_service.get_pool_history(pool.id))
        return Response(content=png, media_type="image/png")

    entries, total = await _pool_entries(leaderboard_service, roster_repo, pool.id, season)
    png = render_pool_card(
        pool_name=pool.name,
        season_label=_format_season_label(season),
        rows=entries,
        total_rosters=total,
    )
    return Response(content=png, media_type="image/png")


@router.get("/og/pools/{slug}/participant/{name}.png")
async def participant_og_image(
    slug: str,
    name: str,
    pool_repo: PoolRepository = Depends(get_pool_repository),
    pool_history_service: PoolHistoryService = Depends(get_pool_history_service),
) -> Response:
    """Render the 1200x630 preview PNG referenced by a participant page's OG meta tags."""
    pool = await _pool_from_cache_busted_slug(slug, pool_repo)
    real_name = re.sub(r"-\d+$", "", name)

    history = await pool_history_service.get_participant_history(pool.id, real_name)
    if not history.seasons:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Participant '{real_name}' not found")

    png = _render_participant_card(real_name, pool, history)
    return Response(content=png, media_type="image/png")


def _render_overview_card(pool: Pool, history: PoolHistory) -> bytes:
    entries = [
        LeaderboardEntry(
            name=participant.name,
            rank=i + 1,
            detail=f"{participant.championships} title{'' if participant.championships == 1 else 's'}",
        )
        for i, participant in enumerate(history.participants)
    ]
    return render_pool_card(
        pool_name=pool.name,
        season_label=_seasons_label(history),
        rows=entries,
        total_rosters=len(entries),
        overflow_noun="participant",
    )


def _render_participant_card(participant_name: str, pool: Pool, history: ParticipantHistory) -> bytes:
    entries = [LeaderboardEntry(name=s.season, wins=s.wins, losses=s.losses, rank=s.rank) for s in history.seasons]
    return render_pool_card(
        pool_name=participant_name,
        season_label=pool.name,
        rows=entries,
        total_rosters=len(entries),
        overflow_noun="season",
    )


async def _pool_from_cache_busted_slug(slug: str, pool_repo: PoolRepository) -> Pool:
    # Strip an optional trailing "-<digits>" cache-buster before DB lookup so
    # `/og/pools/kk-1728430000.png` resolves to the same pool as `/og/pools/kk.png`.
    real_slug = re.sub(r"-\d+$", "", slug)
    pool = await pool_repo.get_by_slug(real_slug)
    if not pool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pool '{real_slug}' not found")
    return pool


async def _serve_pool_html(
    slug: str,
    season: SeasonStr | None,
    request: Request,
    pool_repo: PoolRepository,
    roster_repo: RosterRepository,
    leaderboard_service: LeaderboardService,
    nba_data_service: NbaDataService,
) -> HTMLResponse:
    """Serve the SPA's index.html with season-standings OG/Twitter tags injected."""
    pool = await pool_repo.get_by_slug(slug)
    if not pool:
        # Fall back to the plain SPA so the client-side 404 UI renders.
        return HTMLResponse(_spa_index_html())

    resolved_season = season or _resolve_current_season(nba_data_service)
    entries, _ = await _pool_entries(leaderboard_service, roster_repo, pool.id, resolved_season)

    canonical_url = str(request.url).split("?", 1)[0]
    og_image_url = _og_image_url(request, slug, season=season)
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
        logger.exception(
            "Leaderboard fetch failed for pool_id=%s season=%s; falling back to roster names", pool_id, season
        )

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
    # A missing `season` renders the all-time overview card (see pool_og_image).
    base = str(request.base_url).rstrip("/")
    url = f"{base}/og/pools/{slug}-{int(time.time())}.png"
    if season:
        url = f"{url}?season={season}"
    return url


def _og_participant_image_url(request: Request, slug: str, name: str) -> str:
    # Cache-bust the same way _og_image_url does (see its comment); the route handler
    # strips the trailing digits from `name` before looking up the participant.
    base = str(request.base_url).rstrip("/")
    return f"{base}/og/pools/{slug}/participant/{quote(name)}-{int(time.time())}.png"


def _format_season_label(season: SeasonStr) -> str:
    # SeasonStr is validated as "YYYY-YY"; keep it stable but render an en-dash.
    return season.replace("-", "–")


def _seasons_label(history: PoolHistory) -> str:
    seasons_played = len(history.seasons)
    if not seasons_played:
        return "New pool"
    label = f"{seasons_played} season{'' if seasons_played == 1 else 's'}"
    earliest_season = history.seasons[-1].season
    return f"{label} · est. {earliest_season}"


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
    return _meta_tags(title, description, canonical_url, og_image_url)


def _build_overview_meta_tags(
    pool: Pool,
    history: PoolHistory,
    canonical_url: str,
    og_image_url: str,
) -> str:
    title = pool.name
    description = f"{_seasons_label(history)} — {pool.name} NBA wins pool"
    champions = [s.champion for s in history.seasons if s.champion is not None]
    if champions:
        latest_champion = champions[0]
        description = (
            f"{_seasons_label(history)} · defending champ: {latest_champion.name} "
            f"({latest_champion.wins}–{latest_champion.losses})"
        )
    return _meta_tags(title, description, canonical_url, og_image_url)


def _build_participant_meta_tags(
    pool: Pool,
    participant_name: str,
    history: ParticipantHistory,
    canonical_url: str,
    og_image_url: str,
) -> str:
    title = f"{participant_name} · {pool.name}"
    description = f"{_participant_blurb(history.seasons)} — {pool.name}"
    return _meta_tags(title, description, canonical_url, og_image_url)


def _participant_blurb(seasons: list[ParticipantHistorySeason]) -> str:
    """Mirrors the frontend's participant blurb (ParticipantHistoryView.vue)."""
    seasons_played = len(seasons)
    seasons_text = f"{seasons_played} season{'' if seasons_played == 1 else 's'}"
    champion_seasons = [s for s in seasons if s.rank == 1]

    if len(champion_seasons) > 1:
        return f"{seasons_text} · {len(champion_seasons)}-time champion"
    if len(champion_seasons) == 1:
        return f"{seasons_text} · champion in {champion_seasons[0].season}"

    ranked = [s for s in seasons if s.rank is not None]
    if not ranked:
        return seasons_text
    best_rank = min(s.rank for s in ranked)
    return f"{seasons_text} · best finish: {_ordinal(best_rank)}"


def _ordinal(rank: int) -> str:
    if 11 <= (rank % 100) <= 13:
        return f"{rank}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def _meta_tags(title: str, description: str, canonical_url: str, og_image_url: str) -> str:
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


_spa_index_cache: tuple[float, str] | None = None


def _spa_index_html() -> str:
    """Re-read index.html when it changes on disk (the backend can outlive a frontend-only redeploy)."""
    global _spa_index_cache
    try:
        mtime = _SPA_INDEX_PATH.stat().st_mtime
    except FileNotFoundError:
        return "<!doctype html><html><head></head><body></body></html>"

    if _spa_index_cache is None or _spa_index_cache[0] != mtime:
        _spa_index_cache = (mtime, _SPA_INDEX_PATH.read_text(encoding="utf-8"))
    return _spa_index_cache[1]
