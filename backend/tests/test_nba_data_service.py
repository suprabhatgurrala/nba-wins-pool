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

        with (
            patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)),
            patch.object(nba_service, "_get_espn_season_type_dates", return_value=None),
        ):
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


class TestPlayoffInfo:
    """Playoff-specific fields (seeds, series text) are parsed from gamecardfeed."""

    @pytest.fixture
    def playoffs_fixture(self):
        with open(FIXTURES_DIR / "sample-nba-gamecardfeed-response-playoffs.json") as f:
            return json.load(f)

    def test_series_game_text_from_info(self, nba_service):
        game = {
            "gameId": "0042500106",
            "gameStatus": 1,
            "gameTimeUtc": "2026-05-01T00:00:00Z",
            "homeTeam": {"teamId": 1610612753, "teamTricode": "ORL", "score": 0, "specialInfoPrefix": "8"},
            "awayTeam": {"teamId": 1610612765, "teamTricode": "DET", "score": 0, "specialInfoPrefix": "1"},
            "gameStatusText": "7:30 pm ET",
            "info": "Game 6",
            "subInfo": "ORL leads 3-2",
        }
        result = nba_service._parse_game_data(game, "2026-05-01T00:00:00Z")

        assert result["series_game_text"] == "Game 6"
        assert result["series_status_text"] == "ORL leads 3-2"

    def test_seeds_from_special_info_prefix(self, nba_service):
        game = {
            "gameId": "0042500106",
            "gameStatus": 1,
            "gameTimeUtc": "2026-05-01T00:00:00Z",
            "homeTeam": {"teamId": 1610612753, "teamTricode": "ORL", "score": 0, "specialInfoPrefix": "8"},
            "awayTeam": {"teamId": 1610612765, "teamTricode": "DET", "score": 0, "specialInfoPrefix": "1"},
            "gameStatusText": "7:30 pm ET",
            "info": "Game 6",
            "subInfo": "ORL leads 3-2",
        }
        result = nba_service._parse_game_data(game, "2026-05-01T00:00:00Z")

        assert result["home_seed"] == 8
        assert result["away_seed"] == 1

    def test_parses_playoffs_fixture(self, nba_service, playoffs_fixture):
        games, game_ids, _ = nba_service._parse_gamecardfeed(playoffs_fixture)

        assert len(games) == 3
        orl_det = next(g for g in games if g["game_id"] == "0042500106")
        assert orl_det["series_game_text"] == "Game 6"
        assert orl_det["series_status_text"] == "ORL leads 3-2"
        assert orl_det["home_seed"] == 8
        assert orl_det["away_seed"] == 1

    def test_non_playoff_game_has_null_series_fields(self, nba_service):
        game = {
            "gameId": "0022501042",
            "gameStatus": 1,
            "homeTeam": {"teamId": 1, "teamTricode": "HOM", "score": 0},
            "awayTeam": {"teamId": 2, "teamTricode": "AWY", "score": 0},
            "gameStatusText": "7:30 pm ET",
        }
        result = nba_service._parse_game_data(game, "2026-03-25T23:00:00Z")

        assert result["series_game_text"] is None
        assert result["series_status_text"] is None
        assert result["home_seed"] is None
        assert result["away_seed"] is None

    @pytest.mark.asyncio
    async def test_playoff_info_flows_through_get_game_data(self, nba_service, playoffs_fixture):
        season = nba_service.get_current_season()
        cdn_schedule_raw = {"leagueSchedule": {"seasonYear": season, "gameDates": []}}

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(playoffs_fixture, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        orl_det = result[result["game_id"] == "0042500106"].iloc[0]
        assert orl_det["series_game_text"] == "Game 6"
        assert orl_det["series_status_text"] == "ORL leads 3-2"
        assert orl_det["home_seed"] == 8
        assert orl_det["away_seed"] == 1


class TestParseSchedule:
    """Tests for _parse_schedule using real fixture data."""

    @pytest.fixture
    def schedule_fixture(self):
        with open(FIXTURES_DIR / "sample-nba-schedule-response.json") as f:
            return json.load(f)

    @pytest.fixture
    def schedule_2022_fixture(self):
        with open(FIXTURES_DIR / "sample-nba-schedule-2022-response.json") as f:
            return json.load(f)

    def test_parses_games_from_current_fixture(self, nba_service, schedule_fixture):
        games = nba_service._parse_schedule(schedule_fixture)
        assert len(games) > 0

    def test_parses_games_from_2022_fixture(self, nba_service, schedule_2022_fixture):
        games = nba_service._parse_schedule(schedule_2022_fixture)
        assert len(games) > 0

    def test_if_necessary_string_false_parsed_as_bool_false(self, nba_service, schedule_2022_fixture):
        """2022 fixture stores ifNecessary as the string "false"; must not be truthy."""
        games = nba_service._parse_schedule(schedule_2022_fixture)
        assert all(g["if_necessary"] is False for g in games)

    def test_if_necessary_false_in_current_fixture(self, nba_service, schedule_fixture):
        games = nba_service._parse_schedule(schedule_fixture)
        assert all(g["if_necessary"] is False for g in games if g.get("if_necessary") is not None)

    def test_all_2022_games_are_final(self, nba_service, schedule_2022_fixture):
        games = nba_service._parse_schedule(schedule_2022_fixture)
        assert all(g["status"] == NBAGameStatus.FINAL for g in games)

    def test_game_fields_present(self, nba_service, schedule_2022_fixture):
        games = nba_service._parse_schedule(schedule_2022_fixture)
        required = {"game_id", "date_time", "home_team", "away_team", "status", "if_necessary"}
        assert required.issubset(games[0].keys())


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

    @pytest.mark.asyncio
    async def test_gamecardfeed_series_status_overrides_schedule(self, nba_service):
        """gamecardfeed subInfo overrides CDN schedule seriesText for series_status_text."""
        season = nba_service.get_current_season()
        timestamp = "2026-04-25T23:00:00Z"
        gamecardfeed_raw = _make_gamecardfeed_raw("0042500151", timestamp, subInfo="BOS leads 2-1")
        cdn_schedule_raw = _make_schedule_raw(
            season,
            "04/25/2026 00:00:00",
            [_make_schedule_game("0042500151", timestamp, seriesText="Series tied 1-1")],
        )

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        row = result[result["game_id"] == "0042500151"].iloc[0]
        assert row["series_status_text"] == "BOS leads 2-1"

    @pytest.mark.asyncio
    async def test_gamecardfeed_null_series_status_falls_back_to_schedule(self, nba_service):
        """When gamecardfeed has no subInfo, series_status_text falls back to CDN schedule seriesText."""
        season = nba_service.get_current_season()
        timestamp = "2026-04-25T23:00:00Z"
        gamecardfeed_raw = _make_gamecardfeed_raw("0042500151", timestamp)  # no subInfo
        cdn_schedule_raw = _make_schedule_raw(
            season,
            "04/25/2026 00:00:00",
            [_make_schedule_game("0042500151", timestamp, seriesText="Series tied 1-1")],
        )

        with patch.object(nba_service, "_fetch_current_season_raw", return_value=(gamecardfeed_raw, cdn_schedule_raw)):
            result = await nba_service.get_game_data(season)

        row = result[result["game_id"] == "0042500151"].iloc[0]
        assert row["series_status_text"] == "Series tied 1-1"


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
    async def test_game_date_future_dates_included(self, nba_service):
        """Games after scoreboard_date are included so the full season is navigable."""
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

        assert "today_game" in result["game_id"].values
        assert "future_game" in result["game_id"].values


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


class TestEspnSeasonTypeDates:
    """Tests for ESPN season type date parsing and game classification."""

    @pytest.fixture
    def espn_season_fixture(self):
        with open(FIXTURES_DIR / "sample-espn-nba-season.json") as f:
            return json.load(f)

    def test_parses_all_mapped_season_types(self, nba_service, espn_season_fixture):
        """Preseason, Regular Season, Playoffs, and Play-In are returned; Off Season is skipped."""
        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            return_value=_mock_requests_get(espn_season_fixture),
        ):
            result = nba_service._fetch_espn_season_type_dates(2026)

        from nba_wins_pool.types.nba_game_type import NBAGameType

        game_types = [r[0] for r in result]
        assert NBAGameType.PRESEASON in game_types
        assert NBAGameType.REGULAR_SEASON in game_types
        assert NBAGameType.PLAY_IN in game_types
        assert NBAGameType.PLAYOFFS in game_types
        assert len(result) == 4  # Off Season (type 4) has no mapping and is skipped

    def test_sorted_by_start_date(self, nba_service, espn_season_fixture):
        """Returned ranges are sorted chronologically."""
        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            return_value=_mock_requests_get(espn_season_fixture),
        ):
            result = nba_service._fetch_espn_season_type_dates(2026)

        start_dates = [r[1] for r in result]
        assert start_dates == sorted(start_dates)

    def test_regular_season_date_range(self, nba_service, espn_season_fixture):
        """Regular Season runs 2025-10-21 to 2026-04-13."""
        from datetime import datetime

        from nba_wins_pool.types.nba_game_type import NBAGameType

        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            return_value=_mock_requests_get(espn_season_fixture),
        ):
            result = nba_service._fetch_espn_season_type_dates(2026)

        reg = next(r for r in result if r[0] == NBAGameType.REGULAR_SEASON)
        assert reg[1] == datetime.fromisoformat("2025-10-21T07:00:00+00:00")
        assert reg[2] == datetime.fromisoformat("2026-04-13T06:59:00+00:00")

    def test_play_in_date_range(self, nba_service, espn_season_fixture):
        """Play-In runs 2026-04-13 to 2026-04-18."""
        from datetime import datetime

        from nba_wins_pool.types.nba_game_type import NBAGameType

        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            return_value=_mock_requests_get(espn_season_fixture),
        ):
            result = nba_service._fetch_espn_season_type_dates(2026)

        playin = next(r for r in result if r[0] == NBAGameType.PLAY_IN)
        assert playin[1] == datetime.fromisoformat("2026-04-13T07:00:00+00:00")
        assert playin[2] == datetime.fromisoformat("2026-04-18T06:59:00+00:00")

    def test_playoffs_date_range(self, nba_service, espn_season_fixture):
        """Playoffs run 2026-04-18 to 2026-06-27."""
        from datetime import datetime

        from nba_wins_pool.types.nba_game_type import NBAGameType

        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            return_value=_mock_requests_get(espn_season_fixture),
        ):
            result = nba_service._fetch_espn_season_type_dates(2026)

        playoffs = next(r for r in result if r[0] == NBAGameType.PLAYOFFS)
        assert playoffs[1] == datetime.fromisoformat("2026-04-18T07:00:00+00:00")
        assert playoffs[2] == datetime.fromisoformat("2026-06-27T06:59:00+00:00")


