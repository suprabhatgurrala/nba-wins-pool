from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pandas as pd
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.repositories.pool_repository import (
    PoolRepository,
    get_pool_repository,
)
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
from nba_wins_pool.services.nba_data_service import NbaDataService, NBAGameStatus
from nba_wins_pool.services.pool_season_service import (
    PoolSeasonService,
    get_pool_season_service,
)
from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.season import get_current_season

UNDRAFTED_ROSTER_NAME = "Undrafted"


class LeaderboardService:
    def __init__(
        self,
        db_session: AsyncSession,
        pool_repository: PoolRepository,
        roster_repository: RosterRepository,
        roster_slot_repository: RosterSlotRepository,
        team_repository: TeamRepository,
        nba_data_service: NbaDataService,
        pool_season_service: PoolSeasonService,
    ):
        self.db_session = db_session
        self.pool_repository = pool_repository
        self.roster_repository = roster_repository
        self.roster_slot_repository = roster_slot_repository
        self.team_repository = team_repository
        self.nba_data_service = nba_data_service
        self.pool_season_service = pool_season_service

    async def get_leaderboard(self, pool_id: UUID, season: SeasonStr) -> dict[str, list[dict[str, Any]]]:
        """Generate leaderboard with roster and team-level stats.

        Args:
            pool_id: UUID of the pool
            season: Season string in format YYYY-YY (e.g., "2024-25")

        Returns:
            Dict with keys "roster" and "team" containing leaderboard data
        """
        # Fetch game data from NBA.com
        scoreboard_data, scoreboard_date = await self.nba_data_service.get_scoreboard_cached()
        schedule_data, _ = await self.nba_data_service.get_schedule_cached(scoreboard_date, season)

        # Determine if we should include today's scoreboard
        # Only include scoreboard if the requested season is the current season
        current_season = get_current_season(scoreboard_date)
        
        if season == current_season:
            # Current season: combine schedule and scoreboard data
            game_df = pd.concat([pd.DataFrame(schedule_data), pd.DataFrame(scoreboard_data)], ignore_index=True)
        else:
            # Historical season: only use schedule data
            game_df = pd.DataFrame(schedule_data)

        # Parse dates and normalize timezone (only if we have games)
        if not game_df.empty:
            game_df["date_time"] = pd.to_datetime(game_df["date_time"], utc=True).dt.tz_convert("US/Eastern")
            
            # Filter out preseason games
            # game_label values: "Preseason", empty string (regular season), "Playoffs", etc.
            if "game_label" in game_df.columns:
                game_df = game_df[game_df["game_label"].str.lower() != "preseason"]
        
        # Build mappings from database
        mappings = await self.pool_season_service.get_team_roster_mappings(
            pool_id=pool_id,
            season=season,
            undrafted_name=UNDRAFTED_ROSTER_NAME,
        )
        teams_df = mappings.teams_df
        
        # Short-circuit if no teams in database
        if teams_df.empty:
            return {"roster": [], "team": []}

        # Determine winning and losing teams for completed games (only if we have games)
        if not game_df.empty:
            game_df["winning_team"] = game_df["home_team"].where(
                (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score > game_df.away_score),
                other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
            )
            game_df["losing_team"] = game_df["home_team"].where(
                (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score < game_df.away_score),
                other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
            )

            # Map team IDs to roster names
            for col in ["home_team", "away_team", "winning_team", "losing_team"]:
                game_df[col.replace("_team", "_roster")] = game_df[col].map(teams_df["roster_name"], na_action="ignore")

        # Generate team-level breakdown
        team_breakdown_df = self._compute_record(game_df)
        
        # Add all teams with 0-0 records if they haven't played yet
        all_teams_df = pd.DataFrame([
            {"name": row["roster_name"], "team": team_id, "wins": 0, "losses": 0}
            for team_id, row in teams_df.iterrows()
        ])
        team_breakdown_df = pd.concat([all_teams_df, team_breakdown_df], ignore_index=True)
        team_breakdown_df = team_breakdown_df.groupby(["name", "team"], as_index=False).agg({
            "wins": "sum",
            "losses": "sum"
        })

        # Merge team metadata (logo_url, auction_price) in one operation
        team_breakdown_df = team_breakdown_df.merge(
            teams_df[["logo_url", "auction_price"]],
            left_on="team",
            right_index=True,
            how="left"
        )

        # Generate recent game status strings
        today_results = self._generate_result_map(game_df, scoreboard_date, teams_df)
        yesterday_results = self._generate_result_map(game_df, scoreboard_date - timedelta(days=1), teams_df)

        team_breakdown_df["today_result"] = team_breakdown_df["team"].map(today_results).fillna("")
        team_breakdown_df["yesterday_result"] = team_breakdown_df["team"].map(yesterday_results).fillna("")

        # Compute records for different time periods
        merge_cols = ["name", "team"]

        today_record = self._compute_record(game_df, scoreboard_date, offset=0)
        team_breakdown_df = team_breakdown_df.merge(
            today_record, how="left", on=merge_cols, suffixes=["", "_today"]
        ).fillna(0)

        yesterday_record = self._compute_record(game_df, scoreboard_date - timedelta(days=1), offset=0)
        team_breakdown_df = team_breakdown_df.merge(
            yesterday_record, how="left", on=merge_cols, suffixes=["", "_yesterday"]
        ).fillna(0)

        last7_record = self._compute_record(game_df, scoreboard_date, offset=7)
        team_breakdown_df = team_breakdown_df.merge(
            last7_record, how="left", on=merge_cols, suffixes=["", "_last7"]
        ).fillna(0)

        last30_record = self._compute_record(game_df, scoreboard_date, offset=30)
        team_breakdown_df = team_breakdown_df.merge(
            last30_record, how="left", on=merge_cols, suffixes=["", "_last30"]
        ).fillna(0)

        # Sort teams by record
        team_breakdown_df = team_breakdown_df.sort_values(by=["wins", "losses"], ascending=[False, True])

        # Generate roster-level standings
        roster_standings_df = self._compute_roster_standings(team_breakdown_df)

        # Attach total auction prices per roster (skip if all values are None)
        auction_totals = (
            team_breakdown_df.dropna(subset=["auction_price"])
            .groupby("name")["auction_price"]
            .sum()
        )
        roster_standings_df["auction_price"] = roster_standings_df["name"].map(auction_totals)

        # Sort teams by roster standings order
        ordered_rosters = roster_standings_df["name"].tolist()
        team_breakdown_df = team_breakdown_df.set_index("name", drop=False).loc[ordered_rosters]

        # Preserve external IDs and map display names for frontend compatibility
        team_breakdown_df["team_external_id"] = team_breakdown_df["team"].astype(int)
        team_breakdown_df = team_breakdown_df.merge(
            teams_df[["team_name"]],
            left_on="team_external_id",
            right_index=True,
            how="left"
        )
        team_breakdown_df["team"] = team_breakdown_df["team_name"]
        team_breakdown_df = team_breakdown_df.drop(columns=["team_name"])

        # Convert to dict records and handle NaN values
        roster_data = roster_standings_df.fillna("<NULL>").replace("<NULL>", None).to_dict(orient="records")
        team_data = (
            team_breakdown_df.drop(columns=["team_external_id"], errors="ignore")
            .fillna("<NULL>")
            .replace("<NULL>", None)
            .to_dict(orient="records")
        )

        return {
            "roster": roster_data,
            "team": team_data,
        }

    def _compute_record(
        self, df: pd.DataFrame, today_date: date | None = None, offset: int | None = None
    ) -> pd.DataFrame:
        """Compute wins/losses for a given set of games.

        Args:
            df: Game data DataFrame
            today_date: Optional date for filtering
            offset: Optional number of days to look back from today_date

        Returns:
            DataFrame with columns for name (roster), team, wins, and losses
        """
        # Early return if no games
        if df.empty:
            return pd.DataFrame(columns=["name", "team", "wins", "losses"])
        
        # Filter by date range if specified
        if offset is not None and today_date is not None:
            if offset == 0:
                # Only games on this specific day
                df = df[df["date_time"].dt.date == today_date]
            else:
                # Games in the last N days (excluding today)
                df = df[df["date_time"].dt.date > (today_date - pd.Timedelta(days=offset))]

        # Only count completed games
        df = df[df["status"] == NBAGameStatus.FINAL]

        if df.empty:
            return pd.DataFrame(columns=["name", "team", "wins", "losses"])

        # Count wins and losses by roster and team
        wins_df = (
            df[df["winning_team"].notna()]
            .groupby(["winning_roster", "winning_team"])
            .size()
            .reset_index(name="wins")
            .rename(columns={"winning_roster": "name", "winning_team": "team"})
        )

        losses_df = (
            df[df["losing_team"].notna()]
            .groupby(["losing_roster", "losing_team"])
            .size()
            .reset_index(name="losses")
            .rename(columns={"losing_roster": "name", "losing_team": "team"})
        )

        # Merge wins and losses
        standings = wins_df.merge(losses_df, on=["name", "team"], how="outer").fillna(0)

        # Ensure numeric types
        standings["wins"] = standings["wins"].astype(int)
        standings["losses"] = standings["losses"].astype(int)

        return standings.sort_values(by=["wins", "losses"], ascending=[False, True])

    def _generate_result_map(self, df: pd.DataFrame, target_date: date, teams_df: pd.DataFrame) -> dict[int, str]:
        """Generate status strings for games on a specific date.

        Args:
            df: Game data DataFrame
            target_date: Date to filter games
            teams_df: DataFrame with team metadata including abbreviations

        Returns:
            Dict mapping team ID to result string
        """
        results: dict[int, str] = {}
        
        # Early return if no games
        if df.empty:
            return results
        
        date_df = df[df["date_time"].dt.date == target_date]

        # Create abbreviation lookup
        team_abbrev = teams_df["abbreviation"].to_dict()

        for _, row in date_df.iterrows():
            status = row["status"]
            home_team = row["home_team"]
            away_team = row["away_team"]
            status_text = row["status_text"]
            
            # Get abbreviations, fallback to team ID if not found
            home_abbrev = team_abbrev.get(home_team, str(home_team))
            away_abbrev = team_abbrev.get(away_team, str(away_team))

            if status == NBAGameStatus.PREGAME:
                results[home_team] = f"{status_text} vs {away_abbrev}"
                results[away_team] = f"{status_text} @ {home_abbrev}"
            elif status == NBAGameStatus.INGAME:
                home_score = row["home_score"]
                away_score = row["away_score"]
                results[home_team] = f"{home_score}-{away_score}, {status_text} vs {away_abbrev}"
                results[away_team] = f"{away_score}-{home_score}, {status_text} @ {home_abbrev}"
            elif status == NBAGameStatus.FINAL:
                home_score = row["home_score"]
                away_score = row["away_score"]
                if home_score > away_score:
                    home_status = "W"
                    away_status = "L"
                else:
                    home_status = "L"
                    away_status = "W"
                results[home_team] = f"{home_status}, {home_score}-{away_score} vs {away_abbrev}"
                results[away_team] = f"{away_status}, {away_score}-{home_score} @ {home_abbrev}"

        return results

    def _compute_roster_standings(self, team_breakdown_df: pd.DataFrame) -> pd.DataFrame:
        """Compute roster-level standings from team breakdown.

        Args:
            team_breakdown_df: DataFrame with team-level stats

        Returns:
            DataFrame with roster-level standings including rank
        """
        # Group by roster name and sum stats
        roster_standings_df = (
            team_breakdown_df.groupby("name")
            .agg(
                {
                    "wins": "sum",
                    "losses": "sum",
                    "wins_today": "sum",
                    "losses_today": "sum",
                    "wins_yesterday": "sum",
                    "losses_yesterday": "sum",
                    "wins_last7": "sum",
                    "losses_last7": "sum",
                    "wins_last30": "sum",
                    "losses_last30": "sum",
                }
            )
            .sort_values(by=["wins", "losses"], ascending=[False, True])
        )

        # Move "Undrafted" to the end if present
        ordered_rosters = roster_standings_df.index.tolist()
        if UNDRAFTED_ROSTER_NAME in ordered_rosters:
            ordered_rosters.remove(UNDRAFTED_ROSTER_NAME)
            ordered_rosters.append(UNDRAFTED_ROSTER_NAME)

        # Compute ranks (excluding Undrafted)
        drafted_rosters = [r for r in ordered_rosters if r != UNDRAFTED_ROSTER_NAME]
        if drafted_rosters:
            rank_series = (
                roster_standings_df.loc[drafted_rosters]["wins"].rank(method="min", ascending=False).astype(int)
            )
        else:
            rank_series = pd.Series(dtype=int)

        # Reorder and add rank column
        roster_standings_df = roster_standings_df.reindex(ordered_rosters)
        roster_standings_df["rank"] = roster_standings_df.index.map(rank_series)
        roster_standings_df = roster_standings_df.reset_index()

        return roster_standings_df


async def get_leaderboard_service(
    pool_repo: PoolRepository = Depends(get_pool_repository),
    roster_repo: RosterRepository = Depends(get_roster_repository),
    roster_slot_repo: RosterSlotRepository = Depends(get_roster_slot_repository),
    team_repo: TeamRepository = Depends(get_team_repository),
    pool_season_service: PoolSeasonService = Depends(get_pool_season_service),
    db_session: AsyncSession = Depends(get_db_session),
) -> LeaderboardService:
    nba_data_service = NbaDataService(db_session)
    return LeaderboardService(
        db_session=db_session,
        pool_repository=pool_repo,
        roster_repository=roster_repo,
        roster_slot_repository=roster_slot_repo,
        team_repository=team_repo,
        nba_data_service=nba_data_service,
        pool_season_service=pool_season_service,
    )
