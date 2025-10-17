import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from sqlmodel import Field, SQLModel, UniqueConstraint

from nba_wins_pool.utils.time import utc_now


class AuctionParticipant(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(min_length=1, max_length=100)
    auction_id: uuid.UUID = Field(foreign_key="auction.id", index=True, ondelete="CASCADE")
    roster_id: uuid.UUID = Field(foreign_key="roster.id", index=True)
    budget: Decimal = Field(ge=0, decimal_places=2)
    num_lots_won: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)

    # constraint on (auction_id, roster_id)
    __table_args__ = (UniqueConstraint("auction_id", "roster_id"),)


class AuctionParticipantCreate(SQLModel):
    name: str
    auction_id: uuid.UUID
    roster_id: uuid.UUID


class AuctionParticipantBatchCreate(SQLModel):
    source: Literal["pool", "request"]
    source_id: Optional[str] = None
    auction_id: Optional[uuid.UUID] = None
    auction_participants: Optional[List[AuctionParticipantCreate]] = None
