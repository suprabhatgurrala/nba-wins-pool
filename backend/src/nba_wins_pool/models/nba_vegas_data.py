import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class NBAVegasData(SQLModel, table=True):
    """Stores NBA Vegas odds and projections for teams."""

    __tablename__ = "nba_vegas_data"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    season: SeasonStr = Field(index=True)
    fetched_at: datetime = Field(default_factory=utc_now, index=True)
    team_id: uuid.UUID = Field(foreign_key="team.id", index=True)

    # Regular season wins projection
    reg_season_wins: Decimal = Field(decimal_places=2)

    # Team name from the source
    team_name: str = Field(max_length=100)

    # Odds in American format (e.g., -110, +150)
    over_wins_odds: Optional[int] = None
    under_wins_odds: Optional[int] = None

    # Probability percentages
    make_playoffs_odds: Optional[int] = None
    miss_playoffs_odds: Optional[int] = None
    win_conference_odds: Optional[int] = None
    win_finals_odds: Optional[int] = None

    # Metadata
    source: str = Field(max_length=100, default="unknown")

    __table_args__ = (UniqueConstraint("season", "team_id", "fetched_at", name="uq_vegas_data_season_team_fetched"),)


class NBAVegasDataCreate(SQLModel):
    """Schema for creating new NBA Vegas data records."""

    season: SeasonStr
    team_id: uuid.UUID
    team_name: str = Field(max_length=100)
    fetched_at: datetime
    reg_season_wins: Decimal = Field(decimal_places=1)
    over_wins_odds: Optional[int] = None
    under_wins_odds: Optional[int] = None
    make_playoffs_odds: Optional[int] = None
    miss_playoffs_odds: Optional[int] = None
    win_conference_odds: Optional[int] = None
    win_finals_odds: Optional[int] = None
    source: str = Field(max_length=100, default="unknown")
