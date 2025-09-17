from typing import List, Optional
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.auction_participant import AuctionParticipant


class AuctionParticipantRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, participant_id: UUID) -> Optional[AuctionParticipant]:
        statement = select(AuctionParticipant).where(AuctionParticipant.id == participant_id)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def save(self, participant: AuctionParticipant, commit: bool = True) -> AuctionParticipant:
        self.session.add(participant)
        if commit:
            await self.session.commit()
            await self.session.refresh(participant)
        return participant

    async def save_all(self, participants: List[AuctionParticipant]) -> List[AuctionParticipant]:
        self.session.add_all(participants)
        await self.session.commit()
        for participant in participants:
            await self.session.refresh(participant)
        return participants

    async def get_all_by_auction_id(self, auction_id: UUID) -> List[AuctionParticipant]:
        statement = select(AuctionParticipant).where(AuctionParticipant.auction_id == auction_id)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_by_roster_id_and_auction_id(self, roster_id: UUID, auction_id: UUID) -> Optional[AuctionParticipant]:
        statement = select(AuctionParticipant).where(
            AuctionParticipant.roster_id == roster_id, AuctionParticipant.auction_id == auction_id
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def delete(self, participant: AuctionParticipant) -> bool:
        await self.session.delete(participant)
        await self.session.commit()
        return True


def get_auction_participant_repository(db: AsyncSession = Depends(get_db_session)) -> AuctionParticipantRepository:
    return AuctionParticipantRepository(db)