class TestClassifyGameDate:
    """Tests for NbaDataService._classify_game_date using season type date ranges."""

    @pytest.fixture
    def season_type_dates(self, nba_service):
        fixture = json.loads((FIXTURES_DIR / "sample-espn-nba-season.json").read_text())
        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            return_value=_mock_requests_get(fixture),
        ):
            return nba_service._fetch_espn_season_type_dates(2026)

    def test_regular_season_game(self, season_type_dates):
        from datetime import datetime

        from nba_wins_pool.types.nba_game_type import NBAGameType

        game_dt = datetime.fromisoformat("2026-01-15T00:30:00+00:00")
        assert NbaDataService._classify_game_date(game_dt, season_type_dates) == NBAGameType.REGULAR_SEASON

    def test_play_in_game(self, season_type_dates):
        from datetime import datetime

        from nba_wins_pool.types.nba_game_type import NBAGameType

        game_dt = datetime.fromisoformat("2026-04-15T23:00:00+00:00")
        assert NbaDataService._classify_game_date(game_dt, season_type_dates) == NBAGameType.PLAY_IN

    def test_playoffs_game(self, season_type_dates):
        from datetime import datetime

        from nba_wins_pool.types.nba_game_type import NBAGameType

        game_dt = datetime.fromisoformat("2026-05-10T23:00:00+00:00")
        assert NbaDataService._classify_game_date(game_dt, season_type_dates) == NBAGameType.PLAYOFFS

    def test_preseason_game(self, season_type_dates):
        from datetime import datetime

        from nba_wins_pool.types.nba_game_type import NBAGameType

        game_dt = datetime.fromisoformat("2025-10-10T23:00:00+00:00")
        assert NbaDataService._classify_game_date(game_dt, season_type_dates) == NBAGameType.PRESEASON

    def test_unknown_date_falls_back_to_regular_season(self, season_type_dates):
        """A date outside all ranges (e.g. off-season) defaults to REGULAR_SEASON."""
        from datetime import datetime

        from nba_wins_pool.types.nba_game_type import NBAGameType

        game_dt = datetime.fromisoformat("2026-08-01T00:00:00+00:00")
        assert NbaDataService._classify_game_date(game_dt, season_type_dates) == NBAGameType.REGULAR_SEASON


