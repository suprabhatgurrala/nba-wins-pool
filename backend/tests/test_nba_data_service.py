"""Tests for NbaDataService with database-backed caching."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        """Schedule supplies all games; gamecardfeed overlays live fields for today's games."""
        season = nba_service.get_current_season()

        # today_game appears in both feeds; hist_game only in the schedule
        gamecardfeed_raw = {
            "modules": [
                {
                    "cards": [
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "today_game",
                                "homeTeam": {"teamId": 1610612747, "score": 72, "teamTricode": "LAL"},
                                "awayTeam": {"teamId": 1610612738, "score": 68, "teamTricode": "BOS"},
                                "gameStatus": 2,  # INGAME
                                "gameTimeUtc": "2024-10-22T23:30:00Z",
                                "gameStatusText": "Q3 5:00",
                                "gameClock": "PT05M00.00S",
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
                        "gameDate": "10/15/2024 00:00:00",
                        "games": [
                            {
                                "gameId": "hist_game",
                                "gameStatus": 3,
                                "gameDateTimeUTC": "2024-10-15T23:00:00Z",
                                "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "score": 120},
                                "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "score": 115},
                                "gameStatusText": "Final",
                                "gameLabel": "",
                                "seriesText": "",
                                "arenaName": "Crypto.com Arena",
                                "arenaCity": "Los Angeles",
                                "arenaState": "CA",
                            }
                        ],
                    },
                    {
                        "gameDate": "10/22/2024 00:00:00",
                        "games": [
                            {
                                "gameId": "today_game",
                                "gameStatus": 1,
                                "gameDateTimeUTC": "2024-10-22T23:30:00Z",
                                "homeTeam": {"teamId": 1610612747, "teamTricode": "LAL", "score": 0},
                                "awayTeam": {"teamId": 1610612738, "teamTricode": "BOS", "score": 0},
                                "gameStatusText": "7:30 pm ET",
                                "gameLabel": "",
                                "seriesText": "",
                                "arenaName": "Crypto.com Arena",
                                "arenaCity": "Los Angeles",
                                "arenaState": "CA",
                            }
                        ],
                    },
                ],
            }
        }

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert set(result["game_id"]) == {"hist_game", "today_game"}
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

        assert len(games) == 5
        assert len(game_ids) == 5

    def test_game_ids(self, nba_service, gamecardfeed_fixture):
        games, game_ids, _ = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        expected_ids = {"0022501050", "0022501047", "0022501048", "0022501049", "0022501051"}
        assert game_ids == expected_ids
        assert {g["game_id"] for g in games} == expected_ids

    def test_scoreboard_date(self, nba_service, gamecardfeed_fixture):
        _, _, scoreboard_date = nba_service._parse_gamecardfeed(gamecardfeed_fixture)

        # First game in fixture is 0022501051 at 2026-03-25T23:00:00Z = 2026-03-25 US/Eastern
        from datetime import date

        assert scoreboard_date == date(2026, 3, 25)

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


def _make_schedule_raw(season: str, game_date: str, games: list[dict]) -> dict:
    """Helper to build a minimal CDN schedule response."""
    return {
        "leagueSchedule": {
            "seasonYear": season,
            "gameDates": [{"gameDate": game_date, "games": games}],
        }
    }


def _make_schedule_game(game_id: str, timestamp: str, **kwargs) -> dict:
    """Helper to build a minimal schedule game entry."""
    return {
        "gameId": game_id,
        "gameStatus": 1,
        "gameDateTimeUTC": timestamp,
        "homeTeam": {"teamId": 1, "teamTricode": "HOM", "score": 0},
        "awayTeam": {"teamId": 2, "teamTricode": "AWY", "score": 0},
        "gameStatusText": "7:30 pm ET",
        "gameLabel": "",
        "seriesText": "",
        **kwargs,
    }


def _make_gamecardfeed_raw(game_id: str, timestamp: str, **kwargs) -> dict:
    """Helper to build a minimal gamecardfeed response with one game."""
    return {
        "modules": [
            {
                "cards": [
                    {
                        "cardType": "game",
                        "cardData": {
                            "gameId": game_id,
                            "gameTimeUtc": timestamp,
                            "gameStatus": 2,
                            "gameStatusText": "Q2 3:00",
                            "gameClock": "PT03M00.00S",
                            "homeTeam": {"teamId": 1, "score": 55, "teamTricode": "HOM"},
                            "awayTeam": {"teamId": 2, "score": 50, "teamTricode": "AWY"},
                            **kwargs,
                        },
                    }
                ]
            }
        ]
    }


