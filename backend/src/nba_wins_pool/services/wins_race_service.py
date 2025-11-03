from typing import Any
from uuid import UUID

from fastapi import Depends

from nba_wins_pool.repositories.roster_repository import (
    RosterRepository,
    get_roster_repository,
)
from nba_wins_pool.repositories.roster_slot_repository import (
    RosterSlotRepository,
    get_roster_slot_repository,
)
from nba_wins_pool.repositories.team_repository import (
    TeamRepository,
    get_team_repository,
)
from nba_wins_pool.services.nba_data_service import (
    NbaDataService,
    get_nba_data_service,
)
from nba_wins_pool.services.pool_season_service import (
    PoolSeasonService,
    get_pool_season_service,
)
from nba_wins_pool.types.season_str import SeasonStr

UNDRAFTED_ROSTER_NAME = "Undrafted"

# Season milestones
# TODO: Move to database table for better management
SEASON_MILESTONES = {
    "2024-25": [
        {"slug": "all_star_break_start", "date": "2025-02-14", "description": "All-Star Break"},
        {"slug": "regular_season_end", "date": "2025-04-13", "description": "Regular Season Ends"},
        {"slug": "playoffs_start", "date": "2025-04-19", "description": "Playoffs Start"},
    ],
    # Add future seasons as needed
}


class WinsRaceService:
    def __init__(
        self,
        roster_repository: RosterRepository,
        roster_slot_repository: RosterSlotRepository,
        team_repository: TeamRepository,
        nba_data_service: NbaDataService,
        pool_season_service: PoolSeasonService,
    ) -> None:
        self.roster_repository = roster_repository
        self.roster_slot_repository = roster_slot_repository
        self.team_repository = team_repository
        self.nba_data_service = nba_data_service
        self.pool_season_service = pool_season_service

    async def get_wins_race(self, pool_id: UUID, season: SeasonStr) -> dict[str, Any]:
        """Generate cumulative wins time series data for each roster."""
        game_df = await self.nba_data_service.get_game_data(season)

        mappings = await self.pool_season_service.get_team_roster_mappings(
            pool_id=pool_id,
            season=season,
            undrafted_name=UNDRAFTED_ROSTER_NAME,
        )
        teams_df = mappings.teams_df
        roster_names = mappings.roster_names

        roster_metadata = self._build_roster_metadata(roster_names)
        milestones_metadata = self._load_milestones(season)

        # Short-circuit if no teams in database or no game data
        if teams_df.empty or game_df.empty:
            return {
                "data": [],
                "metadata": {
                    "rosters": roster_metadata,
                    "milestones": milestones_metadata,
                },
            }

        for col in ["home_team", "away_team", "winning_team", "losing_team"]:
            roster_col = col.replace("_team", "_roster")
            game_df[roster_col] = game_df[col].map(teams_df["roster_name"]).fillna(UNDRAFTED_ROSTER_NAME)

        game_df["date"] = game_df["date_time"].dt.date

        roster_totals = game_df.groupby(["date", "winning_roster"]).count()["game_id"].rename("wins")
        timeseries_df = roster_totals.sort_index(ascending=True).cumsum().reset_index()

        result_data = timeseries_df[["date", "roster", "wins"]].to_dict("records")

        return {
            "data": result_data,
            "metadata": {
                "rosters": [{"name": roster} for roster in roster_names],
                "milestones": milestones_metadata,
            },
        }

    def _build_roster_metadata(self, roster_names: Any) -> list[dict[str, str]]:
        unique_names = sorted({name for name in roster_names if name != UNDRAFTED_ROSTER_NAME})
        return [{"name": name} for name in unique_names]

    def _load_milestones(self, season_year: str | None) -> list[dict[str, Any]]:
        """Load milestones for a given season from the SEASON_MILESTONES dictionary."""
        if not season_year:
            return []
        return SEASON_MILESTONES.get(season_year, [])


async def get_wins_race_service(
    roster_repo: RosterRepository = Depends(get_roster_repository),
    roster_slot_repo: RosterSlotRepository = Depends(get_roster_slot_repository),
    team_repo: TeamRepository = Depends(get_team_repository),
    pool_season_service: PoolSeasonService = Depends(get_pool_season_service),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
) -> WinsRaceService:
    return WinsRaceService(
        roster_repository=roster_repo,
        roster_slot_repository=roster_slot_repo,
        team_repository=team_repo,
        nba_data_service=nba_data_service,
        pool_season_service=pool_season_service,
    )
