import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship, SQLModel

from nba_wins_pool.utils.time import utc_now

if TYPE_CHECKING:
    from .member import Member
    from .team_ownership import TeamOwnership


# Base model with shared fields
class PoolBase(SQLModel):
    slug: str = Field(max_length=10)
    name: str = Field(max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    rules: Optional[str] = Field(default=None, max_length=500)


# Database model
class Pool(PoolBase, table=True):
    """Represents a wins pool/league"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(unique=True, max_length=10, index=True)
    season: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)

    # Relationships
    team_ownerships: List["TeamOwnership"] = Relationship()
    members: List["Member"] = Relationship()


# For creating pools (request body)
class PoolCreate(PoolBase):
    pass


# For updating pools (request body)
class PoolUpdate(SQLModel):
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[str] = None
