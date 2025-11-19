"""Tests for NbaDataService with database-backed caching."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.external_data import DataFormat, ExternalData
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.types.nba_game_status import NBAGameStatus


@pytest.fixture
def mock_db_session():
    """Mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def mock_repo():
    """Mock ExternalDataRepository."""
    repo = AsyncMock(spec=ExternalDataRepository)
    return repo


@pytest.fixture
def nba_service(mock_db_session, mock_repo):
    """Create NbaDataService with mocked dependencies."""
    return NbaDataService(mock_db_session, mock_repo)


@pytest.fixture
def sample_scoreboard_data():
    """Sample scoreboard data from NBA API."""
    return [
        {
            "game_id": "0022400001",
            "date_time": "2024-10-22T23:30:00Z",
            "home_team": 1610612747,  # Lakers
            "home_tricode": "LAL",
            "home_score": 110,
            "away_team": 1610612738,  # Celtics
            "away_tricode": "BOS",
            "away_score": 105,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        },
        {
            "game_id": "0022400002",
            "date_time": "2024-10-22T23:00:00Z",
            "home_team": 1610612744,  # Warriors
            "home_tricode": "GSW",
            "home_score": 95,
            "away_team": 1610612752,  # Knicks
            "away_tricode": "NYK",
            "away_score": 98,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        },
    ]


@pytest.fixture
def sample_schedule_data():
    """Sample schedule data from NBA API."""
    return [
        {
            "game_id": "0022400100",
            "date_time": "2024-10-15T23:00:00Z",
            "home_team": 1610612747,
            "home_tricode": "LAL",
            "home_score": 120,
            "away_team": 1610612738,
            "away_tricode": "BOS",
            "away_score": 115,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        }
    ]


