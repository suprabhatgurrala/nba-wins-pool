import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class SimulationTeamResult(SQLModel, table=True):
    __tablename__ = "simulation_team_result"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    season: SeasonStr = Field(index=True)
    phase: str = Field(max_length=20)
    n_sims: int
    simulated_at: datetime = Field(default_factory=utc_now, index=True)
    team_id: uuid.UUID = Field(foreign_key="team.id", index=True)
    power_rating: float
    current_wins: float
    projected_wins: float
    vegas_odds_fetched_at: datetime | None = Field(default=None)
    # Preseason-equivalent rating uncertainty τ₀ (points), regular season only: the next
    # run's fallback for a team whose X+ wins ladder FanDuel no longer lists
    preseason_rating_sd: float | None = Field(default=None)
    # Regular season: the playoff adjustment δ (points), reused while FanDuel's futures are stale
    playoff_adjustment: float | None = Field(default=None)
    # Regular season: latest tip-off whose result power_rating has learned from (the next run
    # updates ratings from games after it)
    ratings_through: datetime | None = Field(default=None)


class SimulationRosterResult(SQLModel, table=True):
    __tablename__ = "simulation_roster_result"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    season: SeasonStr = Field(index=True)
    phase: str = Field(max_length=20)
    n_sims: int
    simulated_at: datetime = Field(default_factory=utc_now, index=True)
    roster_id: uuid.UUID = Field(foreign_key="roster.id", index=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    win_pct: float
