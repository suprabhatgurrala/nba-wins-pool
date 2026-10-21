import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, Index, SQLModel

from nba_wins_pool.utils.time import utc_now


class AuctionEventLog(SQLModel, table=True):
    """Persistent storage for auction events"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    auction_id: uuid.UUID = Field(foreign_key="auction.id", index=True, ondelete="CASCADE")
    event_type: str = Field(index=True)
    payload: dict = Field(sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=utc_now, index=True)

    __table_args__ = (Index("ix_auctioneventlog_auction_id_created_at", "auction_id", "created_at"),)
