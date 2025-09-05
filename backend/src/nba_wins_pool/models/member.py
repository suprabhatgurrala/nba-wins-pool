from datetime import datetime
import uuid

from nba_wins_pool.utils.time import utc_now
from sqlmodel import Field, SQLModel

class MemberBase(SQLModel):
    name: str


class Member(MemberBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    name: str
    budget: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)

class MemberCreate(MemberBase):
    pass
