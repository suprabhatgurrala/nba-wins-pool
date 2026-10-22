import uuid
from datetime import datetime

from sqlmodel import Field, Index, SQLModel

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class SimulationRun(SQLModel, table=True):
    """One hourly simulation; its per-team and per-roster results reference it."""

    __tablename__ = "simulation_run"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    season: SeasonStr
    phase: str = Field(max_length=20)
    n_sims: int
    simulated_at: datetime = Field(default_factory=utc_now)

    __table_args__ = (Index("ix_simulation_run_season_simulated_at", "season", "simulated_at"),)


class SimulationTeamResult(SQLModel, table=True):
    __tablename__ = "simulation_team_result"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="simulation_run.id", index=True, ondelete="CASCADE")
    team_id: uuid.UUID = Field(foreign_key="team.id", index=True)
    power_rating: float
    current_wins: float
    projected_wins: float
    vegas_odds_fetched_at: datetime | None = Field(default=None)
    preseason_rating_sd: float | None = Field(default=None)
    playoff_adjustment: float | None = Field(default=None)
    ratings_through: datetime | None = Field(default=None)


class SimulationRosterResult(SQLModel, table=True):
    __tablename__ = "simulation_roster_result"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="simulation_run.id", index=True, ondelete="CASCADE")
    roster_id: uuid.UUID = Field(foreign_key="roster.id", index=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    win_pct: float
