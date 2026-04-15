import pytest

from nba_wins_pool.services.nba_data_service import NbaDataService


@pytest.mark.parametrize(
    "season_year, expected_espn_year",
    [
        ("2025-26", 2026),
        ("2024-25", 2025),
        ("2025", 2026),
        ("2024", 2025),
        ("1999-00", 2000),
        ("2000-01", 2001),
    ],
)
def test_espn_year_from_season(season_year, expected_espn_year):
    """Test that _espn_year_from_season correctly converts various season formats."""
    # pylint: disable=protected-access
    assert NbaDataService._espn_year_from_season(season_year) == expected_espn_year
