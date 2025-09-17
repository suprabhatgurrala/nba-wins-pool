from datetime import date
from typing import Callable, Tuple

import pandas as pd
import pytest
from nba_wins_pool.nba_data import NBAGameStatus, read_team_owner_data


@pytest.fixture
def mock_get_game_data() -> Callable[[str], Tuple[pd.DataFrame, date, str]]:
    """Factory fixture to generate deterministic game data for a given pool slug.

    Returns a callable that accepts pool_slug and returns a tuple of
    (game_data_df, today_date, seasonYear) consistent with nba_data.get_game_data().
    """

    def _factory(pool_slug: str):
        season_year = "2024-25"
        # team_owner_df indexed by (season, team) after read_team_owner_data
        team_owner_df = read_team_owner_data(pool_slug)
        team_to_owner = team_owner_df.loc[season_year]["owner"]  # Series: team -> owner

        teams = list(team_to_owner.index)

        # Two dates to produce multiple time points
        ts_day1 = pd.Timestamp("2024-10-10 19:00:00", tz="US/Eastern")
        ts_day2 = pd.Timestamp("2024-10-11 19:00:00", tz="US/Eastern")
        today_date = ts_day2.date()

        rows = []

        # Round 1: each team wins once against the next team in list (cyclic)
        # This ensures all teams appear as winners at least once
        for i, team in enumerate(teams):
            opponent = teams[(i + 1) % len(teams)]
            rows.append(
                {
                    "date_time": ts_day1 if i < len(teams) // 2 else ts_day2,
                    "home_team": team,
                    "home_score": 110,
                    "away_team": opponent,
                    "away_score": 100,
                    "status_text": "Final",
                    "status": NBAGameStatus.FINAL,
                    "winning_team": team,
                    "losing_team": opponent,
                    "winning_owner": team_to_owner[team],
                    "losing_owner": team_to_owner[opponent],
                }
            )

        # Round 2: each team loses once to the previous team (to ensure they appear as losers too)
        for i, team in enumerate(teams):
            opponent = teams[(i - 1) % len(teams)]
            rows.append(
                {
                    "date_time": ts_day2,
                    "home_team": opponent,
                    "home_score": 120,
                    "away_team": team,
                    "away_score": 90,
                    "status_text": "Final",
                    "status": NBAGameStatus.FINAL,
                    "winning_team": opponent,
                    "losing_team": team,
                    "winning_owner": team_to_owner[opponent],
                    "losing_owner": team_to_owner[team],
                }
            )

        game_data_df = pd.DataFrame(rows)

        return game_data_df, today_date, season_year

    return _factory
