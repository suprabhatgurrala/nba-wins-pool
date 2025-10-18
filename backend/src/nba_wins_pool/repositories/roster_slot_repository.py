import uuid
from typing import List

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.roster_slot import RosterSlot


class RosterSlotRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, roster_slot: RosterSlot, commit: bool = True) -> RosterSlot:
        self.session.add(roster_slot)
        if commit:
            await self.session.commit()
            await self.session.refresh(roster_slot)
        return roster_slot

    async def save_all(self, roster_slots: List[RosterSlot]) -> List[RosterSlot]:
        self.session.add_all(roster_slots)
        await self.session.commit()
        for roster_slot in roster_slots:
            await self.session.refresh(roster_slot)
        return roster_slots

    async def get_all_by_roster_id(self, roster_id: uuid.UUID) -> List[RosterSlot]:
        statement = select(RosterSlot).where(RosterSlot.roster_id == roster_id)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_all_by_roster_id_in(self, roster_ids: List[uuid.UUID]) -> List[RosterSlot]:
        statement = select(RosterSlot).where(RosterSlot.roster_id.in_(roster_ids))
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def delete(self, roster_slot: RosterSlot) -> bool:
        await self.session.delete(roster_slot)
        await self.session.commit()
        return True

    async def delete_all_by_roster_id_in(self, roster_ids: List[uuid.UUID]) -> bool:
        roster_slots = await self.get_all_by_roster_id_in(roster_ids)
        for roster_slot in roster_slots:
            await self.session.delete(roster_slot)
        await self.session.commit()
        return True


def get_roster_slot_repository(db: AsyncSession = Depends(get_db_session)) -> RosterSlotRepository:
    return RosterSlotRepository(db)