class TestGameTypeInParsedSchedule:
    """game_type is set correctly when season_type_dates are passed to _parse_schedule."""

    @pytest.fixture
    def season_type_dates(self, nba_service):
        fixture = json.loads((FIXTURES_DIR / "sample-espn-nba-season.json").read_text())
        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            return_value=_mock_requests_get(fixture),
        ):
            return nba_service._fetch_espn_season_type_dates(2026)

    def test_regular_season_game_labelled(self, nba_service, season_type_dates):
        from nba_wins_pool.types.nba_game_type import NBAGameType

        raw = _make_schedule_raw(
            "2025-26",
            "11/01/2025 00:00:00",
            [_make_schedule_game("g1", "2025-11-01T00:30:00Z")],
        )
        games = nba_service._parse_schedule(raw, season_type_dates=season_type_dates)
        assert games[0]["game_type"] == NBAGameType.REGULAR_SEASON

    def test_play_in_game_labelled(self, nba_service, season_type_dates):
        from nba_wins_pool.types.nba_game_type import NBAGameType

        raw = _make_schedule_raw(
            "2025-26",
            "04/15/2026 00:00:00",
            [_make_schedule_game("g2", "2026-04-15T23:00:00Z")],
        )
        games = nba_service._parse_schedule(raw, season_type_dates=season_type_dates)
        assert games[0]["game_type"] == NBAGameType.PLAY_IN

    def test_playoffs_game_labelled(self, nba_service, season_type_dates):
        from nba_wins_pool.types.nba_game_type import NBAGameType

        raw = _make_schedule_raw(
            "2025-26",
            "05/10/2026 00:00:00",
            [_make_schedule_game("g3", "2026-05-10T23:00:00Z")],
        )
        games = nba_service._parse_schedule(raw, season_type_dates=season_type_dates)
        assert games[0]["game_type"] == NBAGameType.PLAYOFFS

    def test_defaults_to_regular_season_without_dates(self, nba_service):
        """When season_type_dates is not provided, game_type defaults to REGULAR_SEASON."""
        from nba_wins_pool.types.nba_game_type import NBAGameType

        raw = _make_schedule_raw(
            "2025-26",
            "04/15/2026 00:00:00",
            [_make_schedule_game("g4", "2026-04-15T23:00:00Z")],
        )
        games = nba_service._parse_schedule(raw)
        assert games[0]["game_type"] == NBAGameType.REGULAR_SEASON

    def test_preseason_games_excluded(self, nba_service, season_type_dates):
        """Preseason games must not appear in parsed results — they would inflate leaderboard win counts."""
        # Preseason window in fixture: Oct 1–21 2025. Regular season starts Oct 21 2025.
        raw = {
            "leagueSchedule": {
                "seasonYear": "2025-26",
                "gameDates": [
                    {
                        "gameDate": "10/05/2025 00:00:00",
                        "games": [_make_schedule_game("preseason_game", "2025-10-05T23:00:00Z")],
                    },
                    {
                        "gameDate": "11/01/2025 00:00:00",
                        "games": [_make_schedule_game("regular_game", "2025-11-01T00:30:00Z")],
                    },
                ],
            }
        }
        games = nba_service._parse_schedule(raw, season_type_dates=season_type_dates)
        game_ids = [g["game_id"] for g in games]
        assert "preseason_game" not in game_ids
        assert "regular_game" in game_ids
        assert len(games) == 1


