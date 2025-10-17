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
    service = NbaDataService(mock_db_session)
    service.repo = mock_repo
    return service


@pytest.fixture
def sample_scoreboard_data():
    """Sample scoreboard data from NBA API."""
    return [
        {
            "game_id": "0022400001",
            "date_time": "2024-10-22T23:30:00Z",
            "home_team": 1610612747,  # Lakers
            "home_score": 110,
            "away_team": 1610612738,  # Celtics
            "away_score": 105,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        },
        {
            "game_id": "0022400002",
            "date_time": "2024-10-22T23:00:00Z",
            "home_team": 1610612744,  # Warriors
            "home_score": 95,
            "away_team": 1610612752,  # Knicks
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
            "home_score": 120,
            "away_team": 1610612738,
            "away_score": 115,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        }
    ]


class TestGetScoreboardCached:
    """Tests for get_scoreboard_cached method."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_data(self, nba_service, mock_repo):
        """Test that valid cached data is returned without fetching from API."""
        # Arrange
        today = datetime.now(UTC).date()
        cached_data = ExternalData(
            key=f"nba:scoreboard:{today.isoformat()}",
            data_format=DataFormat.JSON,
            data_json={
                "games": [{"game_id": "123", "home_team": 1610612747}],
                "date": today.isoformat(),
            },
            updated_at=datetime.now(UTC),  # Fresh cache
        )
        mock_repo.get_by_key.return_value = cached_data

        # Act
        games, scoreboard_date = await nba_service.get_scoreboard_cached()

        # Assert
        assert games == [{"game_id": "123", "home_team": 1610612747}]
        assert scoreboard_date == today
        mock_repo.get_by_key.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_cache_fetches_fresh_data(
        self, nba_service, mock_repo, sample_scoreboard_data
    ):
        """Test that stale cached data triggers a fresh API fetch."""
        # Arrange
        today = datetime.now(UTC).date()
        stale_cache = ExternalData(
            key=f"nba:scoreboard:{today.isoformat()}",
            data_format=DataFormat.JSON,
            data_json={"games": [], "date": today.isoformat()},
            updated_at=datetime.now(UTC) - timedelta(minutes=10),  # Stale (>5 min)
        )
        mock_repo.get_by_key.return_value = stale_cache

        # Mock the NBA API fetch
        with patch.object(
            nba_service, "_fetch_scoreboard", return_value=(sample_scoreboard_data, today)
        ):
            with patch.object(nba_service, "_store_scoreboard") as mock_store:
                # Act
                games, scoreboard_date = await nba_service.get_scoreboard_cached()

                # Assert
                assert len(games) == 2
                assert scoreboard_date == today
                mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_and_stores(
        self, nba_service, mock_repo, sample_scoreboard_data
    ):
        """Test that cache miss fetches from API and stores in database."""
        # Arrange
        today = datetime.now(UTC).date()  # Use UTC date like the service does
        mock_repo.get_by_key.return_value = None  # Cache miss

        # Mock the NBA API fetch
        with patch.object(
            nba_service, "_fetch_scoreboard", return_value=(sample_scoreboard_data, today)
        ):
            with patch.object(nba_service, "_store_scoreboard") as mock_store:
                # Act
                games, scoreboard_date = await nba_service.get_scoreboard_cached()

                # Assert
                assert games == sample_scoreboard_data
                assert scoreboard_date == today
                mock_store.assert_called_once_with(
                    f"nba:scoreboard:{today.isoformat()}", sample_scoreboard_data, today
                )

    @pytest.mark.asyncio
    async def test_api_failure_returns_stale_data(self, nba_service, mock_repo):
        """Test that API failure returns stale cached data as fallback."""
        # Arrange
        today = datetime.now(UTC).date()
        stale_cache = ExternalData(
            key=f"nba:scoreboard:{today.isoformat()}",
            data_format=DataFormat.JSON,
            data_json={
                "games": [{"game_id": "old_game"}],
                "date": today.isoformat(),
            },
            updated_at=datetime.now(UTC) - timedelta(hours=1),  # Very stale
        )
        mock_repo.get_by_key.return_value = stale_cache

        # Mock API failure
        with patch.object(
            nba_service, "_fetch_scoreboard", side_effect=Exception("API Error")
        ):
            # Act
            games, scoreboard_date = await nba_service.get_scoreboard_cached()

            # Assert - should return stale data
            assert games == [{"game_id": "old_game"}]
            assert scoreboard_date == today

    @pytest.mark.asyncio
    async def test_api_failure_no_cache_raises_exception(self, nba_service, mock_repo):
        """Test that API failure with no cache raises exception."""
        # Arrange
        mock_repo.get_by_key.return_value = None  # No cache

        # Mock API failure
        with patch.object(
            nba_service, "_fetch_scoreboard", side_effect=Exception("API Error")
        ):
            # Act & Assert
            with pytest.raises(Exception, match="API Error"):
                await nba_service.get_scoreboard_cached()


class TestGetScheduleCached:
    """Tests for get_schedule_cached method."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_schedule(self, nba_service, mock_repo):
        """Test that valid cached schedule is returned."""
        # Arrange
        season = "2024-25"
        today = datetime.now(UTC).date()
        cached_data = ExternalData(
            key=f"nba:schedule:{season}",
            data_format=DataFormat.JSON,
            data_json={
                "games": [{"game_id": "123"}],
                "season": season,
            },
            updated_at=datetime.now(UTC),  # Fresh
        )
        mock_repo.get_by_key.return_value = cached_data

        # Act
        games, season_year = await nba_service.get_schedule_cached(today, season)

        # Assert
        assert games == [{"game_id": "123"}]
        assert season_year == season

    @pytest.mark.asyncio
    async def test_stale_schedule_fetches_fresh(
        self, nba_service, mock_repo, sample_schedule_data
    ):
        """Test that stale schedule triggers fresh fetch."""
        # Arrange
        season = "2024-25"
        today = datetime.now(UTC).date()
        stale_cache = ExternalData(
            key=f"nba:schedule:{season}",
            data_format=DataFormat.JSON,
            data_json={"games": [], "season": season},
            updated_at=datetime.now(UTC) - timedelta(days=2),  # Stale (>24h)
        )
        mock_repo.get_by_key.return_value = stale_cache

        with patch.object(
            nba_service, "_fetch_schedule", return_value=(sample_schedule_data, season)
        ):
            with patch.object(nba_service, "_store_schedule") as mock_store:
                # Act
                games, season_year = await nba_service.get_schedule_cached(
                    today, season
                )

                # Assert
                assert len(games) == 1
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
    async def test_update_scoreboard_calls_get_cached(
        self, nba_service, sample_scoreboard_data
    ):
        """Test that update_scoreboard calls get_scoreboard_cached."""
        # Arrange
        today = datetime.now(UTC).date()
        with patch.object(
            nba_service,
            "get_scoreboard_cached",
            return_value=(sample_scoreboard_data, today),
        ) as mock_get:
            # Act
            await nba_service.update_scoreboard()

            # Assert
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_schedule_calls_get_cached(
        self, nba_service, sample_schedule_data
    ):
        """Test that update_schedule calls get_schedule_cached."""
        # Arrange
        season = "2024-25"
        today = datetime.now(UTC).date()
        with patch.object(
            nba_service,
            "get_schedule_cached",
            return_value=(sample_schedule_data, season),
        ) as mock_get:
            # Act
            await nba_service.update_schedule(season, today)

            # Assert
            mock_get.assert_called_once_with(scoreboard_date=today, season=season)


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


