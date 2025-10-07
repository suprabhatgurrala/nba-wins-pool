import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.auction_event_log import AuctionEventLog


class AuctionEventLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, event_log: AuctionEventLog, commit: bool = True) -> AuctionEventLog:
        """Save an event log entry"""
        self.session.add(event_log)
        if commit:
            await self.session.commit()
            await self.session.refresh(event_log)
        return event_log

    async def get_by_auction_id(
        self, auction_id: uuid.UUID, limit: Optional[int] = None
    ) -> List[AuctionEventLog]:
        """Get all event logs for an auction, ordered by created_at desc"""
        statement = (
            select(AuctionEventLog)
            .where(AuctionEventLog.auction_id == auction_id)
            .order_by(AuctionEventLog.created_at.desc())
        )
        if limit:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return result.scalars().all()


def get_auction_event_log_repository(
    db: AsyncSession = Depends(get_db_session),
) -> AuctionEventLogRepository:
    return AuctionEventLogRepository(db)
