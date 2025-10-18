from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from nba_wins_pool.models.pool_season import PoolSeason, PoolSeasonCreate, PoolSeasonResponse, PoolSeasonUpdate
from nba_wins_pool.repositories.pool_repository import PoolRepository, get_pool_repository
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository, get_pool_season_repository
from nba_wins_pool.types.season_str import SeasonStr

router = APIRouter(tags=["pool_seasons"])


@router.get("/pools/{pool_id}/seasons", response_model=List[PoolSeasonResponse])
async def get_pool_seasons(
    pool_id: UUID,
    pool_repo: PoolRepository = Depends(get_pool_repository),
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
) -> List[PoolSeasonResponse]:
    """Get all seasons for a pool"""
    # Verify pool exists
    pool = await pool_repo.get_by_id(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")

    seasons = await pool_season_repo.get_all_by_pool(pool_id)
    return [PoolSeasonResponse.model_validate(season) for season in seasons]


@router.post("/pools/{pool_id}/seasons", response_model=PoolSeasonResponse, status_code=status.HTTP_201_CREATED)
async def create_pool_season(
    pool_id: UUID,
    season_data: PoolSeasonCreate,
    pool_repo: PoolRepository = Depends(get_pool_repository),
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
) -> PoolSeasonResponse:
    """Create a new season for a pool"""
    # Verify pool exists
    pool = await pool_repo.get_by_id(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")

    # Verify pool_id matches
    if season_data.pool_id != pool_id:
        raise HTTPException(status_code=400, detail="Pool ID in URL does not match pool ID in request body")

    # Check if season already exists
    existing = await pool_season_repo.get_by_pool_and_season(pool_id, season_data.season)
    if existing:
        raise HTTPException(status_code=409, detail=f"Season {season_data.season} already exists for this pool")

    # Create pool season
    pool_season = PoolSeason.model_validate(season_data)
    created_season = await pool_season_repo.create(pool_season)
    return PoolSeasonResponse.model_validate(created_season)


@router.get("/pools/{pool_id}/seasons/{season}", response_model=PoolSeasonResponse)
async def get_pool_season(
    pool_id: UUID,
    season: SeasonStr,
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
) -> PoolSeasonResponse:
    """Get a specific season for a pool"""
    pool_season = await pool_season_repo.get_by_pool_and_season(pool_id, season)
    if not pool_season:
        raise HTTPException(status_code=404, detail="Pool season not found")

    return PoolSeasonResponse.model_validate(pool_season)


@router.patch("/pools/{pool_id}/seasons/{season}", response_model=PoolSeasonResponse)
async def update_pool_season(
    pool_id: UUID,
    season: SeasonStr,
    update_data: PoolSeasonUpdate,
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
) -> PoolSeasonResponse:
    """Update a pool season"""
    pool_season = await pool_season_repo.get_by_pool_and_season(pool_id, season)
    if not pool_season:
        raise HTTPException(status_code=404, detail="Pool season not found")

    # Update fields
    if update_data.rules is not None:
        pool_season.rules = update_data.rules

    updated_season = await pool_season_repo.update(pool_season)
    return PoolSeasonResponse.model_validate(updated_season)


@router.delete("/pools/{pool_id}/seasons/{season}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pool_season(
    pool_id: UUID,
    season: SeasonStr,
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
):
    """Delete a pool season"""
    pool_season = await pool_season_repo.get_by_pool_and_season(pool_id, season)
    if not pool_season:
        raise HTTPException(status_code=404, detail="Pool season not found")

    await pool_season_repo.delete(pool_season)
