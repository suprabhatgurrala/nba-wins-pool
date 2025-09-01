from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
import uuid


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
    created_at: datetime = Field(default_factory=datetime.now)

    # Relationships
    team_ownerships: List["TeamOwnership"] = Relationship(back_populates="pool")
    milestones: List["SeasonMilestone"] = Relationship(back_populates="pool")


# For creating pools (request body)
class PoolCreate(PoolBase):
    pass


# For reading pools (response)
class PoolPublic(PoolBase):
    id: uuid.UUID


# For updating pools (request body)
class PoolUpdate(SQLModel):
    name: Optional[str]
    description: Optional[str]
    rules: Optional[str]
