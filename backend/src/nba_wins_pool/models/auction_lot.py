import uuid
from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional

from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class AuctionLotStatus(str, Enum):
    READY = "ready"
    OPEN = "open"
    CLOSED = "closed"


class AuctionLot(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: AuctionLotStatus = Field(default=AuctionLotStatus.READY)
    auction_id: uuid.UUID = Field(foreign_key="auction.id", index=True, ondelete="CASCADE")
    team_id: uuid.UUID = Field(foreign_key="team.id")
    winning_bid_id: Optional[uuid.UUID] = Field(default=None, foreign_key="bid.id")
    created_at: datetime = Field(default_factory=utc_now)
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

class AuctionLotCreate(SQLModel):
    auction_id: uuid.UUID
    team_id: uuid.UUID


class AuctionLotUpdate(SQLModel):
    status: AuctionLotStatus


class AuctionLotBatchCreate(SQLModel):
    source: Literal["league", "request"]
    source_id: Optional[str] = None
    auction_id: Optional[uuid.UUID] = None
    auction_lots: Optional[List[AuctionLotCreate]] = None
