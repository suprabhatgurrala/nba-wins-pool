import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.team_season_result import TeamSeasonResult
from nba_wins_pool.types.season_str import SeasonStr


class TeamSeasonResultRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_by_season(self, season: SeasonStr) -> List[TeamSeasonResult]:
        """Get every team's materialized record for a season"""
        statement = select(TeamSeasonResult).where(TeamSeasonResult.season == season)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_by_team_and_season(self, team_id: uuid.UUID, season: SeasonStr) -> Optional[TeamSeasonResult]:
        """Get a single team's materialized record for a season"""
        statement = select(TeamSeasonResult).where(
            TeamSeasonResult.team_id == team_id, TeamSeasonResult.season == season
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def create_all(self, team_season_results: List[TeamSeasonResult]) -> List[TeamSeasonResult]:
        """Persist materialized records for a season, skipping any team that already has one"""
        if not team_season_results:
            return []
        existing = await self.get_all_by_season(team_season_results[0].season)
        existing_team_ids = {r.team_id for r in existing}
        to_create = [r for r in team_season_results if r.team_id not in existing_team_ids]
        if not to_create:
            return existing
        self.session.add_all(to_create)
        await self.session.commit()
        return existing + to_create


def get_team_season_result_repository(db: AsyncSession = Depends(get_db_session)) -> TeamSeasonResultRepository:
    return TeamSeasonResultRepository(db)
