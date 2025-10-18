import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class Pool(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=20, index=True, unique=True)
    name: str = Field(max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)


class PoolCreate(SQLModel):
    slug: str = Field(max_length=20)
    name: str = Field(max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)


class PoolUpdate(SQLModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)


class PoolListItemSeason(BaseModel):
    """Minimal season info for pool list responses"""
    id: uuid.UUID
    season: SeasonStr


class PoolListItem(BaseModel):
    """Pool with its associated seasons for list responses"""
    id: uuid.UUID
    slug: str
    name: str
    description: Optional[str]
    created_at: datetime
    seasons: List[PoolListItemSeason] = []


class PoolRosterTeamOverview(SQLModel):
    id: uuid.UUID
    name: str
    created_at: datetime


class PoolRosterSlotOverview(SQLModel):
    id: uuid.UUID
    name: str
    team: PoolRosterTeamOverview
    created_at: datetime


class PoolRosterOverview(SQLModel):
    id: uuid.UUID
    season: SeasonStr
    name: str
    slots: List[PoolRosterSlotOverview]
    created_at: datetime


class PoolOverview(SQLModel):
    id: uuid.UUID
    slug: str
    name: str
    season: SeasonStr
    description: Optional[str]
    rules: Optional[str]  # Fetched from PoolSeason
    rosters: List[PoolRosterOverview]
    created_at: datetime
