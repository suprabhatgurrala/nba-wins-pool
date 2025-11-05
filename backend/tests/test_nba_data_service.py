"""Tests for NbaDataService with database-backed caching."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

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


class TestGetScoreboardCached:
    """Tests for get_gamecardfeed_cached method."""

    @pytest.mark.asyncio
    async def test_stale_cache_fetches_fresh_data(self, nba_service, mock_repo, sample_scoreboard_data):
        """Test that stale cached data triggers a fresh API fetch."""
        # Arrange
        today = datetime.now(UTC).date()
        stale_cache = ExternalData(
            key="nba:scoreboard:live",
            data_format=DataFormat.JSON,
            data_json={"scoreboard": {"gameDate": today.isoformat(), "games": []}},
            updated_at=datetime.now(UTC) - timedelta(minutes=10),  # Stale (>5 min)
        )
        mock_repo.get_by_key.return_value = stale_cache

        # Mock raw API response
        raw_response = {
            "scoreboard": {
                "gameDate": today.isoformat(),
                "games": [
                    {
                        "gameId": "001",
                        "homeTeam": {"teamId": 1610612747, "score": 110, "teamTricode": "LAL"},
                        "awayTeam": {"teamId": 1610612738, "score": 105, "teamTricode": "BOS"},
                        "gameStatus": 3,
                        "gameTimeUTC": "2024-10-22T23:30:00Z",
                        "gameStatusText": "Final",
                        "gameLabel": "",
                    },
                    {
                        "gameId": "002",
                        "homeTeam": {"teamId": 1610612744, "score": 95, "teamTricode": "GSW"},
                        "awayTeam": {"teamId": 1610612752, "score": 98, "teamTricode": "NYK"},
                        "gameStatus": 3,
                        "gameTimeUTC": "2024-10-22T23:00:00Z",
                        "gameStatusText": "Final",
                        "gameLabel": "",
                    },
                ],
            }
        }

        # Mock the NBA API fetches (gamecardfeed + scoreboard)
        gamecardfeed_raw = {
            "modules": [
                {
                    "cards": [
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "001",
                                "homeTeam": {"teamId": 1610612747, "score": 110, "teamTricode": "LAL"},
                                "awayTeam": {"teamId": 1610612738, "score": 105, "teamTricode": "BOS"},
                                "gameStatus": 3,
                                "gameTimeUtc": "2024-10-22T23:30:00Z",
                                "gameStatusText": "Final",
                            },
                        },
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "002",
                                "homeTeam": {"teamId": 1610612744, "score": 95, "teamTricode": "GSW"},
                                "awayTeam": {"teamId": 1610612752, "score": 98, "teamTricode": "NYK"},
                                "gameStatus": 3,
                                "gameTimeUtc": "2024-10-22T23:00:00Z",
                                "gameStatusText": "Final",
                            },
                        },
                    ]
                }
            ]
        }

        with patch.object(nba_service, "_fetch_gamecardfeed_raw", return_value=gamecardfeed_raw):
            with patch.object(nba_service, "_fetch_scoreboard_raw", return_value=raw_response):
                with patch.object(nba_service, "_store_data") as mock_store:
                    # Act
                    games, scoreboard_date = await nba_service.get_gamecardfeed_cached()

                    # Assert
                    assert len(games) == 2
                    assert scoreboard_date == today
                    # both gamecardfeed and scoreboard are stored
                    assert mock_store.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_and_stores(self, nba_service, mock_repo, sample_scoreboard_data):
        """Test that cache miss fetches from API and stores in database."""
        # Arrange
        today = datetime.now(UTC).date()  # Use UTC date like the service does
        mock_repo.get_by_key.return_value = None  # Cache miss

        # Mock raw API response
        raw_response = {
            "scoreboard": {
                "gameDate": today.isoformat(),
                "games": [
                    {
                        "gameId": "001",
                        "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "score": 110},
                        "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "score": 105},
                        "gameStatus": 3,
                        "gameTimeUTC": "2024-10-22T23:30:00Z",
                        "gameStatusText": "Final",
                        "gameLabel": "",
                    }
                ],
            }
        }

        # Mock the NBA API fetches
        gamecardfeed_raw = {
            "modules": [
                {
                    "cards": [
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "001",
                                "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "score": 110},
                                "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "score": 105},
                                "gameStatus": 3,
                                "gameTimeUtc": "2024-10-22T23:30:00Z",
                                "gameStatusText": "Final",
                            },
                        }
                    ]
                }
            ]
        }
        with patch.object(nba_service, "_fetch_gamecardfeed_raw", return_value=gamecardfeed_raw):
            with patch.object(nba_service, "_fetch_scoreboard_raw", return_value=raw_response):
                with patch.object(nba_service, "_store_data") as mock_store:
                    # Act
                    games, scoreboard_date = await nba_service.get_gamecardfeed_cached()

                    # Assert
                    assert len(games) == 1
                    assert games[0]["game_id"] == "001"
                    assert scoreboard_date == today
                    mock_store.assert_any_call("nba:gamecardfeed:live", gamecardfeed_raw)
                    mock_store.assert_any_call("nba:scoreboard:live", raw_response)

    @pytest.mark.asyncio
    async def test_api_failure_returns_stale_data(self, nba_service, mock_repo):
        """Test that API failure returns stale cached data as fallback."""
        # Arrange
        today = datetime.now(UTC).date()
        stale_cache = ExternalData(
            key="nba:scoreboard:live",
            data_format=DataFormat.JSON,
            data_json={
                "scoreboard": {
                    "gameDate": today.isoformat(),
                    "games": [
                        {
                            "gameId": "old_game",
                            "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "score": 100},
                            "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "score": 95},
                            "gameStatus": 3,
                            "gameTimeUTC": "2024-10-22T23:00:00Z",
                            "gameStatusText": "Final",
                            "gameLabel": "",
                        }
                    ],
                }
            },
            updated_at=datetime.now(UTC) - timedelta(hours=1),  # Very stale
        )
        mock_repo.get_by_key.return_value = stale_cache

        # Mock API failure (gamecardfeed fetch will raise)
        with patch.object(nba_service, "_fetch_gamecardfeed_raw", side_effect=Exception("API Error")):
            # Act
            games, scoreboard_date = await nba_service.get_gamecardfeed_cached()

            # Assert - should return stale data
            assert len(games) == 1
            assert games[0]["game_id"] == "old_game"
            assert scoreboard_date == today

    @pytest.mark.asyncio
    async def test_api_failure_no_cache_raises_exception(self, nba_service, mock_repo):
        """Test that API failure with no cache raises exception."""
        # Arrange
        mock_repo.get_by_key.return_value = None  # No cache

        # Mock API failure with no cache (gamecardfeed fetch will raise)
        with patch.object(nba_service, "_fetch_gamecardfeed_raw", side_effect=Exception("API Error")):
            # Act & Assert
            with pytest.raises(Exception, match="API Error"):
                await nba_service.get_gamecardfeed_cached()

    @pytest.mark.asyncio
    async def test_parse_gamecardfeed_various_statuses(self, nba_service, mock_repo):
        """Test parsing of gamecardfeed with gamesStatus values 1 (pregame), 2 (ingame), 3 (final)."""
        # Arrange - ensure cache miss so fetch path is used
        mock_repo.get_by_key.return_value = None

        today = datetime.now(UTC).date()

        gamecardfeed_raw = {
            "modules": [
                {
                    "cards": [
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "g1",
                                "homeTeam": {"teamId": 1610612747, "score": None, "teamTricode": "LAL"},
                                "awayTeam": {"teamId": 1610612738, "score": None, "teamTricode": "BOS"},
                                "gameStatus": 1,
                                "gameTimeUtc": f"{today.isoformat()}T19:00:00Z",
                                "gameStatusText": "Scheduled",
                            },
                        },
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "g2",
                                "homeTeam": {"teamId": 1610612744, "score": 50, "teamTricode": "GSW"},
                                "awayTeam": {"teamId": 1610612752, "score": 48, "teamTricode": "NYK"},
                                "gameStatus": 2,
                                "gameTimeUtc": f"{today.isoformat()}T20:00:00Z",
                                "gameStatusText": "In Progress",
                                "gameClock": "PT11M23.45S",
                            },
                        },
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "g3",
                                "homeTeam": {"teamId": 1610612755, "score": 110, "teamTricode": "MIA"},
                                "awayTeam": {"teamId": 1610612760, "score": 108, "teamTricode": "PHI"},
                                "gameStatus": 3,
                                "gameTimeUtc": f"{today.isoformat()}T21:00:00Z",
                                "gameStatusText": "Final",
                            },
                        },
                    ]
                }
            ]
        }

        scoreboard_raw = {"scoreboard": {"gameDate": today.isoformat(), "games": []}}

        # Act
        with patch.object(nba_service, "_fetch_gamecardfeed_raw", return_value=gamecardfeed_raw):
            with patch.object(nba_service, "_fetch_scoreboard_raw", return_value=scoreboard_raw):
                games, scoreboard_date = await nba_service.get_gamecardfeed_cached()

        # Assert
        assert scoreboard_date == today
        assert len(games) == 3
        statuses = [g["status"] for g in games]
        assert statuses[0] == NBAGameStatus.PREGAME
        assert statuses[1] == NBAGameStatus.INGAME
        assert statuses[2] == NBAGameStatus.FINAL
        # date_time should be parsed to a timezone-aware datetime
        for g in games:
            assert g["date_time"].tzinfo is not None


class TestGetScheduleCached:
    """Tests for get_schedule_cached method."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_schedule(self, nba_service, mock_repo):
        """Test that valid cached schedule is returned."""
        # Arrange
        season = "2024-25"
        today = datetime.now(UTC).date()
        # Mock raw API response structure (scheduleleaguev2 format)
        cached_data = ExternalData(
            key=f"nba:schedule:{season}",
            data_format=DataFormat.JSON,
            data_json={
                "leagueSchedule": {
                    "seasonYear": season,
                    "gameDates": [
                        {
                            "gameDate": "2024-10-15",
                            "games": [
                                {
                                    "gameId": "123",
                                    "gameStatus": 3,
                                    "gameDateTimeUTC": "2024-10-15T23:00:00Z",
                                    "gameDateUTC": "2024-10-15",
                                    "homeTeam": {
                                        "teamId": 1610612747,
                                        "teamTricode": "LAL",
                                        "score": 120,
                                    },
                                    "awayTeam": {
                                        "teamId": 1610612738,
                                        "teamTricode": "BOS",
                                        "score": 115,
                                    },
                                    "gameStatusText": "Final",
                                    "gameLabel": "",
                                    "seriesText": "",
                                }
                            ],
                        }
                    ],
                }
            },
            updated_at=datetime.now(UTC),  # Fresh
        )
        mock_repo.get_by_key.return_value = cached_data

        # Act
        games, season_year = await nba_service.get_schedule_cached(today, season)

        # Assert
        assert len(games) == 1
        assert games[0]["game_id"] == "123"
        assert season_year == season

    @pytest.mark.asyncio
    async def test_stale_schedule_fetches_fresh(self, nba_service, mock_repo, sample_schedule_data):
        """Test that stale schedule triggers fresh fetch for current season."""
        # Arrange
        season = nba_service.get_current_season()  # Use current season to trigger 24h TTL
        today = datetime.now(UTC).date()
        stale_cache = ExternalData(
            key=f"nba:schedule:{season}",
            data_format=DataFormat.JSON,
            data_json={"leagueSchedule": {"seasonYear": season, "gameDates": []}},
            updated_at=datetime.now(UTC) - timedelta(days=2),  # Stale (>24h for current season)
        )
        mock_repo.get_by_key.return_value = stale_cache

        # Mock raw API response (scheduleleaguev2 format)
        raw_response = {
            "leagueSchedule": {
                "seasonYear": season,
                "gameDates": [
                    {
                        "gameDate": today.isoformat(),
                        "games": [
                            {
                                "gameId": "0022400100",
                                "gameStatus": 3,
                                "gameDateTimeUTC": f"{today.isoformat()}T23:00:00Z",
                                "gameDateUTC": today.isoformat(),
                                "homeTeam": {
                                    "teamId": 1610612747,
                                    "teamTricode": "LAL",
                                    "score": 120,
                                },
                                "awayTeam": {
                                    "teamId": 1610612738,
                                    "teamTricode": "BOS",
                                    "score": 115,
                                },
                                "gameStatusText": "Final",
                                "gameLabel": "",
                                "seriesText": "",
                            }
                        ],
                    }
                ],
            }
        }

        with patch.object(nba_service, "_fetch_schedule_raw", return_value=raw_response):
            with patch.object(nba_service, "_store_data") as mock_store:
                # Act
                games, season_year = await nba_service.get_schedule_cached(today, season)

                # Assert
                assert len(games) == 0  # Game is on scoreboard_date, so excluded (games < scoreboard_date)
                mock_store.assert_called_once()


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


