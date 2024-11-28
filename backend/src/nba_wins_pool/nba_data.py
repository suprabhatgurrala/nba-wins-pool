import json
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import requests

nba_schedule_data_url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
nba_scoreboard_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

team_to_owner_path = Path(__file__).parent / "data"


class NBAGameStatus(Enum):
    """Enum representing possible game statuses"""

    PREGAME = 1
    INGAME = 2
    FINAL = 3


def request_helper(url: str) -> dict:
    """Helper method to perform request to a URL which returns JSON

    Args:
        url: URL to send request to

    Returns:
        a dict of the JSON response of the URL
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
    }
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


def parse_game_data(game: dict, game_timestamp: str) -> dict:
    """Helper method to parse game data from one item

    Args:
        game: a dict, one element of the NBA.com API response that represents a single game
        game_timestamp: a str representing the start time of the game.
            Needs to be an arg since the scoreboard and schedule responses use different keys for this

    Returns:
        a dict containing relevant information
    """
    # TODO: Set status as final when it says something like 4Q 0:00
    return {
        "date_time": game_timestamp,
        "home_team": game["homeTeam"]["teamTricode"],
        "home_score": game["homeTeam"]["score"],
        "away_team": game["awayTeam"]["teamTricode"],
        "away_score": game["awayTeam"]["score"],
        "status_text": game["gameStatusText"],
        "status": NBAGameStatus(game["gameStatus"]),
    }


def parse_schedule(scoreboard_date: date) -> List:
    """Parse NBA.com's schedule data

    Args:
        scoreboard_date: the date to stop parsing the schedule

    Returns:
        list of dictionaries, where each element contains information about an individual game
    """
    game_data = []
    nba_schedule_data = request_helper(nba_schedule_data_url)
    reg_season_start_date = pd.to_datetime(nba_schedule_data["leagueSchedule"]["weeks"][0]["startDate"]).date()

    for game_date in nba_schedule_data["leagueSchedule"]["gameDates"]:
        date = pd.to_datetime(game_date["gameDate"]).date()
        if reg_season_start_date <= date < scoreboard_date:
            for game in game_date["games"]:
                game_data.append(parse_game_data(game, game["gameDateTimeUTC"]))
    return game_data


def parse_scoreboard() -> Tuple[List, date]:
    """Parse NBA.com's scoreboard data

    Returns:
        2-element tuple
            - a list of dictionaries, where each element contains information about an individual game
            - the current date according to the scoreboard
    """
    game_data = []
    scoreboard_raw = request_helper(nba_scoreboard_url)
    scoreboard_date = pd.to_datetime(scoreboard_raw["scoreboard"]["gameDate"]).date()

    for game in scoreboard_raw["scoreboard"]["games"]:
        game_data.append(parse_game_data(game, game["gameTimeUTC"]))
        raw_status = game["gameStatusText"]
    return game_data, scoreboard_date


def get_game_data(pool_slug: str) -> Tuple[pd.DataFrame, date]:
    """Calls NBA APIs and generates game dataframe

    Args:
        pool_slug: a string representing a specific wins pool, which has a corresponding file named data/{slug}_team_owner.json

    Returns:
        2-element tuple
            - first element is a dataframe where each row has data about a single game, including which owner is involved in the game
            - second element is the date according to the NBA.com scoreboard
    """
    # Parse NBA APIs
    scoreboard_data, scoreboard_date = parse_scoreboard()
    schedule_data = parse_schedule(scoreboard_date)
    df = pd.concat([pd.DataFrame(schedule_data), pd.DataFrame(scoreboard_data)])

    # Load team owner information
    map_file = team_to_owner_path / Path(f"{pool_slug}_team_owner.json")

    if map_file.exists():
        with open(map_file) as f:
            team_id_to_owner = json.load(f)
    else:
        raise FileNotFoundError(f"{map_file} could not be found.")

    # Parse dates
    df["date_time"] = pd.to_datetime(df["date_time"], utc=True).dt.tz_convert("US/Eastern")

    # Determine winning and losing team
    df["winning_team"] = df["home_team"].where(
        (df.status == NBAGameStatus.FINAL) & (df.home_score > df.away_score),
        other=df["away_team"].where(df.status == NBAGameStatus.FINAL),
    )
    df["losing_team"] = df["home_team"].where(
        (df.status == NBAGameStatus.FINAL) & (df.home_score < df.away_score),
        other=df["away_team"].where(df.status == NBAGameStatus.FINAL),
    )

    df["winning_owner"] = df["winning_team"].apply(lambda x: team_id_to_owner.get(x) if pd.notnull(x) else pd.NA)
    df["losing_owner"] = df["losing_team"].apply(lambda x: team_id_to_owner.get(x) if pd.notnull(x) else pd.NA)
    df["home_owner"] = df["home_team"].apply(lambda x: team_id_to_owner.get(x) if pd.notnull(x) else pd.NA)
    df["away_owner"] = df["away_team"].apply(lambda x: team_id_to_owner.get(x) if pd.notnull(x) else pd.NA)

    return df, scoreboard_date


def generate_leaderboard(df: pd.DataFrame, today_date: date) -> pd.DataFrame:
    """Generates leaderboard, computes overall W-L by owner

    Args:
        df: the first output of get_game_data()
        today_date: the second output of get_game_data()

    Returns:
        pd.DataFrame with owner-level stats including W-L for the entire season, today, and last 7 days
    """
    # Create a DataFrame with Owner as the index and wins and losses as columns
    leaderboard_df = pd.DataFrame(
        {
            "wins": df.groupby("winning_owner")["status"].count(),
            "losses": df.groupby("losing_owner")["status"].count(),
        }
    )
    leaderboard_df = leaderboard_df.sort_values(by=["wins", "losses"], ascending=[False, True])
    # Compute leaderboard rank, using min to give ties the same rank
    leaderboard_df["rank"] = leaderboard_df["wins"].rank(method="min", ascending=False).astype(int)
    leaderboard_df["name"] = leaderboard_df.index
    leaderboard_df["W-L"] = leaderboard_df.apply(lambda x: f"{x.wins}-{x.losses}", axis=1)

    # Compute record over last 7 days
    last_7_days_df = df[df["date_time"].dt.date > (today_date - pd.Timedelta(days=7))]
    for name in leaderboard_df.index:
        wins = (last_7_days_df["winning_owner"] == name).sum()
        losses = (last_7_days_df["losing_owner"] == name).sum()
        leaderboard_df.loc[name, "7d"] = f"{wins}-{losses}"

    # Compute record from today's games
    today_df = df[df["date_time"].dt.date == today_date]
    today_str_col = []
    for name in leaderboard_df.index:
        wins = (today_df["winning_owner"] == name).sum()
        losses = (today_df["losing_owner"] == name).sum()
        today_str_col.append(f"{wins}-{losses}")

    leaderboard_df["Today"] = pd.Series(today_str_col, index=leaderboard_df.index)

    return leaderboard_df[["rank", "name", "W-L", "Today", "7d"]]


def generate_team_breakdown(df: pd.DataFrame, today_date: date) -> pd.DataFrame:
    """Generates team-level stats, including overall W-L and recent results.

    Args:
        df: pd.DataFrame, the output of get_game_data()
        today_date: date, the output of get_game_data()

    Returns:
        pd.DataFrame with team-level stats, grouped by owner and in standings order
    """
    # Create DataFrame with Owner, Team as index and wins, losses as columns
    # Grouping by team gives us team-level counts for wins and losses
    # Grouping by owner and team allows us to group the team level stats by owner as well
    team_breakdown_df = pd.DataFrame(
        {
            "wins": df.groupby(["winning_owner", "winning_team"])["winning_team"].count(),
            "losses": df.groupby(["losing_owner", "losing_team"])["losing_team"].count(),
        }
    )

    # Keep only owner as index, convert team to regular column
    team_breakdown_df = team_breakdown_df.reset_index(level=1, names=["", "team"])

    # Compute the standings order of the owners. Could be re-used in from `generate_leaderboard()`
    ordered_owners = (
        team_breakdown_df.groupby(level=[0]).sum().sort_values(by=["wins", "losses"], ascending=[False, True]).index
    )

    # Filter recent data for recent status strings
    today_df = df[df["date_time"].dt.date == today_date]
    yesterday_df = df[df["date_time"].dt.date == (today_date - timedelta(1))]

    today_results = {}
    today_df.apply(lambda x: result_map(x, today_results), axis=1)

    yesterday_results = {}
    yesterday_df.apply(lambda x: result_map(x, yesterday_results), axis=1)

    team_breakdown_df["today"] = team_breakdown_df.team.map(today_results)
    team_breakdown_df["yesterday"] = team_breakdown_df.team.map(yesterday_results)

    # Return sorted dataframe, sorted by both Owner (standings order) and individual team record
    return team_breakdown_df.sort_values(by=["wins", "losses"], ascending=[False, True]).loc[ordered_owners,].fillna("")


def result_map(row: pd.Series, results: dict) -> None:
    """Generates a status string for the game based on its status.

    Args:
        row: pd.Series representing one row of the schedule dataframe or scoreboard dataframe
        results: dict to add status strings to, with key representing a team and value being it's status

    Returns:
        None, this method adds items to the passed dictionary results
    """
    match row.status:
        case NBAGameStatus.PREGAME:
            results[row.home_team] = f"{row.status_text} vs {row.away_team}"
            results[row.away_team] = f"{row.status_text} @ {row.home_team}"
        case NBAGameStatus.INGAME:
            results[row.home_team] = f"{row.home_score}-{row.away_score}, {row.status_text} vs {row.away_team}"
            results[row.away_team] = f"{row.home_score}-{row.away_score}, {row.status_text} @ {row.home_team}"
        case NBAGameStatus.FINAL:
            if row.home_score > row.away_score:
                home_status = "W"
                away_status = "L"
            else:
                home_status = "L"
                away_status = "W"
            results[row.home_team] = f"{home_status}, {row.home_score}-{row.away_score} vs {row.away_team}"
            results[row.away_team] = f"{away_status}, {row.away_score}-{row.home_score} @ {row.home_team}"
        case _:
            results[row.home_team] = ""
            results[row.away_team] = ""
