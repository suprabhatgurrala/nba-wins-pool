import json
from pathlib import Path

import pandas as pd
import requests

nba_schedule_data_url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
nba_scoreboard_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

team_to_owner_map_file = "team_owner.json"
team_to_owner_path = Path(__file__).parent / team_to_owner_map_file


def request_helper(url):
    r = requests.get(url)
    r.raise_for_status()
    return r.json()


def generate_game_data():
    nba_schedule_data = request_helper(nba_schedule_data_url)
    reg_season_start_date = pd.to_datetime(nba_schedule_data["leagueSchedule"]["weeks"][0]["startDate"]).date()

    scoreboard_raw = request_helper(nba_scoreboard_url)
    scoreboard_date = pd.to_datetime(scoreboard_raw["scoreboard"]["gameDate"]).date()

    game_data = []

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
                        "status": "Final" if "Final" in raw_status else raw_status,
                    }
                )

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
                "status": "Final" if "Final" in raw_status else raw_status,
            }
        )

    df = pd.DataFrame(game_data)

    df["date_time"] = pd.to_datetime(df["date_time"], infer_datetime_format=True, utc=True).dt.tz_convert("US/Eastern")

    return df, scoreboard_date


def generate_leaderboard():
    game_data, today_date = generate_game_data()

    if team_to_owner_path.exists():
        with open(team_to_owner_path) as f:
            team_id_to_owner = json.load(f)
    else:
        raise FileNotFoundError("team_owner.json could not be found.")
    df = game_data
    df["winning_team"] = df["home_team"].where(
        (df.status == "Final") & (df.home_score > df.away_score),
        other=df["away_team"].where(df.status == "Final"),
    )
    df["losing_team"] = df["home_team"].where(
        (df.status == "Final") & (df.home_score < df.away_score),
        other=df["away_team"].where(df.status == "Final"),
    )
    df["winning_owner"] = df["winning_team"].apply(lambda x: team_id_to_owner.get(x) if pd.notnull(x) else pd.NA)
    df["losing_owner"] = df["losing_team"].apply(lambda x: team_id_to_owner.get(x) if pd.notnull(x) else pd.NA)
    df["home_owner"] = df["home_team"].apply(lambda x: team_id_to_owner.get(x) if pd.notnull(x) else pd.NA)
    df["away_owner"] = df["away_team"].apply(lambda x: team_id_to_owner.get(x) if pd.notnull(x) else pd.NA)

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

        # pending_teams = (today_df["home_owner"] == name).sum() + (today_df["away_owner"] == name).sum()

        today_str_col.append(f"{wins}-{losses}")

    leaderboard_df["Today"] = pd.Series(today_str_col, index=leaderboard_df.index)

    return leaderboard_df[["rank", "name", "W-L", "Today", "7d"]]
