import pytest

from nba_wins_pool.services.nba_data_service import NbaDataService


@pytest.fixture(autouse=True)
def clear_nba_data_service_cache():
    NbaDataService.get_game_data.cache_clear()
    NbaDataService.get_current_season.cache_clear()
    yield
    NbaDataService.get_game_data.cache_clear()
    NbaDataService.get_current_season.cache_clear()
