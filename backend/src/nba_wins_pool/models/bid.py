from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from nba_wins_pool.utils.time import utc_now
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .member import Member


class BidBase(SQLModel):
    lot_id: uuid.UUID
    bidder_id: uuid.UUID
    amount: Decimal = Field(decimal_places=2, ge=1)


class Bid(BidBase, table=True):
    """Represents a bid placed by a member on an auction lot."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lot_id: uuid.UUID = Field(foreign_key="auctionlot.id", index=True)
    bidder_id: uuid.UUID = Field(foreign_key="member.id", index=True)
    amount: Decimal = Field(decimal_places=2, ge=1)
    created_at: datetime = Field(default_factory=utc_now)

    # Relationships
    bidder: "Member" = Relationship()


class BidCreate(BidBase):
    pass
