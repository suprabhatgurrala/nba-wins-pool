import json
from datetime import date
from enum import Enum
from pathlib import Path
from types import NoneType
from typing import List, Tuple

import pandas as pd
import requests

nba_schedule_data_url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
nba_scoreboard_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
nba_logo_url = "https://cdn.nba.com/logos/nba/{nba_team_id}/primary/L/logo.svg"

data_path = Path(__file__).parent / "data"
with open(data_path / "nba_tricode_to_id.json") as f:
    nba_tricode_to_id = json.load(f)

team_owner_cache = None
milestones_cache = None
schedule_cache = {}


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


def parse_schedule(scoreboard_date: date, schedule_cache: dict = schedule_cache) -> Tuple[List, str]:
    """Parse NBA.com's schedule data

    Args:
        scoreboard_date: the date to stop parsing the schedule
        schedule_cache: a dictionary to cache the schedule data by date

    Returns:
        a 2-tuple:
            - list of dictionaries, where each element contains information about an individual game
            - a string representing the current seasonYear
    """
    if scoreboard_date not in schedule_cache:
        game_data = []
        nba_schedule_data = request_helper(nba_schedule_data_url)
        reg_season_start_date = pd.to_datetime(nba_schedule_data["leagueSchedule"]["weeks"][0]["startDate"]).date()

        current_season = nba_schedule_data["leagueSchedule"]["seasonYear"]

        for game_date in nba_schedule_data["leagueSchedule"]["gameDates"]:
            date = pd.to_datetime(game_date["gameDate"]).date()
            if reg_season_start_date <= date < scoreboard_date:
                for game in game_date["games"]:
                    game_data.append(parse_game_data(game, game["gameDateTimeUTC"]))
        schedule_cache[scoreboard_date] = game_data, current_season
    return schedule_cache[scoreboard_date]


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
    return game_data, scoreboard_date


def get_game_data(pool_slug: str) -> Tuple[pd.DataFrame, date]:
    """Calls NBA APIs and generates game dataframe

    Args:
        pool_slug: a string representing a specific wins pool, which has a corresponding file named data/{slug}_team_owner.json
        season: a string representing the seasonYear to get data for

    Returns:
        3-element tuple
            - first element is a dataframe where each row has data about a single game, including which owner is involved in the game
            - second element is the date according to the NBA.com scoreboard
            - third element is the current seasonYear
    """
    # Parse NBA APIs
    scoreboard_data, scoreboard_date = parse_scoreboard()
    schedule_data, seasonYear = parse_schedule(scoreboard_date)
    df = pd.concat([pd.DataFrame(schedule_data), pd.DataFrame(scoreboard_data)])

    # Load team owner information
    team_owner_df = read_team_owner_data(pool_slug)

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

    team_to_owner_map: pd.Series = team_owner_df.loc[seasonYear]["owner"]

    for col in ["home_team", "away_team", "winning_team", "losing_team"]:
        df[col.replace("_team", "_owner")] = df[col].map(team_to_owner_map, na_action="ignore")

    return df, scoreboard_date, seasonYear


def read_team_owner_data(pool_slug: str, team_owner_cache: pd.DataFrame | NoneType = team_owner_cache) -> pd.DataFrame:
    """Reads team owner data from file and caches it

    Args:
        pool_slug: a string representing a specific wins pool, which has a corresponding file named data/{slug}_team_owner.csv
        team_owner_cache: global variable to cache the team owner data in memory

    Returns:
        a pandas DataFrame indexed on seasonYear and team, where each row has its corresponding owner and auction price
    """
    if team_owner_cache is not None:
        team_owner_df = team_owner_cache
    else:
        team_owner_df = pd.read_csv(data_path / "team_owner.csv")
        team_owner_df = team_owner_df.set_index(["pool_slug", "season", "team"])
        team_owner_cache = team_owner_df

    return team_owner_df.loc[pool_slug]


def read_milestone_data(season: str, milestones_cache: pd.DataFrame | NoneType = milestones_cache) -> pd.DataFrame:
    """Reads milestone data from file

    Returns:
        a pandas DataFrame indexed on seasonYear where each row has a season milestone
    """
    if milestones_cache is not None:
        milestones_df = milestones_cache
    else:
        milestones_df = pd.read_csv(data_path / "milestones.csv")
        milestones_df = milestones_df.set_index(["season"])
        milestones_cache = milestones_df

    return milestones_df.loc[season]
