from nba_wins_pool.aggregations import generate_leaderboard, generate_team_breakdown
from nba_wins_pool.nba_data import get_game_data


def test_leaderboard():
    df, today_date = get_game_data("sg")
    leaderboard = generate_leaderboard(df, today_date)
    assert leaderboard.shape[0] == 6


def test_team_breakdown():
    df, today_date = get_game_data("sg")
    team_breakdown = generate_team_breakdown(df, today_date)
    assert team_breakdown.shape[0] == 24