class TestCacheValidation:
    """Tests for _is_cache_valid method."""

    def test_fresh_cache_is_valid(self, nba_service):
        """Test that recently updated cache is valid."""
        # Arrange
        updated_at = datetime.now(UTC) - timedelta(seconds=30)
        ttl = 60  # 1 minute

        # Act
        is_valid = nba_service._is_cache_valid(updated_at, ttl)

        # Assert
        assert is_valid is True

    def test_stale_cache_is_invalid(self, nba_service):
        """Test that old cache is invalid."""
        # Arrange
        updated_at = datetime.now(UTC) - timedelta(minutes=10)
        ttl = 60  # 1 minute

        # Act
        is_valid = nba_service._is_cache_valid(updated_at, ttl)

        # Assert
        assert is_valid is False

    def test_handles_naive_datetime(self, nba_service):
        """Test that naive datetime is handled correctly."""
        # Arrange
        updated_at = datetime.now()  # Naive datetime
        ttl = 60

        # Act
        is_valid = nba_service._is_cache_valid(updated_at, ttl)

        # Assert - should not raise exception
        assert isinstance(is_valid, bool)


class TestBackgroundJobMethods:
    """Tests for background job wrapper methods."""

    @pytest.mark.asyncio
    async def test_update_scoreboard_calls_get_cached(self, nba_service, sample_scoreboard_data):
        """Test that update_scoreboard calls get_gamecardfeed_cached."""
        # Arrange
        today = datetime.now(UTC).date()
        with patch.object(
            nba_service,
            "get_gamecardfeed_cached",
            return_value=(sample_scoreboard_data, today),
        ) as mock_get:
            # Act
            await nba_service.update_scoreboard()

            # Assert
            mock_get.assert_called_once()


