from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
from decimal import Decimal
import uuid

if TYPE_CHECKING:
    from .member import MemberPublic
    from .team import TeamPublic


# Base model with shared fields
class TeamOwnershipBase(SQLModel):
    pool_id: uuid.UUID
    season: str  # e.g., "2024-25"
    team_slug: str
    owner_id: uuid.UUID
    auction_price: Decimal = Field(decimal_places=2)


# Database model
class TeamOwnership(TeamOwnershipBase, table=True):
    """Records who owns which team in which season and at what price"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    season: str = Field(index=True)  # e.g., "2024-25"
    team_slug: str = Field(foreign_key="team.slug", index=True)
    owner_id: uuid.UUID = Field(foreign_key="member.id", index=True)
    auction_price: Decimal = Field(decimal_places=2)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    pool: "Pool" = Relationship(back_populates="team_ownerships")
    team: "Team" = Relationship(back_populates="team_ownerships")
    owner: "Member" = Relationship(back_populates="team_ownerships")


# For creating team ownerships (request body)
class TeamOwnershipCreate(TeamOwnershipBase):
    pass


# For reading team ownerships (response)
class TeamOwnershipPublic(TeamOwnershipBase):
    id: uuid.UUID
    created_at: datetime

    # Nested objects with related data
    owner: "MemberPublic"
    team: "TeamPublic"


# For updating team ownerships (request body)
class TeamOwnershipUpdate(SQLModel):
    auction_price: Optional[Decimal] = None
