import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class PoolSeason(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(index=True, foreign_key="pool.id", ondelete="CASCADE")
    season: SeasonStr = Field(index=True)
    rules: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)

    __table_args__ = (UniqueConstraint("pool_id", "season"),)


class PoolSeasonCreate(SQLModel):
    pool_id: uuid.UUID
    season: SeasonStr
    rules: Optional[str] = Field(default=None, max_length=500)


class PoolSeasonUpdate(SQLModel):
    rules: Optional[str] = Field(default=None, max_length=500)


class PoolSeasonResponse(SQLModel):
    id: uuid.UUID
    pool_id: uuid.UUID
    season: SeasonStr
    rules: Optional[str]
    created_at: datetime
