import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class Roster(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True, ondelete="CASCADE")
    season: SeasonStr = Field(index=True)
    name: str = Field(min_length=1, max_length=100)
    created_at: datetime = Field(default_factory=utc_now)


class RosterCreate(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    pool_id: uuid.UUID
    season: SeasonStr


class RosterUpdate(SQLModel):
    name: str = Field(min_length=1, max_length=100)


class RosterResponse(Roster):
    pass