class TestGetGameData:
    """Tests for get_game_data method - main public API."""

    @pytest.mark.asyncio
    async def test_get_game_data_current_season_combines_live_and_schedule(self, nba_service, mock_repo):
        """Test that get_game_data for current season combines gamecardfeed and CDN schedule."""
        # Arrange
        season = nba_service.get_current_season()

        gamecardfeed_raw = {
            "modules": [
                {
                    "cards": [
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "live_001",
                                "homeTeam": {"teamId": 1610612747, "score": 110, "teamTricode": "LAL"},
                                "awayTeam": {"teamId": 1610612738, "score": 105, "teamTricode": "BOS"},
                                "gameStatus": 3,
                                "gameTimeUtc": "2024-10-22T23:30:00Z",
                                "gameStatusText": "Final",
                            },
                        }
                    ]
                }
            ]
        }

        cdn_schedule_raw = {
            "leagueSchedule": {
                "seasonYear": season,
                "gameDates": [
                    {
                        "gameDate": "2024-10-15",
                        "games": [
                            {
                                "gameId": "sched_001",
                                "gameStatus": 3,
                                "gameDateTimeUTC": "2024-10-15T23:00:00Z",
                                "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "score": 120},
                                "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "score": 115},
                                "gameStatusText": "Final",
                                "gameLabel": "",
                                "seriesText": "",
                            }
                        ],
                    }
                ],
            }
        }

        with patch.object(nba_service, "_fetch_gamecardfeed_raw", return_value=gamecardfeed_raw):
            with patch.object(nba_service, "_fetch_schedule_raw_cdn", return_value=cdn_schedule_raw):
                # Act
                result = await nba_service.get_game_data(season)

                # Assert
                assert isinstance(result, pd.DataFrame)
                assert len(result) == 2  # Both live and schedule games
                assert "winning_team" in result.columns
                assert "losing_team" in result.columns

    @pytest.mark.asyncio
    async def test_get_game_data_historical_season_uses_cache(self, nba_service, mock_repo):
        """Test that get_game_data for historical season uses cached schedule."""
        # Arrange
        season = "2023-24"
        cached_schedule = {
            "leagueSchedule": {
                "seasonYear": season,
                "gameDates": [
                    {
                        "gameDate": "2024-10-15",
                        "games": [
                            {
                                "gameId": "hist_001",
                                "gameStatus": 3,
                                "gameDateTimeUTC": "2024-10-15T23:00:00Z",
                                "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "score": 115},
                                "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "score": 110},
                                "gameStatusText": "Final",
                                "gameLabel": "",
                                "seriesText": "",
                            }
                        ],
                    }
                ],
            }
        }

        cached_data = ExternalData(
            key=f"nba:schedule:{season}",
            data_format=DataFormat.JSON,
            data_json=cached_schedule,
            updated_at=datetime.now(UTC),
        )
        mock_repo.get_by_key.return_value = cached_data

        # Act
        result = await nba_service.get_game_data(season)

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert "winning_team" in result.columns
        assert "losing_team" in result.columns

    @pytest.mark.asyncio
    async def test_get_game_data_adds_winning_and_losing_teams(self, nba_service, mock_repo):
        """Test that get_game_data correctly identifies winning and losing teams."""
        # Arrange
        season = "2023-24"
        cached_schedule = {
            "leagueSchedule": {
                "seasonYear": season,
                "gameDates": [
                    {
                        "gameDate": "2024-10-15",
                        "games": [
                            {
                                "gameId": "final_game",
                                "gameStatus": 3,  # FINAL
                                "gameDateTimeUTC": "2024-10-15T23:00:00Z",
                                "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "score": 120},
                                "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "score": 110},
                                "gameStatusText": "Final",
                                "gameLabel": "",
                                "seriesText": "",
                            },
                            {
                                "gameId": "in_progress_game",
                                "gameStatus": 2,  # IN PROGRESS
                                "gameDateTimeUTC": "2024-10-16T23:00:00Z",
                                "homeTeam": {"teamId": 1610612744, "teamTricode": "GSW", "score": 50},
                                "awayTeam": {"teamId": 1610612752, "teamTricode": "NYK", "score": 48},
                                "gameStatusText": "In Progress",
                                "gameLabel": "",
                                "seriesText": "",
                                "gameClock": "PT06M00.00S",
                            },
                        ],
                    }
                ],
            }
        }

        cached_data = ExternalData(
            key=f"nba:schedule:{season}",
            data_format=DataFormat.JSON,
            data_json=cached_schedule,
            updated_at=datetime.now(UTC),
        )
        mock_repo.get_by_key.return_value = cached_data

        # Act
        result = await nba_service.get_game_data(season)

        # Assert
        assert len(result) == 2
        final_game = result[result["game_id"] == "final_game"].iloc[0]
        assert final_game["winning_team"] == 1610612747  # LAL (home team with higher score)
        assert final_game["losing_team"] == 1610612738  # BOS (away team with lower score)

        in_progress_game = result[result["game_id"] == "in_progress_game"].iloc[0]
        assert pd.isna(in_progress_game["winning_team"])  # Not final, so no winner
        assert pd.isna(in_progress_game["losing_team"])  # Not final, so no loser


class TestStoreData:
    """Tests for _store_data helper method."""

    @pytest.mark.asyncio
    async def test_store_data_creates_new_record(self, nba_service, mock_repo):
        """Test that _store_data creates new record when none exists."""
        # Arrange
        mock_repo.get_by_key.return_value = None
        test_data = {"key": "value"}

        # Act
        await nba_service._store_data("test:key", test_data)

        # Assert
        mock_repo.save.assert_called_once()
        saved_data = mock_repo.save.call_args[0][0]
        assert saved_data.key == "test:key"
        assert saved_data.data_json == test_data

    @pytest.mark.asyncio
    async def test_store_data_updates_existing_record(self, nba_service, mock_repo):
        """Test that _store_data updates existing record."""
        # Arrange
        existing = ExternalData(
            key="test:key",
            data_format=DataFormat.JSON,
            data_json={"old": "data"},
        )
        mock_repo.get_by_key.return_value = existing
        new_data = {"new": "data"}

        # Act
        await nba_service._store_data("test:key", new_data)

        # Assert
        mock_repo.update.assert_called_once()
        assert existing.data_json == new_data