class TestCleanupOldScoreboards:
    """Tests for cleanup_old_scoreboards method."""

    @pytest.mark.asyncio
    async def test_deletes_old_scoreboards(self, nba_service, mock_repo):
        """Test that old scoreboards are deleted."""
        # Arrange
        old_record = ExternalData(
            key="nba:scoreboard:2023-01-01",
            data_format=DataFormat.JSON,
            data_json={},
            created_at=datetime.now(UTC) - timedelta(days=400),
        )
        recent_record = ExternalData(
            key="nba:scoreboard:2024-10-01",
            data_format=DataFormat.JSON,
            data_json={},
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
        mock_repo.get_by_key_prefix.return_value = [old_record, recent_record]

        # Act
        deleted = await nba_service.cleanup_old_scoreboards(keep_days=365)

        # Assert
        assert deleted == 1
        mock_repo.delete.assert_called_once_with(old_record)

    @pytest.mark.asyncio
    async def test_keeps_recent_scoreboards(self, nba_service, mock_repo):
        """Test that recent scoreboards are not deleted."""
        # Arrange
        recent_record = ExternalData(
            key="nba:scoreboard:2024-10-01",
            data_format=DataFormat.JSON,
            data_json={},
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
        mock_repo.get_by_key_prefix.return_value = [recent_record]

        # Act
        deleted = await nba_service.cleanup_old_scoreboards(keep_days=365)

        # Assert
        assert deleted == 0
        mock_repo.delete.assert_not_called()


class TestBuildGameIdentifier:
    """Tests for _build_game_identifier helper."""

    def test_builds_identifier_with_datetime(self, nba_service):
        """Test game identifier with datetime."""
        # Act
        identifier = nba_service._build_game_identifier(
            "2024-10-22T23:00:00Z", 1610612747, 1610612738
        )

        # Assert
        assert identifier == "2024-10-22T23:00:00Z-1610612747-vs-1610612738"

    def test_builds_identifier_without_datetime(self, nba_service):
        """Test game identifier fallback without datetime."""
        # Act
        identifier = nba_service._build_game_identifier("", 1610612747, 1610612738)

        # Assert
        assert identifier == "unknown-1610612747-vs-1610612738"
