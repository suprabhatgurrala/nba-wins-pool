import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


# Base model with shared fields
class TeamBase(SQLModel):
    slug: str = Field(max_length=3)
    external_id: str
    name: Optional[str] = None
    logo_url: Optional[str] = None


# Database model
class Team(TeamBase, table=True):
    """NBA Team information"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=3, unique=True, index=True)
    external_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)


# For creating teams (request body)
class TeamCreate(TeamBase):
    pass
