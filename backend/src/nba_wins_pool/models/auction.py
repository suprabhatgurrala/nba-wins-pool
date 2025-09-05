import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class AuctionStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"


class AuctionBase(SQLModel):
    pool_id: uuid.UUID
    lots_per_member: int
    status: AuctionStatus = Field(default=AuctionStatus.DRAFT)
    min_bid_increment: Decimal = Field(default=Decimal("1.00"), decimal_places=2)


class Auction(AuctionBase, table=True):
    """Represents an auction session for a pool"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    status: AuctionStatus = Field(default=AuctionStatus.DRAFT)
    lots_per_member: int
    min_bid_increment: Decimal = Field(default=Decimal("1.00"), decimal_places=2)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AuctionCreate(AuctionBase):
    pass
