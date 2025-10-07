import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.pool_season import PoolSeason
from nba_wins_pool.types.season_str import SeasonStr


class PoolSeasonRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, pool_season: PoolSeason) -> PoolSeason:
        """Create a new pool season"""
        self.session.add(pool_season)
        await self.session.commit()
        await self.session.refresh(pool_season)
        return pool_season

    async def get_by_id(self, pool_season_id: uuid.UUID) -> Optional[PoolSeason]:
        """Get pool season by ID"""
        statement = select(PoolSeason).where(PoolSeason.id == pool_season_id)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_by_pool_and_season(self, pool_id: uuid.UUID, season: SeasonStr) -> Optional[PoolSeason]:
        """Get pool season by pool ID and season"""
        statement = select(PoolSeason).where(PoolSeason.pool_id == pool_id, PoolSeason.season == season)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_all_by_pool(self, pool_id: uuid.UUID) -> List[PoolSeason]:
        """Get all seasons for a pool"""
        statement = select(PoolSeason).where(PoolSeason.pool_id == pool_id).order_by(PoolSeason.season.desc())
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_all_by_pools(self, pool_ids: List[uuid.UUID]) -> List[PoolSeason]:
        """Get all seasons for multiple pools in a single batch query (optimization for N+1)"""
        if not pool_ids:
            return []
        statement = select(PoolSeason).where(PoolSeason.pool_id.in_(pool_ids)).order_by(PoolSeason.season.desc())
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def update(self, pool_season: PoolSeason) -> PoolSeason:
        """Update pool season"""
        self.session.add(pool_season)
        await self.session.commit()
        await self.session.refresh(pool_season)
        return pool_season

    async def delete(self, pool_season: PoolSeason) -> bool:
        """Delete pool season"""
        await self.session.delete(pool_season)
        await self.session.commit()
        return True

    async def exists(self, pool_id: uuid.UUID, season: SeasonStr) -> bool:
        """Check if pool season exists"""
        statement = select(PoolSeason).where(PoolSeason.pool_id == pool_id, PoolSeason.season == season)
        result = await self.session.execute(statement)
        return result.scalars().first() is not None


def get_pool_season_repository(db: AsyncSession = Depends(get_db_session)) -> PoolSeasonRepository:
    return PoolSeasonRepository(db)
