import uuid
from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class MemberBase(SQLModel):
    name: str = Field(min_length=1, max_length=100)


class Member(MemberBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    budget: Decimal = Field(default=Decimal("0.00"))
    created_at: datetime = Field(default_factory=utc_now)


class MemberCreate(MemberBase):
    pass
