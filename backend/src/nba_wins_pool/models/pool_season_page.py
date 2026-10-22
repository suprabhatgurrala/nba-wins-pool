from typing import List

from sqlmodel import SQLModel

from nba_wins_pool.models.auction import Auction
from nba_wins_pool.models.pool import Pool, PoolOverview
from nba_wins_pool.models.pool_season import PoolSeasonResponse
from nba_wins_pool.models.roster import Roster


class PoolSeasonPage(SQLModel):
    """Everything the season page reads from the database, in one response."""

    pool: Pool
    seasons: List[PoolSeasonResponse]
    overview: PoolOverview
    rosters: List[Roster]
    auctions: List[Auction]
