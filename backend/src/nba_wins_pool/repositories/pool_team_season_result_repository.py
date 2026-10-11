import uuid
from typing import List

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.pool_team_season_result import PoolTeamSeasonResult


class PoolTeamSeasonResultRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_by_pool(self, pool_id: uuid.UUID) -> List[PoolTeamSeasonResult]:
        """Get every materialized team-season row for a pool, across all its seasons"""
        statement = select(PoolTeamSeasonResult).where(PoolTeamSeasonResult.pool_id == pool_id)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_all_by_pool_season(self, pool_season_id: uuid.UUID) -> List[PoolTeamSeasonResult]:
        """Get the materialized team-season rows for a single pool season"""
        statement = select(PoolTeamSeasonResult).where(PoolTeamSeasonResult.pool_season_id == pool_season_id)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def create_all(self, pool_team_season_results: List[PoolTeamSeasonResult]) -> List[PoolTeamSeasonResult]:
        """Persist materialized rows for a pool season, skipping if it's already materialized"""
        if not pool_team_season_results:
            return []
        existing = await self.get_all_by_pool_season(pool_team_season_results[0].pool_season_id)
        if existing:
            return existing
        self.session.add_all(pool_team_season_results)
        await self.session.commit()
        return pool_team_season_results


def get_pool_team_season_result_repository(
    db: AsyncSession = Depends(get_db_session),
) -> PoolTeamSeasonResultRepository:
    return PoolTeamSeasonResultRepository(db)
