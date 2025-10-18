import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.auction import Auction, AuctionStatus
from nba_wins_pool.types.season_str import SeasonStr


class AuctionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, auction: Auction, commit: bool = True) -> Auction:
        self.session.add(auction)
        if commit:
            await self.session.commit()
            await self.session.refresh(auction)
        return auction

    async def get_all(
        self, pool_id: Optional[uuid.UUID], season: Optional[SeasonStr], status: Optional[AuctionStatus]
    ) -> List[Auction]:
        statement = select(Auction).order_by(Auction.created_at.desc())
        if pool_id:
            statement = statement.where(Auction.pool_id == pool_id)
        if season:
            statement = statement.where(Auction.season == season)
        if status:
            statement = statement.where(Auction.status == status)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_by_id(self, auction_id: uuid.UUID) -> Optional[Auction]:
        statement = select(Auction).where(Auction.id == auction_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_first_by_pool_id(self, pool_id: uuid.UUID) -> Optional[Auction]:
        statement = select(Auction).where(Auction.pool_id == pool_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def delete(self, auction: Auction) -> bool:
        await self.session.delete(auction)
        await self.session.commit()
        return True


def get_auction_repository(db: AsyncSession = Depends(get_db_session)) -> AuctionRepository:
    return AuctionRepository(db)
