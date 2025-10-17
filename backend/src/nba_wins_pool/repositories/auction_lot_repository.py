import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.auction_lot import AuctionLot


class AuctionLotRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, auction_lot: AuctionLot, commit: bool = True) -> AuctionLot:
        """Create a new auction lot"""
        self.session.add(auction_lot)
        if commit:
            await self.session.commit()
            await self.session.refresh(auction_lot)
        return auction_lot

    async def save_all(self, auction_lots: List[AuctionLot]) -> List[AuctionLot]:
        self.session.add_all(auction_lots)
        await self.session.commit()
        for auction_lot in auction_lots:
            await self.session.refresh(auction_lot)
        return auction_lots

    async def get_by_id(self, auction_lot_id: uuid.UUID) -> Optional[AuctionLot]:
        """Get auction lot by id"""
        statement = select(AuctionLot).where(AuctionLot.id == auction_lot_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_auction_id_and_team_id(self, auction_id: uuid.UUID, team_id: uuid.UUID) -> Optional[AuctionLot]:
        statement = select(AuctionLot).where(AuctionLot.auction_id == auction_id, AuctionLot.team_id == team_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_all_by_auction_id(self, auction_id: uuid.UUID) -> List[AuctionLot]:
        """Get all auction lots in an auction"""
        statement = select(AuctionLot).where(AuctionLot.auction_id == auction_id).order_by(AuctionLot.opened_at)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def delete(self, auction_lot: AuctionLot) -> bool:
        """Delete auction lot"""
        await self.session.delete(auction_lot)
        await self.session.commit()
        return True


def get_auction_lot_repository(db: AsyncSession = Depends(get_db_session)) -> AuctionLotRepository:
    return AuctionLotRepository(db)
