import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint

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
    mean_rs_wins: float
    mean_po_wins: Optional[float] = Field(default=None)

    __table_args__ = (UniqueConstraint("season", "team_id", "simulated_at"),)


class SimulationRosterResult(SQLModel, table=True):
    __tablename__ = "simulation_roster_result"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    season: SeasonStr = Field(index=True)
    phase: str = Field(max_length=20)
    n_sims: int
    simulated_at: datetime = Field(default_factory=utc_now, index=True)
    roster_id: uuid.UUID = Field(foreign_key="roster.id", index=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    mean_rs_wins: float
    mean_po_wins: float
    win_pct: float

    __table_args__ = (UniqueConstraint("season", "roster_id", "simulated_at"),)