class TestGameUrl:
    """game_url is populated from shareUrl (gamecardfeed) or constructed from teamSlugs (schedule)."""

    def test_share_url_used_when_present(self, nba_service):
        game = {
            "gameId": "0022501042",
            "gameStatus": 1,
            "homeTeam": {"teamId": 1, "teamTricode": "DET", "teamSlug": "pistons", "score": 0},
            "awayTeam": {"teamId": 2, "teamTricode": "ATL", "teamSlug": "hawks", "score": 0},
            "gameStatusText": "7:00 pm ET",
            "shareUrl": "https://www.nba.com/game/atl-vs-det-0022501042",
        }
        result = nba_service._parse_game_data(game, "2026-03-25T23:00:00Z")

        assert result["game_url"] == "https://www.nba.com/game/atl-vs-det-0022501042"

    def test_url_none_when_no_share_url(self, nba_service):
        game = {
            "gameId": "0022501051",
            "gameStatus": 1,
            "homeTeam": {"teamId": 1, "teamTricode": "DET", "score": 0},
            "awayTeam": {"teamId": 2, "teamTricode": "ATL", "score": 0},
            "gameStatusText": "7:00 pm ET",
        }
        result = nba_service._parse_game_data(game, "2026-03-25T23:00:00Z")

        assert result["game_url"] is None

    @pytest.mark.asyncio
    async def test_gamecardfeed_share_url_overrides_schedule_null(self, nba_service):
        """shareUrl from gamecardfeed overlays the schedule's null game_url for today's games."""
        season = nba_service.get_current_season()
        timestamp = "2026-03-25T23:00:00Z"
        gamecardfeed_raw = {
            "modules": [
                {
                    "cards": [
                        {
                            "cardType": "game",
                            "cardData": {
                                "gameId": "0022501051",
                                "gameTimeUtc": timestamp,
                                "gameStatus": 1,
                                "gameStatusText": "7:00 pm ET",
                                "homeTeam": {"teamId": 1, "score": 0, "teamTricode": "DET"},
                                "awayTeam": {"teamId": 2, "score": 0, "teamTricode": "ATL"},
                                "shareUrl": "https://www.nba.com/game/atl-vs-det-0022501051",
                            },
                        }
                    ]
                }
            ]
        }
        # Schedule entry has no shareUrl → game_url will be None or slug-constructed
        cdn_schedule_raw = _make_schedule_raw(
            season,
            "03/25/2026 00:00:00",
            [_make_schedule_game("0022501051", timestamp)],  # no shareUrl, no slugs
        )

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        row = result[result["game_id"] == "0022501051"].iloc[0]
        assert row["game_url"] == "https://www.nba.com/game/atl-vs-det-0022501051"

    def test_url_none_when_no_share_url_and_no_slugs(self, nba_service):
        game = {
            "gameId": "0022501051",
            "gameStatus": 1,
            "homeTeam": {"teamId": 1, "teamTricode": "DET", "score": 0},
            "awayTeam": {"teamId": 2, "teamTricode": "ATL", "score": 0},
            "gameStatusText": "7:00 pm ET",
        }
        result = nba_service._parse_game_data(game, "2026-03-25T23:00:00Z")

        assert result["game_url"] is None


