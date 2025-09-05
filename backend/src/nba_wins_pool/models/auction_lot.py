from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from typing import TYPE_CHECKING
import uuid

from nba_wins_pool.utils.time import utc_now
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .bid import Bid


class LotStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class AuctionLotBase(SQLModel):
    auction_id: uuid.UUID
    team_id: uuid.UUID
    nominator_id: uuid.UUID
    winning_bidder_id: Optional[uuid.UUID]


class AuctionLot(AuctionLotBase, table=True):
    """Represents a nominated team currently being auctioned in an Auction."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    auction_id: uuid.UUID = Field(foreign_key="auction.id", index=True)
    team_id: uuid.UUID = Field(foreign_key="team.id")
    nominator_id: uuid.UUID = Field(foreign_key="member.id")
    winning_bid_amount: Optional[Decimal] = Field(default=None, decimal_places=2, ge=1)
    winning_bidder_id: Optional[uuid.UUID] = Field(default=None, foreign_key="member.id", index=True)
    status: LotStatus = Field(default=LotStatus.OPEN, index=True)
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: Optional[datetime] = None
    closed_by: Optional[uuid.UUID] = Field(default=None, foreign_key="member.id")

    # Relationships
    bids: List["Bid"] = Relationship()


class AuctionLotCreate(AuctionLotBase):
    pass
