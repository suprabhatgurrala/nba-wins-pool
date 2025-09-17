import uuid
from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class Bid(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lot_id: uuid.UUID = Field(foreign_key="auctionlot.id", index=True, ondelete="CASCADE")
    participant_id: uuid.UUID = Field(foreign_key="auctionparticipant.id", index=True, ondelete="CASCADE")
    amount: Decimal = Field(decimal_places=2, gt=0)
    created_at: datetime = Field(default_factory=utc_now)


class BidCreate(SQLModel):
    lot_id: uuid.UUID
    participant_id: uuid.UUID
    amount: Decimal = Field(gt=0)