class TestArenaFields:
    """Arena name/city/state are parsed from schedule and flow through to game data."""

    def test_parse_game_data_extracts_arena_fields(self, nba_service):
        game = {
            "gameId": "0022501042",
            "gameStatus": 1,
            "homeTeam": {"teamId": 1, "teamTricode": "HOM", "score": 0},
            "awayTeam": {"teamId": 2, "teamTricode": "AWY", "score": 0},
            "gameStatusText": "7:30 pm ET",
            "arenaName": "Little Caesars Arena",
            "arenaCity": "Detroit",
            "arenaState": "MI",
        }
        result = nba_service._parse_game_data(game, "2026-03-25T23:00:00Z")

        assert result["arena_name"] == "Little Caesars Arena"
        assert result["arena_city"] == "Detroit"
        assert result["arena_state"] == "MI"

    def test_parse_game_data_arena_fields_none_when_absent(self, nba_service):
        game = {
            "gameId": "0022501042",
            "gameStatus": 1,
            "homeTeam": {"teamId": 1, "teamTricode": "HOM", "score": 0},
            "awayTeam": {"teamId": 2, "teamTricode": "AWY", "score": 0},
            "gameStatusText": "7:30 pm ET",
        }
        result = nba_service._parse_game_data(game, "2026-03-25T23:00:00Z")

        assert result["arena_name"] is None
        assert result["arena_city"] is None
        assert result["arena_state"] is None

    @pytest.mark.asyncio
    async def test_get_game_data_arena_fields_from_schedule(self, nba_service):
        """Arena fields come from the schedule and are present in the merged DataFrame."""
        season = nba_service.get_current_season()
        timestamp = "2026-03-25T23:00:00Z"
        gamecardfeed_raw = _make_gamecardfeed_raw("0022501042", timestamp)
        cdn_schedule_raw = _make_schedule_raw(
            season,
            "03/25/2026 00:00:00",
            [
                _make_schedule_game(
                    "0022501042",
                    timestamp,
                    arenaName="Little Caesars Arena",
                    arenaCity="Detroit",
                    arenaState="MI",
                )
            ],
        )

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        row = result[result["game_id"] == "0022501042"].iloc[0]
        assert row["arena_name"] == "Little Caesars Arena"
        assert row["arena_city"] == "Detroit"
        assert row["arena_state"] == "MI"


class TestLiveFieldsOverlay:
    """Gamecardfeed live fields override schedule fields for today's games."""

    @pytest.mark.asyncio
    async def test_live_status_overrides_schedule_status(self, nba_service):
        season = nba_service.get_current_season()
        timestamp = "2026-03-25T23:00:00Z"
        gamecardfeed_raw = _make_gamecardfeed_raw("0022501042", timestamp)  # status=2, INGAME
        cdn_schedule_raw = _make_schedule_raw(
            season,
            "03/25/2026 00:00:00",
            [_make_schedule_game("0022501042", timestamp)],  # status=1, PREGAME in schedule
        )

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        row = result[result["game_id"] == "0022501042"].iloc[0]
        assert row["status"] == NBAGameStatus.INGAME

    @pytest.mark.asyncio
    async def test_live_scores_override_schedule_scores(self, nba_service):
        season = nba_service.get_current_season()
        timestamp = "2026-03-25T23:00:00Z"
        gamecardfeed_raw = _make_gamecardfeed_raw("0022501042", timestamp)  # home=55, away=50
        cdn_schedule_raw = _make_schedule_raw(
            season,
            "03/25/2026 00:00:00",
            [_make_schedule_game("0022501042", timestamp)],  # scores both 0 in schedule
        )

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        row = result[result["game_id"] == "0022501042"].iloc[0]
        assert row["home_score"] == 55
        assert row["away_score"] == 50

    @pytest.mark.asyncio
    async def test_schedule_only_games_unaffected_by_overlay(self, nba_service):
        """Historical games not in the gamecardfeed keep their schedule data intact."""
        season = nba_service.get_current_season()
        live_ts = "2026-03-25T23:00:00Z"
        hist_ts = "2026-03-24T23:00:00Z"
        gamecardfeed_raw = _make_gamecardfeed_raw("today_game", live_ts)
        cdn_schedule_raw = _make_schedule_raw(
            season,
            "03/25/2026 00:00:00",
            [
                _make_schedule_game("hist_game", hist_ts),
                _make_schedule_game("today_game", live_ts),
            ],
        )

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        assert len(result) == 2
        hist = result[result["game_id"] == "hist_game"].iloc[0]
        assert hist["status"] == NBAGameStatus.PREGAME  # unchanged from schedule


