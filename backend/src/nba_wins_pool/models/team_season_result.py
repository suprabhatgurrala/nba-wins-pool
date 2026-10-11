import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class TeamSeasonResult(SQLModel, table=True):
    """A team's actual NBA record for a completed season, shared across all pools that include it."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    team_id: uuid.UUID = Field(foreign_key="team.id", index=True, ondelete="CASCADE")
    season: SeasonStr = Field(index=True)
    actual_wins: int
    actual_losses: int
    computed_at: datetime = Field(default_factory=utc_now)
