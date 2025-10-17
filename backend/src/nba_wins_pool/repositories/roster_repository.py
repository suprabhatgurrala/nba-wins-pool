import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.roster import Roster


class RosterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, roster: Roster) -> Roster:
        self.session.add(roster)
        await self.session.commit()
        await self.session.refresh(roster)
        return roster

    async def save_all(self, rosters: List[Roster]) -> List[Roster]:
        self.session.add_all(rosters)
        await self.session.commit()
        for roster in rosters:
            await self.session.refresh(roster)
        return rosters

    async def get_by_id(self, roster_id: uuid.UUID) -> Optional[Roster]:
        """Get roster by ID and pool ID"""
        statement = select(Roster).where(Roster.id == roster_id)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_all(self, pool_id: Optional[uuid.UUID] = None, season: Optional[int] = None) -> List[Roster]:
        statement = select(Roster)
        if pool_id:
            statement = statement.where(Roster.pool_id == pool_id)
        if season:
            statement = statement.where(Roster.season == season)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def delete(self, roster: Roster) -> bool:
        """Delete roster"""
        await self.session.delete(roster)
        await self.session.commit()
        return True


def get_roster_repository(db: AsyncSession = Depends(get_db_session)) -> RosterRepository:
    return RosterRepository(db)
