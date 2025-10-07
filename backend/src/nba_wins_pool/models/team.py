import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class LeagueSlug(str, Enum):
    NBA = "nba"


class Team(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    league_slug: LeagueSlug = Field(index=True)
    external_id: str = Field(index=True)
    name: str
    abbreviation: str = Field(max_length=10)
    logo_url: str
    created_at: datetime = Field(default_factory=utc_now)


class TeamCreate(SQLModel):
    league_slug: LeagueSlug
    external_id: str
    name: str
    abbreviation: str
    logo_url: str
