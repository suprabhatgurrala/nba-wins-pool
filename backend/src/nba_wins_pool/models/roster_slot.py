import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class RosterSlot(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    roster_id: uuid.UUID = Field(foreign_key="roster.id", index=True, ondelete="CASCADE")
    team_id: uuid.UUID = Field(foreign_key="team.id")
    created_at: datetime = Field(default_factory=utc_now)

    auction_lot_id: Optional[uuid.UUID] = Field(default=None, foreign_key="auctionlot.id", ondelete="SET NULL")
    auction_price: Optional[Decimal] = Field(default=None, decimal_places=2)


class RosterSlotCreate(SQLModel):
    roster_id: uuid.UUID
    team_id: uuid.UUID
    auction_lot_id: Optional[uuid.UUID]
    auction_price: Optional[Decimal] = Field(decimal_places=2)


class RosterSlotBatchCreate(SQLModel):
    source: Literal["auction", "request"]
    source_id: Optional[str] = None
    roster_slots: Optional[List[RosterSlotCreate]] = None
    replace: Optional[bool] = True
