from unittest.mock import patch

import pytest

from nba_wins_pool.services.nba_data_service import NbaDataService

_DEFAULT_CURRENT_SEASON_RAW = (
    {"modules": []},
    {"leagueSchedule": {"seasonYear": "2024-25", "gameDates": []}},
)


@pytest.fixture(autouse=True)
def clear_nba_data_service_cache():
    NbaDataService.get_game_data.cache_clear()
    NbaDataService.get_current_season.cache_clear()
    NbaDataService._fetch_current_season_raw.cache_clear()
    with patch.object(NbaDataService, "_fetch_current_season_raw", return_value=_DEFAULT_CURRENT_SEASON_RAW):
        yield
