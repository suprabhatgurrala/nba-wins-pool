from datetime import date, timedelta
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.team import LeagueSlug
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
from nba_wins_pool.repositories.simulation_results_repository import (
    SimulationResultsRepository,
    get_simulation_results_repository,
)
from nba_wins_pool.repositories.team_repository import (
    TeamRepository,
    get_team_repository,
)
from nba_wins_pool.services.auction_valuation_service import AuctionValuationService, get_auction_valuation_service
from nba_wins_pool.services.nba_data_service import (
    NbaDataService,
    NBAGameStatus,
    get_nba_data_service,
)
from nba_wins_pool.services.pool_season_service import (
    PoolSeasonService,
    get_pool_season_service,
)
from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.safe_cast import safe_int, safe_str

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
        auction_valuation_service: AuctionValuationService,
        simulation_results_repository: SimulationResultsRepository,
    ):
        self.db_session = db_session
        self.pool_repository = pool_repository
        self.roster_repository = roster_repository
        self.roster_slot_repository = roster_slot_repository
        self.team_repository = team_repository
        self.nba_data_service = nba_data_service
        self.pool_season_service = pool_season_service
        self.auction_valuation_service = auction_valuation_service
        self.simulation_results_repository = simulation_results_repository

    async def get_leaderboard(self, pool_id: UUID, season: SeasonStr) -> dict[str, list[dict[str, Any]]]:
        """Generate leaderboard with roster and team-level stats.

        Args:
            pool_id: UUID of the pool
            season: Season string in format YYYY-YY (e.g., "2024-25")

        Returns:
            Dict with keys "roster" and "team" containing leaderboard data
        """
        current_season = self.nba_data_service.get_current_season()
        game_df = await self.nba_data_service.get_game_data(season)

        # Handle empty games case
        scoreboard_date = None
        if not game_df.empty:
            scoreboard_date = self.nba_data_service.get_scoreboard_date(season)

        if season == current_season:
            (
                expected_wins_df,
                projection_date,
                projection_source,
            ) = await self.auction_valuation_service.get_expected_wins(season)
            expected_wins = expected_wins_df.set_index("abbreviation")["expected_wins"]
        else:
            expected_wins = None

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

        team_breakdown_df = self._build_team_breakdown(game_df, teams_df)

        # Merge team metadata (logo_url, auction_price) in one operation
        team_breakdown_df = team_breakdown_df.merge(
            teams_df[["logo_url", "auction_price", "abbreviation"]], left_on="team", right_index=True, how="left"
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

        sort_order = ["wins", "losses"]
        ascending = [False, True]
        # Compute current expected wins
        if expected_wins is not None and expected_wins.notna().all():
            team_breakdown_df["expected_wins"] = team_breakdown_df["abbreviation"].map(expected_wins)
            sort_order.append("expected_wins")
            ascending.append(False)

        # Sort teams by record
        team_breakdown_df = team_breakdown_df.sort_values(by=sort_order, ascending=ascending)

        # Preserve external IDs and map display names for frontend compatibility
        team_breakdown_df["team_external_id"] = team_breakdown_df["team"].astype(int)
        team_breakdown_df = team_breakdown_df.merge(
            teams_df[["team_name"]], left_on="team_external_id", right_index=True, how="left"
        )
        team_breakdown_df["team"] = team_breakdown_df["team_name"]
        team_breakdown_df = team_breakdown_df.drop(columns=["team_name"])

        # Generate roster-level standings
        roster_standings_df = self._compute_roster_standings(team_breakdown_df)

        # Attach total auction prices per roster (skip if all values are None)
        auction_totals = team_breakdown_df.dropna(subset=["auction_price"]).groupby("name")["auction_price"].sum()
        roster_standings_df["auction_price"] = roster_standings_df["name"].map(auction_totals)

        # Apply simulation overrides if available
        sim_last_updated = None
        sim_roster_results = await self.simulation_results_repository.get_latest_roster_results(season, pool_id)
        sim_team_results = await self.simulation_results_repository.get_latest_team_results(season)

        # Set team-level expected_wins from simulation, then derive roster expected_wins by summing
        if sim_team_results:
            nba_teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
            team_id_to_abbrev = {t.id: t.abbreviation for t in nba_teams}
            sim_by_abbrev = {
                team_id_to_abbrev[r.team_id]: r.projected_wins
                for r in sim_team_results
                if r.team_id in team_id_to_abbrev
            }
            team_breakdown_df["expected_wins"] = team_breakdown_df["abbreviation"].map(sim_by_abbrev)
            roster_proj_wins = team_breakdown_df.groupby("name")["expected_wins"].sum()
            roster_standings_df["expected_wins"] = roster_standings_df["name"].map(roster_proj_wins)
        else:
            team_breakdown_df.drop(columns=["expected_wins"], errors="ignore", inplace=True)

        if sim_roster_results:
            rosters = await self.roster_repository.get_all(pool_id=pool_id)
            roster_id_to_name = {r.id: r.name for r in rosters if r.season == season}
            sim_by_name = {
                roster_id_to_name[r.roster_id]: r for r in sim_roster_results if r.roster_id in roster_id_to_name
            }
            if sim_by_name:
                roster_standings_df["win_probability"] = roster_standings_df["name"].map(
                    {name: r.win_pct for name, r in sim_by_name.items()}
                )
                # Re-sort with sim expected_wins, keeping Undrafted at end
                undrafted_mask = roster_standings_df["name"] == UNDRAFTED_ROSTER_NAME
                sort_cols = ["wins", "losses"]
                ascending = [False, True]
                if "expected_wins" in roster_standings_df.columns:
                    sort_cols.append("expected_wins")
                    ascending.append(False)
                roster_standings_df = pd.concat(
                    [
                        roster_standings_df[~undrafted_mask].sort_values(by=sort_cols, ascending=ascending),
                        roster_standings_df[undrafted_mask],
                    ]
                ).reset_index(drop=True)
                sim_last_updated = sim_roster_results[0].simulated_at.isoformat()

        # A team is eliminated when its projected wins equals its current wins (no games remaining)
        if "expected_wins" in team_breakdown_df.columns:
            team_breakdown_df["eliminated"] = (
                team_breakdown_df["expected_wins"] - team_breakdown_df["wins"]
            ).abs() < 0.00001
        else:
            team_breakdown_df["eliminated"] = False

        # A roster is eliminated when all its teams are eliminated
        roster_eliminated = team_breakdown_df.groupby("name")["eliminated"].all()
        roster_standings_df["eliminated"] = roster_standings_df["name"].map(roster_eliminated).fillna(False)

        # Sort teams by roster standings order
        ordered_rosters = roster_standings_df["name"].tolist()
        team_breakdown_df = team_breakdown_df.set_index("name", drop=False).loc[ordered_rosters]

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
            "sim_last_updated": sim_last_updated,
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

    async def get_today_games(self, pool_id: UUID, season: SeasonStr, game_date: date | None = None) -> dict:
        """Get games for a given date (defaults to the current scoreboard date) with pool ownership info.

        Args:
            pool_id: UUID of the pool
            season: Season string in format YYYY-YY (e.g., "2024-25")
            game_date: Date to fetch games for. Defaults to today's scoreboard date.

        Returns:
            Dict with "date", "scoreboard_date" (ISO date strings) and "games" list
        """
        game_df = await self.nba_data_service.get_game_data(season)

        if game_df.empty:
            return {"date": None, "scoreboard_date": None, "game_dates": [], "games": []}

        scoreboard_date = self.nba_data_service.get_scoreboard_date(season)
        view_date = game_date or scoreboard_date
        today_df = game_df[game_df["date_time"].dt.date == view_date].copy()
        game_dates = sorted({d.isoformat() for d in game_df["date_time"].dt.date})

        if today_df.empty:
            return {
                "date": view_date.isoformat(),
                "scoreboard_date": scoreboard_date.isoformat(),
                "game_dates": game_dates,
                "games": [],
            }

        # For dates other than today, re-fetch the gamecardfeed for that date to get accurate status/scores.
        # Today's overlay is already baked into game_df by _build_current_schedule_df.
        if view_date != scoreboard_date:
            today_df = self.nba_data_service.apply_gamecardfeed_overlay_for_date(today_df, view_date)

        mappings = await self.pool_season_service.get_team_roster_mappings(
            pool_id=pool_id,
            season=season,
            undrafted_name=UNDRAFTED_ROSTER_NAME,
        )
        teams_df = mappings.teams_df

        team_breakdown_df = self._build_team_breakdown(game_df, teams_df)

        # roster_name -> total season wins
        roster_standings_df = self._compute_roster_standings(team_breakdown_df)
        roster_season_wins: dict[str, int] = {
            row["name"]: int(row["wins"]) for _, row in roster_standings_df.iterrows()
        }

        # roster_name -> (today_wins, today_losses) from completed games on scoreboard_date
        today_record_df = self._compute_record(game_df, scoreboard_date, offset=0)
        today_roster_record: dict[str, tuple[int, int]] = {
            row["name"]: (int(row["wins"]), int(row["losses"]))
            for _, row in today_record_df.groupby("name")[["wins", "losses"]].sum().reset_index().iterrows()
        }

        status_sort = {NBAGameStatus.INGAME: 0, NBAGameStatus.PREGAME: 1, NBAGameStatus.FINAL: 2}
        odds_map = self.nba_data_service.get_sportsbook_game_win_probabilities()

        result = []
        for _, game in today_df.iterrows():
            home_id = safe_int(game["home_team"])
            away_id = safe_int(game["away_team"])
            odds = odds_map.get(safe_str(game.get("game_code")))
            period = safe_int(game.get("period")) or 0
            odds_suspended = odds is not None and odds.get("both_suspended") and period >= 4
            result.append(
                {
                    "game_id": game["game_id"],
                    "game_url": game["game_url"] if not pd.isna(game.get("game_url")) else None,
                    "status": int(game["status"]),
                    "status_text": safe_str(game["status_text"]),
                    "game_clock": safe_str(game["game_clock"]),
                    "game_time": game["date_time"].tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S")
                    if pd.notna(game.get("date_time"))
                    and not (game["date_time"].hour == 0 and game["date_time"].minute == 0)
                    else None,
                    "arena_name": game.get("arena_name") or None,
                    "arena_city": game.get("arena_city") or None,
                    "arena_state": game.get("arena_state") or None,
                    "national_broadcaster_logos": game.get("national_broadcaster_logos") or None,
                    "game_label": game.get("game_label") or None,
                    "series_game_text": game.get("series_game_text") or None,
                    "series_status_text": game.get("series_status_text") or None,
                    "if_necessary": bool(game.get("if_necessary", False)),
                    "home_seed": safe_int(game.get("home_seed")),
                    "away_seed": safe_int(game.get("away_seed")),
                    "home_win_pct": odds["home"] if odds and not odds_suspended else None,
                    "away_win_pct": odds["away"] if odds and not odds_suspended else None,
                    **self._build_game_side("home", game, home_id, teams_df, roster_season_wins, today_roster_record),
                    **self._build_game_side("away", game, away_id, teams_df, roster_season_wins, today_roster_record),
                }
            )

        result.sort(key=lambda g: (status_sort.get(g["status"], 99), g["game_id"] or ""))
        game_dates = sorted({d.isoformat() for d in game_df["date_time"].dt.date})
        return {
            "date": view_date.isoformat(),
            "scoreboard_date": scoreboard_date.isoformat(),
            "game_dates": game_dates,
            "games": result,
        }

    def _build_team_breakdown(self, game_df: pd.DataFrame, teams_df: pd.DataFrame) -> pd.DataFrame:
        """Map roster columns onto game_df and compute wins/losses for every team.

        Returns a DataFrame with columns: name, team (team_id), wins, losses.
        Every team in teams_df is guaranteed to appear with at least a 0-0 record.
        """
        for col in ["home_team", "away_team", "winning_team", "losing_team"]:
            game_df[col.replace("_team", "_roster")] = game_df[col].map(teams_df["roster_name"], na_action="ignore")

        team_breakdown_df = self._compute_record(game_df)
        all_teams_df = pd.DataFrame(
            [
                {"name": row["roster_name"], "team": team_id, "wins": 0, "losses": 0}
                for team_id, row in teams_df.iterrows()
            ]
        )
        team_breakdown_df = pd.concat([all_teams_df, team_breakdown_df], ignore_index=True)
        team_breakdown_df = team_breakdown_df.groupby(["name", "team"], as_index=False).agg(
            {"wins": "sum", "losses": "sum"}
        )
        team_breakdown_df["wins"] = team_breakdown_df["wins"].astype(int)
        team_breakdown_df["losses"] = team_breakdown_df["losses"].astype(int)
        return team_breakdown_df

    def _build_roster_info(self, roster_standings_df: pd.DataFrame) -> dict[str, dict]:
        """Build a roster-name-keyed lookup of wins, losses, rank, and rank_tied."""
        rank_counts = roster_standings_df["rank"].value_counts()
        return {
            row["name"]: {
                "wins": int(row["wins"]),
                "losses": int(row["losses"]),
                "rank": int(row["rank"]) if not pd.isna(row["rank"]) else None,
                "rank_tied": bool(rank_counts.get(row["rank"], 0) > 1) if not pd.isna(row["rank"]) else False,
            }
            for _, row in roster_standings_df.iterrows()
        }

    def _build_game_side(
        self,
        side: str,
        game,
        team_id: int | None,
        teams_df: pd.DataFrame,
        roster_season_wins: dict[str, int],
        today_roster_record: dict[str, tuple[int, int]],
    ) -> dict:
        """Build the home or away half of a today-game dict."""
        team_info = teams_df.loc[team_id] if team_id is not None and team_id in teams_df.index else None
        owner = (
            team_info["roster_name"]
            if team_info is not None and team_info["roster_name"] != UNDRAFTED_ROSTER_NAME
            else None
        )
        today_rec = today_roster_record.get(owner) if owner else None
        return {
            f"{side}_team_id": team_id,
            f"{side}_team_name": team_info["team_name"] if team_info is not None else safe_str(game[f"{side}_tricode"]),
            f"{side}_team_tricode": safe_str(game[f"{side}_tricode"]),
            f"{side}_team_logo_url": team_info["logo_url"] if team_info is not None else None,
            f"{side}_score": safe_int(game[f"{side}_score"]),
            f"{side}_owner": owner,
            f"{side}_owner_wins": roster_season_wins.get(owner) if owner else None,
            f"{side}_owner_today_wins": today_rec[0] if today_rec is not None else None,
            f"{side}_owner_today_losses": today_rec[1] if today_rec is not None else None,
        }

    def _compute_roster_standings(self, team_breakdown_df: pd.DataFrame) -> pd.DataFrame:
        """Compute roster-level standings from team breakdown.

        Args:
            team_breakdown_df: DataFrame with team-level stats

        Returns:
            DataFrame with roster-level standings including rank
        """
        # Group by roster name and sum stats
        sort_cols = ["wins", "losses"]
        ascending = [False, True]

        if "expected_wins" in team_breakdown_df.columns:
            sort_cols.append("expected_wins")
            ascending.append(False)

        roster_standings_df = (
            team_breakdown_df.groupby("name").agg("sum").sort_values(by=sort_cols, ascending=ascending)
        ).select_dtypes(include=np.number)

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
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
    auction_valuation_service: AuctionValuationService = Depends(get_auction_valuation_service),
    simulation_results_repository: SimulationResultsRepository = Depends(get_simulation_results_repository),
    db_session: AsyncSession = Depends(get_db_session),
) -> LeaderboardService:
    return LeaderboardService(
        db_session=db_session,
        pool_repository=pool_repo,
        roster_repository=roster_repo,
        roster_slot_repository=roster_slot_repo,
        team_repository=team_repo,
        nba_data_service=nba_data_service,
        pool_season_service=pool_season_service,
        auction_valuation_service=auction_valuation_service,
        simulation_results_repository=simulation_results_repository,
    )
