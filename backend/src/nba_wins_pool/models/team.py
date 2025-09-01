from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
import uuid


# Base model with shared fields
class TeamBase(SQLModel):
    slug: str = Field(max_length=3)
    nba_id: int
    name: Optional[str] = None
    logo_url: Optional[str] = None


# Database model
class Team(TeamBase, table=True):
    """NBA Team information"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=3, unique=True, index=True)
    nba_id: int = Field(unique=True, index=True)

    # Relationships
    team_ownerships: List["TeamOwnership"] = Relationship(back_populates="team")


# For creating teams (request body)
class TeamCreate(TeamBase):
    pass


# For reading teams (response)
class TeamPublic(TeamBase):
    id: uuid.UUID


# For updating teams (request body)
class TeamUpdate(SQLModel):
    slug: Optional[str] = None
    name: Optional[str] = None
    logo_url: Optional[str] = None
