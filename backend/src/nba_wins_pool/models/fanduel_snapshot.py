import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class FanDuelSnapshot(SQLModel, table=True):
    """Raw FanDuel futures response, archived once per day.

    Each day keeps its fullest fetch (most populated markets), so a fetch taken mid-game,
    when FanDuel suspends or pulls markets, doesn't overwrite a complete one.

    Write-only archive: nothing reads it at runtime; the parsed values live in nba_projections.
    """

    __tablename__ = "fanduel_snapshot"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    season: Optional[str] = Field(default=None, index=True)
    projection_date: date = Field(index=True)
    fetched_at: datetime = Field(default_factory=utc_now)
    populated_markets: int = Field(default=0)
    futures_response: Optional[dict] = Field(sa_column=Column(JSONB(none_as_null=True)), default=None)