class TestSeasonMilestones:
    """Tests for All-Star and Playoffs milestone extraction."""

    def _make_schedule(self, game_dates: list[dict]) -> dict:
        return {"leagueSchedule": {"seasonYear": "2025-26", "gameDates": game_dates}}

    def _make_game_date(self, date_str: str, game_labels: list[str]) -> dict:
        """date_str in MM/DD/YYYY format."""
        return {
            "gameDate": f"{date_str} 00:00:00",
            "games": [{"gameLabel": label, "gameId": f"g_{date_str}_{i}"} for i, label in enumerate(game_labels)],
        }

    def test_all_star_date_is_last_regular_game_before_break(self, nba_service):
        """Should return the last date with regular games before the All-Star event dates."""
        raw = self._make_schedule(
            game_dates=[
                self._make_game_date("02/10/2026", ["", ""]),
                self._make_game_date("02/12/2026", ["", ""]),  # last regular games
                self._make_game_date("02/13/2026", ["Rising Stars Game"]),  # only excluded
                self._make_game_date("02/15/2026", ["All-Star Game"]),  # only excluded
                self._make_game_date("02/18/2026", ["", ""]),  # regular games resume
            ],
        )
        assert nba_service._get_all_star_date_from_schedule(raw) == "2026-02-12"

    def test_all_star_date_skips_excluded_only_dates(self, nba_service):
        """Multiple consecutive excluded-only dates are all treated as part of the break."""
        raw = self._make_schedule(
            game_dates=[
                self._make_game_date("02/12/2025", ["", ""]),
                self._make_game_date("02/14/2025", ["Rising Stars Game"]),
                self._make_game_date("02/15/2025", ["All-Star Celebrity Game"]),
                self._make_game_date("02/16/2025", ["NBA All-Star Game"]),
                self._make_game_date("02/18/2025", ["", ""]),
            ],
        )
        assert nba_service._get_all_star_date_from_schedule(raw) == "2025-02-12"

    def test_all_star_date_returns_none_when_no_all_star_events(self, nba_service):
        """Returns None if no All-Star/Rising Stars labeled games appear."""
        raw = self._make_schedule(
            game_dates=[
                self._make_game_date("10/22/2025", ["", ""]),
                self._make_game_date("10/24/2025", ["", ""]),
            ],
        )
        assert nba_service._get_all_star_date_from_schedule(raw) is None

    def test_all_star_date_returns_none_on_empty_game_dates(self, nba_service):
        raw = self._make_schedule(game_dates=[])
        assert nba_service._get_all_star_date_from_schedule(raw) is None

    def test_regular_season_end_date_extracted(self, nba_service):
        from nba_wins_pool.types.nba_game_type import NBAGameType

        season_type_dates = [
            (
                NBAGameType.PRESEASON,
                datetime.fromisoformat("2025-10-01T07:00:00+00:00"),
                datetime.fromisoformat("2025-10-21T06:59:00+00:00"),
            ),
            (
                NBAGameType.REGULAR_SEASON,
                datetime.fromisoformat("2025-10-21T07:00:00+00:00"),
                datetime.fromisoformat("2026-04-13T06:59:00+00:00"),
            ),
            (
                NBAGameType.PLAYOFFS,
                datetime.fromisoformat("2026-04-18T07:00:00+00:00"),
                datetime.fromisoformat("2026-06-27T06:59:00+00:00"),
            ),
        ]
        assert nba_service._get_regular_season_end_date(season_type_dates) == "2026-04-13"

    def test_regular_season_end_date_returns_none_when_absent(self, nba_service):
        from nba_wins_pool.types.nba_game_type import NBAGameType

        season_type_dates = [
            (
                NBAGameType.PLAYOFFS,
                datetime.fromisoformat("2026-04-18T07:00:00+00:00"),
                datetime.fromisoformat("2026-06-27T06:59:00+00:00"),
            ),
        ]
        assert nba_service._get_regular_season_end_date(season_type_dates) is None

    @pytest.mark.asyncio
    async def test_get_season_milestones_returns_both(self, nba_service, mock_repo):
        from unittest.mock import patch

        from nba_wins_pool.models.external_data import DataFormat, ExternalData

        espn_fixture = json.loads((FIXTURES_DIR / "sample-espn-nba-season.json").read_text())

        raw_schedule = {
            "leagueSchedule": {
                "seasonYear": "2025-26",
                "gameDates": [
                    {"gameDate": "02/11/2026 00:00:00", "games": [{"gameLabel": "", "gameId": "g1"}]},
                    {"gameDate": "02/12/2026 00:00:00", "games": [{"gameLabel": "", "gameId": "g2"}]},
                    {"gameDate": "02/13/2026 00:00:00", "games": [{"gameLabel": "Rising Stars Game", "gameId": "g3"}]},
                    {"gameDate": "02/15/2026 00:00:00", "games": [{"gameLabel": "All-Star Game", "gameId": "g4"}]},
                    {"gameDate": "02/18/2026 00:00:00", "games": [{"gameLabel": "", "gameId": "g5"}]},
                ],
            }
        }
        cached = ExternalData(key="nba:schedule:2025-26", data_json=raw_schedule, data_format=DataFormat.JSON)
        mock_repo.get_by_key.return_value = cached

        with patch(
            "nba_wins_pool.services.nba_data_service.requests.get",
            return_value=_mock_requests_get(espn_fixture),
        ):
            nba_service.get_current_season.cache_clear()
            with patch.object(nba_service, "get_current_season", return_value="2024-25"):
                result = await nba_service.get_season_milestones("2025-26")

        assert len(result) == 2
        slugs = [m["slug"] for m in result]
        assert "all_star_break" in slugs
        assert "playoffs_start" in slugs
        dates = [m["date"] for m in result]
        assert dates == sorted(dates)
        all_star = next(m for m in result if m["slug"] == "all_star_break")
        assert all_star["date"] == "2026-02-12"  # last regular game date within All-Star week
        playoffs = next(m for m in result if m["slug"] == "playoffs_start")
        assert playoffs["date"] == "2026-04-13"

    @pytest.mark.asyncio
    async def test_get_season_milestones_empty_on_missing_season(self, nba_service):
        result = await nba_service.get_season_milestones("")
        # Empty season year causes ESPN fetch to fail; result should be an empty list or partial
        # The key invariant: no exception is raised
        assert isinstance(result, list)
