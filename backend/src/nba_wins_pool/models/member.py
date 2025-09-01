from datetime import datetime, timezone
from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship
import uuid


# Base model with shared fields
class MemberBase(SQLModel):
    name: str


# Database model
class Member(MemberBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    team_ownerships: List["TeamOwnership"] = Relationship(back_populates="owner")


# For creating members (request body)
class MemberCreate(MemberBase):
    pass


# For reading members (response)
class MemberPublic(MemberBase):
    id: uuid.UUID
    created_at: datetime


# For updating members (request body)
class MemberUpdate(SQLModel):
    name: Optional[str] = None
