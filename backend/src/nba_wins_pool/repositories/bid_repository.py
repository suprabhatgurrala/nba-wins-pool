import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.bid import Bid


class BidRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, bid: Bid, commit: bool = True) -> Bid:
        """Create a new bid"""
        self.session.add(bid)
        if commit:
            await self.session.commit()
            await self.session.refresh(bid)
        return bid

    async def get_by_id(self, bid_id: uuid.UUID) -> Bid:
        """Get bid by id"""
        statement = select(Bid).where(Bid.id == bid_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_all_by_ids(self, bid_ids: List[uuid.UUID]) -> List[Bid]:
        statement = select(Bid).where(Bid.id.in_(bid_ids))
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_all(
        self, lot_id: Optional[uuid.UUID] = None, participant_id: Optional[uuid.UUID] = None
    ) -> List[Bid]:
        statement = select(Bid).order_by(Bid.created_at.desc())
        if lot_id:
            statement = statement.where(Bid.lot_id == lot_id)
        if participant_id:
            statement = statement.where(Bid.participant_id == participant_id)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def delete(self, bid: Bid) -> bool:
        """Delete bid"""
        await self.session.delete(bid)
        await self.session.commit()
        return True


def get_bid_repository(db: AsyncSession = Depends(get_db_session)) -> BidRepository:
    return BidRepository(db)