class TestHasActiveGames:
    """Tests for has_active_games utility method."""

    def test_detects_pregame_status(self, nba_service):
        """Test that pregame games are detected as active."""
        # Arrange
        games = [
            {"status": NBAGameStatus.PREGAME, "game_id": "1"},
            {"status": NBAGameStatus.FINAL, "game_id": "2"},
        ]

        # Act
        has_active = nba_service.has_active_games(games)

        # Assert
        assert has_active is True

    def test_detects_live_games(self, nba_service):
        """Test that live games are detected as active."""
        # Arrange
        games = [
            {"status": NBAGameStatus.FINAL, "game_id": "1"},
            {"status": NBAGameStatus.INGAME, "game_id": "2"},
        ]

        # Act
        has_active = nba_service.has_active_games(games)

        # Assert
        assert has_active is True

    def test_no_active_games(self, nba_service):
        """Test that only final games are not active."""
        # Arrange
        games = [
            {"status": NBAGameStatus.FINAL, "game_id": "1"},
            {"status": NBAGameStatus.FINAL, "game_id": "2"},
        ]

        # Act
        has_active = nba_service.has_active_games(games)

        # Assert
        assert has_active is False

    def test_empty_games_list(self, nba_service):
        """Test that empty games list returns False."""
        # Arrange
        games = []

        # Act
        has_active = nba_service.has_active_games(games)

        # Assert
        assert has_active is False


# Cleanup tests removed - cleanup_old_scoreboards method was removed from NbaDataService


class TestBuildGameIdentifier:
    """Tests for _build_game_identifier helper."""

    def test_builds_identifier_with_datetime(self, nba_service):
        """Test game identifier with datetime."""
        # Act
        identifier = nba_service._build_game_identifier("2024-10-22T23:00:00Z", 1610612747, 1610612738)

        # Assert
        assert identifier == "2024-10-22T23:00:00Z-1610612747-vs-1610612738"

    def test_builds_identifier_without_datetime(self, nba_service):
        """Test game identifier fallback without datetime."""
        # Act
        identifier = nba_service._build_game_identifier("", 1610612747, 1610612738)

        # Assert
        assert identifier == "unknown-1610612747-vs-1610612738"
