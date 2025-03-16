import pytest

from nba_wins_pool.aggregations import generate_leaderboard, generate_wins_race_data
from nba_wins_pool.nba_data import get_game_data


# sg pool includes Undrafted, kk pool does not
@pytest.mark.parametrize("pool_slug, expected_owners", [("sg", 7), ("kk", 6)])
def test_leaderboard(pool_slug, expected_owners):
    owner_leaderboard, team_leaderboard = generate_leaderboard(pool_slug, *get_game_data(pool_slug))
    assert owner_leaderboard.shape[0] == expected_owners
    assert team_leaderboard.shape[0] == 30


# AI testing itself lol
@pytest.mark.parametrize("pool_slug, expected_owners", [("sg", 6), ("kk", 6)])
def test_wins_race_data(pool_slug, expected_owners):
    game_data, today_date, season_year = get_game_data(pool_slug)
    race_data = generate_wins_race_data(pool_slug, game_data, today_date, season_year)

    # 1. Test data structure
    assert isinstance(race_data, dict)
    assert "data" in race_data
    assert "metadata" in race_data
    assert "owners" in race_data["metadata"]
    assert "milestones" in race_data["metadata"]

    # 2. Test owners, Undrafted should not be included
    actual_owners = [owner["name"] for owner in race_data["metadata"]["owners"]]
    assert len(actual_owners) == expected_owners
    assert "Undrafted" not in actual_owners

    # 3. Test milestones
    milestones = race_data["metadata"]["milestones"]
    assert len(milestones) > 0
    assert all(key in milestones[0] for key in ["slug", "date", "description"])

    # 4. Test data integrity
    data = race_data["data"]
    assert len(data) > 0
    assert all(key in data[0] for key in ["date", "owner", "wins"])

    # 5. Test monotonically increasing wins (wins should never decrease)
    for owner in actual_owners:
        owner_data = sorted(
            [entry for entry in data if entry["owner"] == owner],
            key=lambda x: x["date"],
        )
        for i in range(1, len(owner_data)):
            assert (
                owner_data[i]["wins"] >= owner_data[i - 1]["wins"]
            ), f"Wins decreased for {owner} from {owner_data[i-1]['date']} to {owner_data[i]['date']}"

    # 6. Test consistency with leaderboard
    owner_leaderboard, _ = generate_leaderboard(pool_slug, game_data, today_date, season_year)
    latest_date = max(entry["date"] for entry in data)

    for owner in actual_owners:
        race_wins = next(entry["wins"] for entry in data if entry["owner"] == owner and entry["date"] == latest_date)
        leaderboard_wins = owner_leaderboard.loc[owner_leaderboard["name"] == owner, "wins"].values[0]
        assert (
            race_wins == leaderboard_wins
        ), f"Final race wins ({race_wins}) don't match leaderboard wins ({leaderboard_wins}) for {owner}"

    # 7. Test coverage (all dates × all owners)
    unique_dates = len(set(entry["date"] for entry in data))
    expected_data_points = len(actual_owners) * unique_dates
    assert (
        len(data) == expected_data_points
    ), f"Expected {expected_data_points} data points (owners × dates), got {len(data)}"
