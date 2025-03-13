from datetime import date, timedelta

import pandas as pd

from nba_wins_pool.nba_data import NBAGameStatus, get_game_data, nba_logo_url, nba_tricode_to_id, read_team_owner_data


def generate_leaderboard(pool_slug: str, game_data_df: pd.DataFrame, today_date: str, seasonYear: str) -> pd.DataFrame:
    """Generates team-level stats, including overall W-L and recent results.

    Args:
        pool_slug: str, id of the pool
        game_data_df: pd.DataFrame, the output of nba_data.get_game_data()
        today_date: str, the output of nba_data.get_game_data()
        seasonYear: str, the output of nba_data.get_game_data()

    Returns:
        a 2-tuple
            - pd.DataFrame with owner-level stats, grouped by owner and in standings order
            - pd.DataFrame with team-level stats
    """

    # Create DataFrame with Owner, Team as index and wins, losses as columns
    # Grouping by team gives us team-level counts for wins and losses
    # Grouping by owner and team allows us to group the team level stats by owner as well
    team_breakdown_df = compute_record(game_data_df)
    team_owner_df = read_team_owner_data(pool_slug)
    team_breakdown_df["logo_url"] = team_breakdown_df["team"].apply(
        lambda x: nba_logo_url.format(nba_team_id=nba_tricode_to_id[x])
    )
    team_breakdown_df["auction_price"] = team_breakdown_df["team"].map(
        team_owner_df.loc[seasonYear]["Auction Cost"], na_action="ignore"
    )

    # Filter recent data for recent status strings
    today_df = game_data_df[game_data_df["date_time"].dt.date == today_date]
    yesterday_df = game_data_df[game_data_df["date_time"].dt.date == (today_date - timedelta(1))]

    today_results = {}
    today_df.apply(lambda x: result_map(x, today_results), axis=1)

    yesterday_results = {}
    yesterday_df.apply(lambda x: result_map(x, yesterday_results), axis=1)

    team_breakdown_df["today_result"] = team_breakdown_df["team"].map(today_results).fillna("")
    team_breakdown_df["yesterday_result"] = team_breakdown_df["team"].map(yesterday_results).fillna("")

    merge_cols = ["name", "team"]

    # Compute today record
    today_record = compute_record(today_df)
    team_breakdown_df = team_breakdown_df.merge(
        today_record, how="left", on=merge_cols, suffixes=["", "_today"]
    ).fillna(0)

    # Compute yesterday record
    yesterday_record = compute_record(yesterday_df)
    team_breakdown_df = team_breakdown_df.merge(
        yesterday_record, how="left", on=merge_cols, suffixes=["", "_yesterday"]
    ).fillna(0)

    # Compute record over last 7 days
    last7 = compute_record(game_data_df, today_date, offset=7)
    team_breakdown_df = team_breakdown_df.merge(last7, how="left", on=merge_cols, suffixes=["", "_last7"]).fillna(0)

    # Compute record over last 30 days
    last30 = compute_record(game_data_df, today_date, offset=30)
    team_breakdown_df = team_breakdown_df.merge(last30, how="left", on=merge_cols, suffixes=["", "_last30"]).fillna(0)

    # Sort by Team record
    team_breakdown_df = team_breakdown_df.sort_values(by=["wins", "losses"], ascending=[False, True])

    # Compute the standings order of the owners.
    owner_standings_df = (
        team_breakdown_df.groupby("name").sum().sort_values(by=["wins", "losses"], ascending=[False, True])
    )
    owner_standings_df = owner_standings_df.drop(columns=["team", "logo_url", "today_result", "yesterday_result"])
    ordered_owners = owner_standings_df.index.to_list()
    if "Undrafted" in ordered_owners:
        ordered_owners.remove("Undrafted")
        ordered_owners.append("Undrafted")

    owner_standings_df = owner_standings_df.reindex(ordered_owners)
    rank_series = owner_standings_df.loc[ordered_owners[:-1]]["wins"].rank(method="min", ascending=False).astype(int)
    owner_standings_df["rank"] = owner_standings_df.index.map(rank_series.reindex(ordered_owners))
    owner_standings_df = owner_standings_df.reset_index()

    # Sort by Owner standings
    team_breakdown_df = team_breakdown_df.set_index("name", drop=False).loc[ordered_owners]

    return owner_standings_df.fillna("<NULL>").replace("<NULL>", None), team_breakdown_df.fillna("<NULL>").replace(
        "<NULL>", None
    )


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
            results[row.away_team] = f"{row.away_score}-{row.home_score}, {row.status_text} @ {row.home_team}"
        case NBAGameStatus.FINAL:
            if row.home_score > row.away_score:
                home_status = "W"
                away_status = "L"
            else:
                home_status = "L"
                away_status = "W"
            results[row.home_team] = f"{home_status}, {row.home_score}-{row.away_score} vs {row.away_team}"
            results[row.away_team] = f"{away_status}, {row.away_score}-{row.home_score} @ {row.home_team}"


def compute_record(df: pd.DataFrame, today_date: date = None, offset: int = None) -> pd.DataFrame:
    """Helper method to compute wins/losses for a given set of games

    Args:
        df: pd.DataFrame, the output of get_game_data()
        today_date: date, the output of get_game_data()
        offset: optional, integer value to filter by the last offset number of days.
            For example offset=7 will filter games that occurred in the last 7 days
        group_by_team: optional, bool on whether to group records by team in addition to grouping by owner

    Returns:
        pd.DataFrame with columns for Owner, Team, wins and losses
    """
    if offset is not None:
        if today_date is None:
            raise ValueError("today_date is required when using offset")
        df = df[df["date_time"].dt.date > (today_date - pd.Timedelta(days=offset))]

    standings = pd.DataFrame(
        {
            "wins": df.groupby(["winning_owner", "winning_team"])["winning_team"].count(),
            "losses": df.groupby(["losing_owner", "losing_team"])["losing_team"].count(),
        }
    ).reset_index(names=["name", "team"])

    standings = standings.fillna(0)

    return standings.sort_values(by=["wins", "losses"], ascending=[False, True])
