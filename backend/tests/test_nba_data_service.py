"""Tests for NbaDataService with database-backed caching."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.external_data import DataFormat, ExternalData
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.types.nba_game_status import NBAGameStatus

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
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


class TestParseGamecardfeed:
    """Tests for _parse_gamecardfeed using the sample fixture."""

    @pytest.fixture
    def gamecardfeed_fixture(self):
        with open(FIXTURES_DIR / "sample-nba-gamecardfeed-response.json") as f:
            return json.load(f)

    def test_parses_all_games(self, nba_service, gamecardfeed_fixture):
        games, game_ids, scoreboard_date = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        assert len(games) == 4
        assert len(game_ids) == 4

    def test_game_ids(self, nba_service, gamecardfeed_fixture):
        games, game_ids, _ = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        expected_ids = {"0022501050", "0022501047", "0022501048", "0022501049"}
        assert game_ids == expected_ids
        assert {g["game_id"] for g in games} == expected_ids

    def test_scoreboard_date(self, nba_service, gamecardfeed_fixture):
        _, _, scoreboard_date = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        # Games are at 2026-03-25 UTC, which is 2026-03-24 US/Eastern
        from datetime import date

        assert scoreboard_date == date(2026, 3, 24)

    def test_game_statuses(self, nba_service, gamecardfeed_fixture):
        games, _, _ = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        status_by_id = {g["game_id"]: g["status"] for g in games}
        assert status_by_id["0022501050"] == NBAGameStatus.INGAME  # DEN @ PHX, halftime
        assert status_by_id["0022501047"] == NBAGameStatus.FINAL  # SAC @ CHA
        assert status_by_id["0022501048"] == NBAGameStatus.FINAL  # NOP @ NYK
        assert status_by_id["0022501049"] == NBAGameStatus.FINAL  # ORL @ CLE

    def test_scores(self, nba_service, gamecardfeed_fixture):
        games, _, _ = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        cha_game = next(g for g in games if g["game_id"] == "0022501047")
        assert cha_game["home_score"] == 134  # CHA
        assert cha_game["away_score"] == 90  # SAC

    def test_tricodes(self, nba_service, gamecardfeed_fixture):
        games, _, _ = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        den_phx = next(g for g in games if g["game_id"] == "0022501050")
        assert den_phx["away_tricode"] == "DEN"
        assert den_phx["home_tricode"] == "PHX"

    def test_game_url_from_share_url(self, nba_service, gamecardfeed_fixture):
        games, _, _ = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        url_by_id = {g["game_id"]: g["game_url"] for g in games}
        assert url_by_id["0022501050"] == "https://www.nba.com/game/den-vs-phx-0022501050"
        assert url_by_id["0022501047"] == "https://www.nba.com/game/sac-vs-cha-0022501047"
        assert url_by_id["0022501048"] == "https://www.nba.com/game/nop-vs-nyk-0022501048"
        assert url_by_id["0022501049"] == "https://www.nba.com/game/orl-vs-cle-0022501049"

    @pytest.mark.asyncio
    async def test_get_game_data_includes_game_url(self, nba_service, gamecardfeed_fixture):
        """game_url flows through get_game_data into the final DataFrame."""
        season = nba_service.get_current_season()
        cdn_schedule_raw = {"leagueSchedule": {"seasonYear": season, "gameDates": []}}

        with patch.object(
            nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_fixture, cdn_schedule_raw)
        ):
            result = await nba_service.get_game_data(season)

        assert "game_url" in result.columns
        den_phx = result[result["game_id"] == "0022501050"].iloc[0]
        assert den_phx["game_url"] == "https://www.nba.com/game/den-vs-phx-0022501050"
