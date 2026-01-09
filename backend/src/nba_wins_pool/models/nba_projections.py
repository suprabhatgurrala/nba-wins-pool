import uuid
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class NBAProjections(SQLModel, table=True):
    """Stores NBA Vegas odds and projections for teams."""

    __tablename__ = "nba_projections"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    season: SeasonStr = Field(index=True)
    projection_date: date = Field(index=True)
    fetched_at: datetime = Field(default_factory=utc_now, index=True)
    team_id: uuid.UUID = Field(foreign_key="team.id", index=True)

    # Regular season wins projection
    reg_season_wins: Optional[float] = Field(default=None)

    # Team name from the source
    team_name: str = Field(max_length=100)

    # Odds in American format (e.g., -110, +150)
    over_wins_odds: Optional[int] = Field(default=None)
    under_wins_odds: Optional[int] = Field(default=None)
    make_playoffs_odds: Optional[int] = Field(default=None)
    miss_playoffs_odds: Optional[int] = Field(default=None)
    win_conference_odds: Optional[int] = Field(default=None)
    win_finals_odds: Optional[int] = Field(default=None)

    # Probability of making playoffs (0-1)
    over_wins_prob: Optional[float] = Field(default=None)
    make_playoffs_prob: Optional[float] = Field(default=None)
    win_conference_prob: Optional[float] = Field(default=None)
    win_finals_prob: Optional[float] = Field(default=None)

    # Metadata
    source: Optional[str] = Field(max_length=100, index=True)

    __table_args__ = (
        UniqueConstraint(
            "season", "team_id", "projection_date", "source", name="uq_projections_data_season_team_date_source"
        ),
    )


class NBAProjectionsCreate(SQLModel):
    """Schema for creating new NBA Vegas data records."""

    season: SeasonStr
    team_id: uuid.UUID
    team_name: str = Field(max_length=100)
    projection_date: date
    fetched_at: datetime
    reg_season_wins: Optional[float] = Field(default=None)
    over_wins_odds: Optional[int] = Field(default=None)
    under_wins_odds: Optional[int] = Field(default=None)
    make_playoffs_odds: Optional[int] = Field(default=None)
    miss_playoffs_odds: Optional[int] = Field(default=None)
    win_conference_odds: Optional[int] = Field(default=None)
    win_finals_odds: Optional[int] = Field(default=None)
    over_wins_prob: Optional[float] = Field(default=None)
    make_playoffs_prob: Optional[float] = Field(default=None)
    win_conference_prob: Optional[float] = Field(default=None)
    win_finals_prob: Optional[float] = Field(default=None)
    source: Optional[str] = Field(max_length=100)
