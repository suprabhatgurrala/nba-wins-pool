import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Field, SQLModel

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class PoolTeamSeasonResult(SQLModel, table=True):
    """A pool's ownership/valuation of a team for a completed season.

    Materialized once a season is over so history/leaderboard reads for past seasons don't need
    to replay the live game-schedule-based leaderboard computation. Actual win/loss records live
    on TeamSeasonResult (shared across pools); this table holds the pool-specific data: who drafted
    the team, what it was projected to win/cost before the draft, and what it actually cost.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True, ondelete="CASCADE")
    pool_season_id: uuid.UUID = Field(foreign_key="poolseason.id", index=True, ondelete="CASCADE")
    season: SeasonStr = Field(index=True)
    team_id: uuid.UUID = Field(foreign_key="team.id", index=True, ondelete="CASCADE")
    roster_id: uuid.UUID = Field(foreign_key="roster.id", index=True, ondelete="CASCADE")
    roster_name: str

    projected_wins: Optional[float] = Field(default=None)
    projected_price: Optional[Decimal] = Field(default=None, decimal_places=2)
    auction_price: Optional[Decimal] = Field(default=None, decimal_places=2)
    computed_at: datetime = Field(default_factory=utc_now)
