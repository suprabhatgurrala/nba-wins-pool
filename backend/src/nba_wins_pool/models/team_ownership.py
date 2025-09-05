from datetime import datetime
from decimal import Decimal
import uuid

from nba_wins_pool.utils.time import utc_now
from sqlmodel import Field, SQLModel


# Base model with shared fields
class TeamOwnershipBase(SQLModel):
    pool_id: uuid.UUID
    team_id: uuid.UUID
    owner_id: uuid.UUID
    auction_price: Decimal = Field(decimal_places=2)


# Database model
class TeamOwnership(TeamOwnershipBase, table=True):
    """Records who owns which team and at what price"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    team_id: uuid.UUID = Field(foreign_key="team.id")
    owner_id: uuid.UUID = Field(foreign_key="member.id", index=True)
    auction_price: Decimal = Field(decimal_places=2)
    created_at: datetime = Field(default_factory=utc_now)


# For creating team ownerships (request body)
class TeamOwnershipCreate(TeamOwnershipBase):
    pass
