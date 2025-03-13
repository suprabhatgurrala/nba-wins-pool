import pytest

from nba_wins_pool.aggregations import generate_leaderboard
from nba_wins_pool.nba_data import get_game_data


@pytest.mark.parametrize("pool_slug, expected_owners", [("sg", 7), ("kk", 6)])
def test_leaderboard(pool_slug, expected_owners):
    owner_leaderboard, team_leaderboard = generate_leaderboard(pool_slug, *get_game_data(pool_slug))
    assert owner_leaderboard.shape[0] == expected_owners
    assert team_leaderboard.shape[0] == 30
