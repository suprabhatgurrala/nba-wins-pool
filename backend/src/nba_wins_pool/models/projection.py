import uuid
from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, Index, SQLModel

from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class ProjectionMarket(StrEnum):
    """What a quote prices. Adding a market needs only a member here and a parser that writes it."""

    WIN_TOTAL = "win_total"
    """Regular-season wins O/U: line, de-vigged over prob, over/under odds."""
    WINS_LADDER = "wins_ladder"
    """X+ regular-season wins: line is X, prob is the raw single-sided P(wins ≥ X)."""
    MAKE_PLAYOFFS = "make_playoffs"
    """De-vigged prob, make/miss odds (ESPN: prob only)."""
    REACH_SEMIS = "reach_semis"
    REACH_CONF_FINALS = "reach_conf_finals"
    WIN_CONF = "win_conf"
    WIN_TITLE = "win_title"
    ESPN_WINS = "espn_wins"
    """ESPN BPI projected regular-season wins, in line."""
    ESPN_BPI = "espn_bpi"
    ESPN_PLAYOFF_BPI = "espn_playoff_bpi"


class ProjectionFetch(SQLModel, table=True):
    """One successful fetch from a projection source that yielded at least one quote."""

    __tablename__ = "projection_fetch"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source: str = Field(max_length=40)
    season: SeasonStr
    fetched_at: datetime = Field(default_factory=utc_now)
    quote_count: int

    __table_args__ = (Index("ix_projection_fetch_source_season_fetched_at", "source", "season", "fetched_at"),)


class MarketQuote(SQLModel, table=True):
    """One team's price in one market from one fetch; a market absent from a fetch has no row.

    ``source``, ``season`` and ``fetched_at`` repeat the fetch's, so the latest quote per team and market is one
    index lookup. They're written with the fetch and never updated.
    """

    __tablename__ = "market_quote"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    fetch_id: uuid.UUID = Field(foreign_key="projection_fetch.id", ondelete="CASCADE")
    source: str = Field(max_length=40)
    season: SeasonStr
    fetched_at: datetime
    team_id: uuid.UUID = Field(foreign_key="team.id")
    market: str = Field(max_length=40)
    line: float | None = Field(default=None)
    prob: float | None = Field(default=None)
    odds: int | None = Field(default=None)
    opp_odds: int | None = Field(default=None)

    __table_args__ = (
        Index("ix_market_quote_latest", "source", "season", "team_id", "market", "fetched_at"),
        Index("ix_market_quote_fetch_id", "fetch_id"),
    )


class QuoteCreate(SQLModel):
    """A parsed quote before it's attached to a fetch."""

    team_id: uuid.UUID
    market: ProjectionMarket
    line: float | None = None
    prob: float | None = None
    odds: int | None = None
    opp_odds: int | None = None