class TestGameDateParsing:
    """gameDate in MM/DD/YYYY HH:MM:SS format is handled correctly."""

    @pytest.mark.asyncio
    async def test_game_date_mm_dd_yyyy_format(self, nba_service):
        """Schedule gameDates in MM/DD/YYYY HH:MM:SS format parse without error."""
        season = nba_service.get_current_season()
        timestamp = "2026-03-25T23:00:00Z"
        gamecardfeed_raw = _make_gamecardfeed_raw("0022501042", timestamp)
        cdn_schedule_raw = _make_schedule_raw(
            season,
            "03/25/2026 00:00:00",
            [_make_schedule_game("0022501042", timestamp)],
        )

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        assert len(result) == 1
        assert result.iloc[0]["game_id"] == "0022501042"

    @pytest.mark.asyncio
    async def test_game_date_future_dates_excluded(self, nba_service):
        """Games in gameDates blocks after scoreboard_date are not included."""
        season = nba_service.get_current_season()
        today_ts = "2026-03-25T23:00:00Z"
        future_ts = "2026-03-27T23:00:00Z"
        gamecardfeed_raw = _make_gamecardfeed_raw("today_game", today_ts)
        cdn_schedule_raw = {
            "leagueSchedule": {
                "seasonYear": season,
                "gameDates": [
                    {
                        "gameDate": "03/25/2026 00:00:00",
                        "games": [_make_schedule_game("today_game", today_ts)],
                    },
                    {
                        "gameDate": "03/27/2026 00:00:00",
                        "games": [_make_schedule_game("future_game", future_ts)],
                    },
                ],
            }
        }

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        assert "future_game" not in result["game_id"].values


def _mock_requests_get(fixture_data: dict):
    mock_response = MagicMock()
    mock_response.json.return_value = fixture_data
    mock_response.raise_for_status.return_value = None
    return mock_response


class TestGetFanDuelMoneylineOdds:
    """Tests for NbaDataService.get_fanduel_moneyline_odds."""

    def test_parses_fixture(self, nba_service):
        """Vig-adjusted probabilities are computed correctly from the fixture."""
        fixture = json.loads((FIXTURES_DIR / "sample-nba-odds-today-response.json").read_text())

        with patch("nba_wins_pool.services.nba_data_service.requests.get", return_value=_mock_requests_get(fixture)):
            result = nba_service.get_fanduel_moneyline_odds()

        # Game 0022501042: FanDuel home 4.200, away 1.247
        assert "0022501042" in result
        odds = result["0022501042"]
        raw_home = 1 / 4.200
        raw_away = 1 / 1.247
        total = raw_home + raw_away
        assert odds["home"] == pytest.approx(raw_home / total, rel=1e-6)
        assert odds["away"] == pytest.approx(raw_away / total, rel=1e-6)
        assert odds["home"] + odds["away"] == pytest.approx(1.0, rel=1e-6)

    def test_all_probabilities_sum_to_one(self, nba_service):
        """Every game in the fixture sums to 1.0."""
        fixture = json.loads((FIXTURES_DIR / "sample-nba-odds-today-response.json").read_text())

        with patch("nba_wins_pool.services.nba_data_service.requests.get", return_value=_mock_requests_get(fixture)):
            result = nba_service.get_fanduel_moneyline_odds()

        assert len(result) > 0
        for game_id, odds in result.items():
            assert odds["home"] + odds["away"] == pytest.approx(1.0, rel=1e-6), f"game {game_id} does not sum to 1"

    def test_skips_game_without_fanduel(self, nba_service):
        """Games with no FanDuel book are excluded from results."""
        data = {
            "games": [
                {
                    "gameId": "0022501099",
                    "markets": [
                        {
                            "name": "2way",
                            "books": [
                                {
                                    "name": "Novibet",
                                    "outcomes": [
                                        {"type": "home", "odds": "2.000"},
                                        {"type": "away", "odds": "2.000"},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        with patch("nba_wins_pool.services.nba_data_service.requests.get", return_value=_mock_requests_get(data)):
            result = nba_service.get_fanduel_moneyline_odds()

        assert "0022501099" not in result

    def test_skips_game_without_2way_market(self, nba_service):
        """Games with only a spread market are excluded."""
        data = {
            "games": [
                {
                    "gameId": "0022501099",
                    "markets": [
                        {
                            "name": "spread",
                            "books": [
                                {
                                    "name": "FanDuel",
                                    "outcomes": [
                                        {"type": "home", "odds": "1.909", "spread": "-5.5"},
                                        {"type": "away", "odds": "1.909", "spread": "5.5"},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        with patch("nba_wins_pool.services.nba_data_service.requests.get", return_value=_mock_requests_get(data)):
            result = nba_service.get_fanduel_moneyline_odds()

        assert "0022501099" not in result

    def test_returns_empty_on_http_error(self, nba_service):
        """Network failures return an empty dict without raising."""
        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            side_effect=Exception("connection refused"),
        ):
            result = nba_service.get_fanduel_moneyline_odds()

        assert result == {}
