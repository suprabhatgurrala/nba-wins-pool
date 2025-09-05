import pytest
import pandas as pd
from datetime import date
from typing import Tuple
from zoneinfo import ZoneInfo

from nba_wins_pool.nba_data import NBAGameStatus


@pytest.fixture
def mock_game_data() -> Tuple[pd.DataFrame, date, str]:
    """
    Creates a simplified DataFrame with mock NBA game data.
    Returns the same format as get_game_data: (DataFrame, date, season_year)
    """
    # Create a simple base DataFrame with enough teams to pass the tests
    all_teams = [
        "ATL",
        "BOS",
        "BKN",
        "CHA",
        "CHI",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GSW",
        "HOU",
        "IND",
        "LAC",
        "LAL",
        "MEM",
        "MIA",
        "MIL",
        "MIN",
        "NOP",
        "NYK",
        "OKC",
        "ORL",
        "PHI",
        "PHX",
        "POR",
        "SAC",
        "SAS",
        "TOR",
        "UTA",
        "WAS",
    ]

    # Create completed games to establish win records
    rows = []
    game_date = date(2024, 10, 1)
    timestamp = pd.Timestamp(game_date.strftime("%Y-%m-%d") + " 19:00:00", tz=ZoneInfo("US/Eastern"))

    # Create game data with all 30 teams
    for i in range(0, len(all_teams), 2):
        if i + 1 < len(all_teams):
            home_team = all_teams[i]
            away_team = all_teams[i + 1]

            rows.append(
                {
                    "date_time": timestamp,
                    "home_team": home_team,
                    "home_score": 110,
                    "away_team": away_team,
                    "away_score": 100,
                    "status_text": "Final",
                    "status": NBAGameStatus.FINAL,
                    "winning_team": home_team,
                    "losing_team": away_team,
                }
            )

    # Create DataFrame with rows
    df = pd.DataFrame(rows)

    # Owner mapping that matches expected test counts
    sg_owner_map = {
        "ATL": "Sharan",
        "BOS": "Sharan",
        "BKN": "Sharan",
        "CHA": "Sharan",
        "CHI": "Sharan",
        "CLE": "Josiah",
        "DAL": "Josiah",
        "DEN": "Josiah",
        "DET": "Josiah",
        "GSW": "Josiah",
        "HOU": "Ejnar",
        "IND": "Ejnar",
        "LAC": "Ejnar",
        "LAL": "Ejnar",
        "MEM": "Ejnar",
        "MIA": "Rishi",
        "MIL": "Rishi",
        "MIN": "Rishi",
        "NOP": "Rishi",
        "NYK": "Rishi",
        "OKC": "Sup",
        "ORL": "Sup",
        "PHI": "Sup",
        "PHX": "Sup",
        "POR": "Sup",
        "SAC": "Kartik",
        "SAS": "Kartik",
        "TOR": "Kartik",
        "UTA": "Kartik",
        "WAS": "Undrafted",
    }

    kk_owner_map = {
        "ATL": "Sarith",
        "BOS": "Sarith",
        "BKN": "Sarith",
        "CHA": "Sarith",
        "CHI": "Sarith",
        "CLE": "Irfan",
        "DAL": "Irfan",
        "DEN": "Irfan",
        "DET": "Irfan",
        "GSW": "Irfan",
        "HOU": "Kalhan",
        "IND": "Kalhan",
        "LAC": "Kalhan",
        "LAL": "Kalhan",
        "MEM": "Kalhan",
        "MIA": "Pranav",
        "MIL": "Pranav",
        "MIN": "Pranav",
        "NOP": "Pranav",
        "NYK": "Pranav",
        "OKC": "Ashwin",
        "ORL": "Ashwin",
        "PHI": "Ashwin",
        "PHX": "Ashwin",
        "POR": "Ashwin",
        "SAC": "Arjun",
        "SAS": "Arjun",
        "TOR": "Arjun",
        "UTA": "Arjun",
        "WAS": "Arjun",
    }

    # Add owner information for both pools
    df["sg_home_owner"] = df["home_team"].map(sg_owner_map)
    df["sg_away_owner"] = df["away_team"].map(sg_owner_map)
    df["sg_winning_owner"] = df["winning_team"].map(sg_owner_map)
    df["sg_losing_owner"] = df["losing_team"].map(sg_owner_map)

    df["kk_home_owner"] = df["home_team"].map(kk_owner_map)
    df["kk_away_owner"] = df["away_team"].map(kk_owner_map)
    df["kk_winning_owner"] = df["winning_team"].map(kk_owner_map)
    df["kk_losing_owner"] = df["losing_team"].map(kk_owner_map)

    # Set today's date and season year
    today_date = date(2024, 10, 16)
    season_year = "2024-25"

    return df, today_date, season_year


@pytest.fixture
def mock_get_game_data(monkeypatch, mock_game_data):
    """Patch the get_game_data function to return mock data"""

    def _mock_get_game_data(pool_slug):
        df, today_date, season_year = mock_game_data

        # Filter to only include columns needed for this pool
        result_df = df.copy()
        # Map columns to the expected output format
        result_df["home_owner"] = result_df[f"{pool_slug}_home_owner"]
        result_df["away_owner"] = result_df[f"{pool_slug}_away_owner"]
        result_df["winning_owner"] = result_df[f"{pool_slug}_winning_owner"]
        result_df["losing_owner"] = result_df[f"{pool_slug}_losing_owner"]

        # Keep only the necessary columns
        cols_to_keep = [
            "date_time",
            "home_team",
            "home_score",
            "away_team",
            "away_score",
            "status_text",
            "status",
            "winning_team",
            "losing_team",
            "home_owner",
            "away_owner",
            "winning_owner",
            "losing_owner",
        ]
        result_df = result_df[cols_to_keep]

        return result_df, today_date, season_year

    # Patch the module function directly
    import nba_wins_pool.nba_data

    monkeypatch.setattr(nba_wins_pool.nba_data, "get_game_data", _mock_get_game_data)
    return _mock_get_game_data
