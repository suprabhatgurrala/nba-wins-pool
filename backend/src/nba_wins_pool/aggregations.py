from datetime import date, timedelta

import pandas as pd

from nba_wins_pool.nba_data import NBAGameStatus, nba_logo_url, nba_tricode_to_id


def generate_leaderboard(df: pd.DataFrame, today_date: date) -> pd.DataFrame:
    """Generates leaderboard, computes overall W-L by owner

    Args:
        df: the first output of get_game_data()
        today_date: the second output of get_game_data()

    Returns:
        pd.DataFrame with owner-level stats including W-L for the entire season, today, and last 7 days
    """
    leaderboard_df = compute_record(df)
    leaderboard_df = leaderboard_df.sort_values(by=["wins", "losses"], ascending=[False, True])
    # Compute leaderboard rank, using min to give ties the same rank
    leaderboard_df["rank"] = leaderboard_df["wins"].rank(method="min", ascending=False).astype(int)
    leaderboard_df["W-L"] = leaderboard_df.apply(win_loss_str, axis=1)

    merge_col = "name"
    # Compute record from today's games
    today_df = compute_record(df, today_date, offset=1)
    leaderboard_df = leaderboard_df.merge(today_df, how="left", on=merge_col, suffixes=["", "_today"]).fillna(0)

    # Compute record from yesterday's games
    yesterday_df = compute_record(df[df["date_time"].dt.date == (today_date - timedelta(1))], today_date)
    leaderboard_df = leaderboard_df.merge(yesterday_df, how="left", on=merge_col, suffixes=["", "_yesterday"]).fillna(0)

    # Compute record over last 7 days
    last7 = compute_record(df, today_date, offset=7)
    leaderboard_df = leaderboard_df.merge(last7, how="left", on=merge_col, suffixes=["", "_last7"]).fillna(0)

    # Compute record over last 30 days
    last30 = compute_record(df, today_date, offset=30)
    leaderboard_df = leaderboard_df.merge(last30, how="left", on=merge_col, suffixes=["", "_last30"]).fillna(0)

    # Convert win loss columns to strings
    leaderboard_df["Today"] = leaderboard_df.apply(lambda x: win_loss_str(x, suffix="_today"), axis=1)
    leaderboard_df["Yesterday"] = leaderboard_df.apply(lambda x: win_loss_str(x, suffix="_yesterday"), axis=1)
    leaderboard_df["7d"] = leaderboard_df.apply(lambda x: win_loss_str(x, suffix="_last7"), axis=1)
    leaderboard_df["30d"] = leaderboard_df.apply(lambda x: win_loss_str(x, suffix="_last30"), axis=1)

    return leaderboard_df[["rank", "name", "W-L", "Today", "Yesterday", "7d", "30d"]].reset_index(drop=True)


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
    team_breakdown_df = compute_record(df, group_by_team=True)
    team_breakdown_df["logo_url"] = team_breakdown_df["team"].apply(
        lambda x: nba_logo_url.format(nba_team_id=nba_tricode_to_id[x])
    )

    # Compute the standings order of the owners.
    ordered_owners = (
        team_breakdown_df.groupby("name").sum().sort_values(by=["wins", "losses"], ascending=[False, True]).index
    )

    # Filter recent data for recent status strings
    today_df = df[df["date_time"].dt.date == today_date]
    yesterday_df = df[df["date_time"].dt.date == (today_date - timedelta(1))]

    today_results = {}
    today_df.apply(lambda x: result_map(x, today_results), axis=1)

    yesterday_results = {}
    yesterday_df.apply(lambda x: result_map(x, yesterday_results), axis=1)

    team_breakdown_df["Today"] = team_breakdown_df["team"].map(today_results).fillna("")
    team_breakdown_df["Yesterday"] = team_breakdown_df["team"].map(yesterday_results).fillna("")

    merge_cols = ["name", "team"]

    # Compute record over last 7 days
    last7 = compute_record(df, today_date, offset=7, group_by_team=True)
    team_breakdown_df = team_breakdown_df.merge(last7, how="left", on=merge_cols, suffixes=["", "_last7"]).fillna(0)

    # Compute record over last 30 days
    last30 = compute_record(df, today_date, offset=30, group_by_team=True)
    team_breakdown_df = team_breakdown_df.merge(last30, how="left", on=merge_cols, suffixes=["", "_last30"]).fillna(0)

    # Convert win loss columns to strings
    team_breakdown_df["W-L"] = team_breakdown_df.apply(win_loss_str, axis=1)
    team_breakdown_df["7d"] = team_breakdown_df.apply(lambda x: win_loss_str(x, suffix="_last7"), axis=1)
    team_breakdown_df["30d"] = team_breakdown_df.apply(lambda x: win_loss_str(x, suffix="_last30"), axis=1)

    # Sort by Team record
    team_breakdown_df = team_breakdown_df.sort_values(by=["wins", "losses"], ascending=[False, True])
    # Sort by Owner standings
    team_breakdown_df = team_breakdown_df.set_index("name", drop=False).loc[ordered_owners]

    return team_breakdown_df[["name", "team", "logo_url", "W-L", "Today", "Yesterday", "7d", "30d"]].reset_index(
        drop=True
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


def compute_record(
    df: pd.DataFrame, today_date: date = None, offset: int = None, group_by_team: bool = False
) -> pd.DataFrame:
    """Helper method to compute wins/losses for a given set of games

    Args:
        df: pd.DataFrame, the output of get_game_data()
        today_date: date, the output of get_game_data()
        offset: optional, integer value to filter by the last offset number of days.
            For example offset=7 will filter games that occurred in the last 7 days
        group_by_team: optional, bool on whether to group records by team in addition to grouping by owner

    Returns:
        pd.DataFrame with columns for Owner, Team (if group_by_team=True), wins and losses
    """
    if offset is not None:
        if today_date is None:
            raise ValueError("today_date is required when using offset")
        df = df[df["date_time"].dt.date > (today_date - pd.Timedelta(days=offset))]

    if group_by_team:
        standings = pd.DataFrame(
            {
                "wins": df.groupby(["winning_owner", "winning_team"])["winning_team"].count(),
                "losses": df.groupby(["losing_owner", "losing_team"])["losing_team"].count(),
            }
        ).reset_index(names=["name", "team"])
    else:
        standings = pd.DataFrame(
            {
                "wins": df.groupby(["winning_owner"])["winning_team"].count(),
                "losses": df.groupby(["losing_owner"])["losing_team"].count(),
            }
        ).reset_index(names=["name"])

    standings = standings.fillna(0)

    return standings.sort_values(by=["wins", "losses"], ascending=[False, True])


def win_loss_str(row: pd.Series, suffix: str = "") -> str:
    """Helper method to format wins and losses column int a string

    Args:
        row: a pd.Series representing one row of the dataframe, typically the result of using pd.DataFrame.apply()
        suffix: a suffix to add wins and losses column names, defaults to empty string

    Returns:
        a string of W-L, with data converted to integers
    """
    return f"{int(row[f"wins{suffix}"])}-{int(row[f"losses{suffix}"])}"
