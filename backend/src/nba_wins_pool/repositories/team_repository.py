import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.team import LeagueSlug, Team


class TeamRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, team_id: uuid.UUID) -> Optional[Team]:
        statement = select(Team).where(Team.id == team_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_all_by_ids(self, team_ids: List[uuid.UUID]) -> List[Team]:
        if not team_ids:
            return []
        statement = select(Team).where(Team.id.in_(team_ids))
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_all_by_league_slug(self, league_slug: LeagueSlug) -> List[Team]:
        statement = select(Team).where(Team.league_slug == league_slug)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def save(self, team: Team, commit: bool = True) -> Team:
        self.session.add(team)
        if commit:
            await self.session.commit()
            await self.session.refresh(team)
        return team

    async def delete(self, team: Team) -> bool:
        await self.session.delete(team)
        await self.session.commit()
        return True


def get_team_repository(db: AsyncSession = Depends(get_db_session)) -> TeamRepository:
    return TeamRepository(db)
