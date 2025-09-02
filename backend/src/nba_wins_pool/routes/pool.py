from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.requests import Request
from fastapi.responses import JSONResponse, Response
from nba_wins_pool.aggregations import generate_leaderboard, generate_wins_race_data
from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.pool import PoolCreate, PoolPublic, PoolUpdate
from nba_wins_pool.nba_data import get_game_data
from nba_wins_pool.repositories.pool_repository import PoolRepository
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(tags=["pools"])

# TODO:
# - Update endpoints to have REST convention and use plural pools
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


@router.post("/pools", response_model=PoolPublic, status_code=status.HTTP_201_CREATED)
async def create_pool(pool_data: PoolCreate, db: AsyncSession = Depends(get_db_session)):
    """Create a new pool"""
    pool_repo = PoolRepository(db)

    # Check if slug already exists
    if await pool_repo.slug_exists(pool_data.slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pool with slug '{pool_data.slug}' already exists",
        )

    try:
        pool = await pool_repo.create(pool_data)
        return pool
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create pool: {str(e)}",
        ) from e


@router.get("/pools", response_model=List[PoolPublic])
async def get_pools(db: AsyncSession = Depends(get_db_session)):
    """Get all pools"""
    pool_repo = PoolRepository(db)
    try:
        pools = await pool_repo.get_all()
        return pools
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve pools: {str(e)}",
        ) from e


@router.get("/pools/{pool_id}", response_model=PoolPublic)
async def get_pool(pool_id: UUID, db: AsyncSession = Depends(get_db_session)):
    """Get a specific pool by ID"""
    pool_repo = PoolRepository(db)
    pool = await pool_repo.get_by_id(pool_id)
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pool with id {pool_id} not found",
        )
    return pool


@router.get("/pools/slug/{slug}", response_model=PoolPublic)
async def get_pool_by_slug(slug: str, db: AsyncSession = Depends(get_db_session)):
    """Get a specific pool by slug"""
    pool_repo = PoolRepository(db)
    pool = await pool_repo.get_by_slug(slug)
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pool with slug '{slug}' not found",
        )
    return pool


@router.put("/pools/{pool_id}", response_model=PoolPublic)
async def update_pool(pool_id: UUID, pool_data: PoolUpdate, db: AsyncSession = Depends(get_db_session)):
    """Update a pool"""
    pool_repo = PoolRepository(db)

    # If updating slug, check if new slug already exists (and it's not the same pool)
    if pool_data.slug and pool_data.slug != existing_pool.slug:
        if await pool_repo.slug_exists(pool_data.slug):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pool with slug '{pool_data.slug}' already exists",
            )

    try:
        updated_pool = await pool_repo.update(pool_id, pool_data)
        return updated_pool
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update pool: {str(e)}",
        ) from e


@router.delete("/pools/{pool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pool(pool_id: UUID, db: AsyncSession = Depends(get_db_session)):
    """Delete a pool"""
    pool_repo = PoolRepository(db)

    # Check if pool exists
    if not await pool_repo.get_by_id(pool_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pool with id {pool_id} not found",
        )

    try:
        await pool_repo.delete(pool_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete pool: {str(e)}",
        ) from e
