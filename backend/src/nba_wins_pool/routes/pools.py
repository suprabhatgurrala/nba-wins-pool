from typing import List, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.requests import Request
from fastapi.responses import JSONResponse, Response

from nba_wins_pool.aggregations import generate_leaderboard, generate_wins_race_data
from nba_wins_pool.models.pool import Pool, PoolCreate, PoolOverview, PoolUpdate, PoolListItem, PoolListItemSeason
from nba_wins_pool.nba_data import get_game_data
from nba_wins_pool.repositories.pool_repository import PoolRepository, get_pool_repository
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository, get_pool_season_repository
from nba_wins_pool.services.leaderboard_service import LeaderboardService, get_leaderboard_service
from nba_wins_pool.services.pool_service import PoolService, get_pool_service
from nba_wins_pool.services.wins_race_service import WinsRaceService, get_wins_race_service
from nba_wins_pool.types.season_str import SeasonStr

router = APIRouter(tags=["pools"])

# TODO:
# - Deprecate these legacy endpoints
# - Update endpoints to have REST convention and use plural 'pools'
# - Refactor commands to use fast api dependencies & fetch data from database


@router.get("/pool/{pool_slug}/leaderboard", response_class=Response)
def leaderboard(request: Request, pool_slug: str):
    owner_df, team_df = generate_leaderboard(pool_slug, *get_game_data(pool_slug))
    return JSONResponse(
        {
            "owner": owner_df.to_dict(orient="records"),
            "team": team_df.to_dict(orient="records"),
        }
    )


team_metadata_by_id = {
    "sg": {
        "name": "West Coast Boys",
        "description": "I thought you meant weast",
        "rules": "1st: 50%, 2nd: 15%, 1st All-Star: 20%, 2nd All-Star: 10%, IST: 5%",
    },
    "kk": {
        "name": "Kalhan Kup",
        "description": "Some scrubs who know Kartik",
        "rules": "Don't suck",
    },
}


@router.get("/pool/{pool_slug}/metadata", response_class=Response)
def overview(request: Request, pool_slug: str):
    metadata = team_metadata_by_id.get(pool_slug)
    if not metadata:
        raise HTTPException(status_code=404, detail="Item not found")
    return JSONResponse(metadata)


@router.get("/pool/{pool_slug}/wins_race", response_class=Response)
def wins_race(request: Request, pool_slug: str):
    """
    Return time series data of cumulative wins for each owner over time
    """
    wins_race_data = generate_wins_race_data(pool_slug, *get_game_data(pool_slug))
    return JSONResponse(wins_race_data)


# ===== DB backed endpoints =====


@router.post("/pools", response_model=Pool, status_code=status.HTTP_201_CREATED)
async def create_pool(pool_data: PoolCreate, pool_repo: PoolRepository = Depends(get_pool_repository)):
    """Create a new pool"""
    pool = Pool.model_validate(pool_data)
    if await pool_repo.get_by_slug(pool.slug):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pool with slug already exists")
    pool = await pool_repo.save(pool)
    return pool


@router.get("/pools/{pool_id}", response_model=Pool)
async def get_pool(pool_id: UUID, pool_repo: PoolRepository = Depends(get_pool_repository)):
    """Get a specific pool by id"""
    pool = await pool_repo.get_by_id(pool_id)
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pool with id {pool_id} not found",
        )
    return pool


@router.get("/pools", response_model=Union[List[Pool], List[PoolListItem]])
async def get_pools(
    include_seasons: bool = Query(False, description="Include seasons for each pool (optimized batch query)"),
    pool_repo: PoolRepository = Depends(get_pool_repository),
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
):
    """Get all pools, optionally with their seasons in a single batch query"""
    pools = await pool_repo.get_all()
    
    if include_seasons:
        # Batch query all seasons for all pools in a single database query
        pool_ids = [pool.id for pool in pools]
        all_seasons = await pool_season_repo.get_all_by_pools(pool_ids)
        
        # Group seasons by pool_id
        seasons_by_pool = {}
        for season in all_seasons:
            if season.pool_id not in seasons_by_pool:
                seasons_by_pool[season.pool_id] = []
            seasons_by_pool[season.pool_id].append(PoolListItemSeason(id=season.id, season=season.season))
        
        # Build PoolListItem response models
        return [
            PoolListItem(
                id=pool.id,
                slug=pool.slug,
                name=pool.name,
                description=pool.description,
                created_at=pool.created_at,
                seasons=seasons_by_pool.get(pool.id, [])
            )
            for pool in pools
        ]
    
    return pools


@router.get("/pools/slug/{slug}", response_model=Pool)
async def get_pool_by_slug(slug: str, pool_repo: PoolRepository = Depends(get_pool_repository)):
    """Get a specific pool by slug"""
    pool = await pool_repo.get_by_slug(slug)
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pool with slug '{slug}' not found",
        )
    return pool


@router.patch("/pools/{pool_id}", response_model=Pool)
async def update_pool(pool_id: UUID, pool_data: PoolUpdate, pool_repo: PoolRepository = Depends(get_pool_repository)):
    """Update a pool"""
    existing_pool = await pool_repo.get_by_id(pool_id)
    if not existing_pool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pool with id {pool_id} not found",
        )
    pool_data = pool_data.model_dump(exclude_unset=True)
    existing_pool.sqlmodel_update(pool_data)
    return await pool_repo.save(existing_pool)


@router.delete("/pools/{pool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pool(pool_id: UUID, pool_repo: PoolRepository = Depends(get_pool_repository)):
    """Delete a pool"""
    existing_pool = await pool_repo.get_by_id(pool_id)
    if not existing_pool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pool with id {pool_id} not found",
        )
    await pool_repo.delete(existing_pool)


@router.get("/pools/{pool_id}/season/{season}/overview", response_model=PoolOverview)
async def get_pool_season_overview(
    pool_id: UUID,
    season: SeasonStr,
    pool_service: PoolService = Depends(get_pool_service),
) -> PoolOverview:
    """Get detailed pool overview for a season with rosters, roster slots, and teams"""
    return await pool_service.get_pool_season_overview(pool_id, season)


@router.get("/pools/{pool_id}/season/{season}/leaderboard", response_class=Response)
async def leaderboard_v2(
    pool_id: UUID,
    season: SeasonStr,
    leaderboard_service: LeaderboardService = Depends(get_leaderboard_service),
):
    """Leaderboard"""
    data = await leaderboard_service.get_leaderboard(pool_id, season)
    return JSONResponse(data)


@router.get("/pools/{pool_id}/season/{season}/wins-race", response_class=Response)
async def wins_race_v2(
    pool_id: UUID,
    season: SeasonStr,
    wins_race_service: WinsRaceService = Depends(get_wins_race_service),
):
    """Wins race cumulative wins time series."""
    data = await wins_race_service.get_wins_race(pool_id, season)
    return JSONResponse(data)
