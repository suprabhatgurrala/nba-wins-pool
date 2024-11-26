import datetime
import json
from enum import Enum
from pathlib import Path

import pandas as pd
import requests

nba_schedule_data_url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
nba_scoreboard_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

team_to_owner_path = Path(__file__).parent / "data"


class NBAGameStatus(Enum):
    PREGAME = 1
    INGAME = 2
    FINAL = 3


def request_helper(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
    }
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


def parse_schedule(scoreboard_date):
    game_data = []
    nba_schedule_data = request_helper(nba_schedule_data_url)
    reg_season_start_date = pd.to_datetime(nba_schedule_data["leagueSchedule"]["weeks"][0]["startDate"]).date()

    for game_date in nba_schedule_data["leagueSchedule"]["gameDates"]:
        date = pd.to_datetime(game_date["gameDate"]).date()
        if reg_season_start_date <= date < scoreboard_date:
            for game in game_date["games"]:
                raw_status = game["gameStatusText"]
                game_data.append(
                    {
                        "date_time": game["gameDateTimeUTC"],
                        "home_team": game["homeTeam"]["teamTricode"],
                        "home_score": game["homeTeam"]["score"],
                        "away_team": game["awayTeam"]["teamTricode"],
                        "away_score": game["awayTeam"]["score"],
                        "status_text": "Final" if "Final" in raw_status else raw_status,
                        "status": NBAGameStatus(game["gameStatus"]),
                    }
                )
    return game_data


def parse_scoreboard():
    game_data = []
    scoreboard_raw = request_helper(nba_scoreboard_url)
    scoreboard_date = pd.to_datetime(scoreboard_raw["scoreboard"]["gameDate"]).date()

    for game in scoreboard_raw["scoreboard"]["games"]:
        raw_status = game["gameStatusText"]
        # TODO: Set status as final when it says something like 4Q 0:00
        game_data.append(
            {
                "date_time": game["gameTimeUTC"],
                "home_team": game["homeTeam"]["teamTricode"],
                "home_score": game["homeTeam"]["score"],
                "away_team": game["awayTeam"]["teamTricode"],
                "away_score": game["awayTeam"]["score"],
                "status_text": "Final" if "Final" in raw_status else raw_status,
                "status": NBAGameStatus(game["gameStatus"]),
            }
        )
    return game_data, scoreboard_date


def get_game_data(pool_slug):
    scoreboard_data, scoreboard_date = parse_scoreboard()
    schedule_data = parse_schedule(scoreboard_date)
    df = pd.concat([pd.DataFrame(schedule_data), pd.DataFrame(scoreboard_data)])

    map_file = team_to_owner_path / Path(f"{pool_slug}_team_owner.json")

    if map_file.exists():
        with open(map_file) as f:
            team_id_to_owner = json.load(f)
    else:
        raise FileNotFoundError(f"{map_file} could not be found.")

    df["date_time"] = pd.to_datetime(df["date_time"], utc=True).dt.tz_convert("US/Eastern")
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


def generate_leaderboard(df, today_date):
    leaderboard_df = pd.DataFrame(
        {
            "wins": df.groupby("winning_owner")["status"].count(),
            "losses": df.groupby("losing_owner")["status"].count(),
        }
    )
    leaderboard_df = leaderboard_df.sort_values(by=["wins", "losses"], ascending=[False, True])
    leaderboard_df["rank"] = leaderboard_df["wins"].rank(method="min", ascending=False).astype(int)
    leaderboard_df["name"] = leaderboard_df.index
    leaderboard_df["W-L"] = leaderboard_df.apply(lambda x: f"{x.wins}-{x.losses}", axis=1)

    last_7_days_df = df[df["date_time"].dt.date > (today_date - pd.Timedelta(days=7))]
    for name in leaderboard_df.index:
        wins = (last_7_days_df["winning_owner"] == name).sum()
        losses = (last_7_days_df["losing_owner"] == name).sum()
        leaderboard_df.loc[name, "7d"] = f"{wins}-{losses}"

    today_df = df[df["date_time"].dt.date == today_date]

    today_str_col = []
    for name in leaderboard_df.index:
        wins = (today_df["winning_owner"] == name).sum()
        losses = (today_df["losing_owner"] == name).sum()
        today_str_col.append(f"{wins}-{losses}")

    leaderboard_df["Today"] = pd.Series(today_str_col, index=leaderboard_df.index)

    return leaderboard_df[["rank", "name", "W-L", "Today", "7d"]]


def generate_team_breakdown(df: pd.DataFrame, today_date: datetime.date) -> pd.DataFrame:
    """Generates team-level stats, including overall W-L and recent results.

    Args:
        df: pd.DataFrame, the output of get_game_data()
        today_date: datetime.date, the output of get_game_data()

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
    yesterday_df = df[df["date_time"].dt.date == (today_date - 1)]

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
