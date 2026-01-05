"""Tests for NBAVegasProjectionsService."""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService


@pytest.fixture
def mock_db_session():
    """Mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def mock_nba_data_service():
    """Mock NbaDataService."""
    service = MagicMock(spec=NbaDataService)
    service.get_current_season.return_value = "2024-25"
    return service


@pytest.fixture
def mock_team_repository():
    """Mock TeamRepository."""
    repo = AsyncMock(spec=TeamRepository)
    return repo


@pytest.fixture
def vegas_service(mock_db_session, mock_nba_data_service, mock_team_repository):
    """Create NBAVegasProjectionsService with mocked dependencies."""
    return NBAVegasProjectionsService(mock_db_session, mock_nba_data_service, mock_team_repository)


@pytest.fixture
def sample_fanduel_response():
    """Sample raw response from FanDuel API."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample-fanduel-response.json"
    with open(fixture_path, "r") as f:
        return json.load(f)


@pytest.fixture
def team_map():
    """Mock team map."""
    celtics = Team(id=uuid.uuid4(), abbreviation="BOS", name="Boston Celtics", league=LeagueSlug.NBA)
    return {"BOS": celtics}


class TestParseFanduelResponse:
    """Tests for _parse_fanduel_response method."""

    def test_parse_success(self, vegas_service, sample_fanduel_response, team_map):
        """Test successful parsing of FanDuel response."""
        # Arrange
        fetched_at = datetime(2024, 10, 20, 12, 0, 0)
        season = "2024-25"

        # Act
        records = vegas_service._parse_fanduel_response(sample_fanduel_response, season, fetched_at, team_map)

        # Assert
        assert len(records) > 0
        # Find Celtics record
        record = next((r for r in records if r.team_name == "Boston Celtics"), None)
        assert record is not None
        assert record.season == season
        assert record.team_name == "Boston Celtics"
        assert record.reg_season_wins == Decimal("52.5")
        assert record.over_wins_odds == -110
        assert record.under_wins_odds == -110
        assert record.make_playoffs_odds == -50000
        assert record.miss_playoffs_odds == 2000
        assert record.win_conference_odds == 490
        assert record.win_finals_odds == 2200
        assert record.projection_date == date(2024, 10, 20)
        assert record.fetched_at == fetched_at
        assert record.source == "fanduel"

    def test_parse_missing_tricode(self, vegas_service, sample_fanduel_response, team_map):
        """Test parsing when team name mapping is missing."""
        # Add a team not in FANDUEL_TO_TRICODE
        sample_fanduel_response["attachments"]["markets"]["m5"] = {
            "marketType": "NBA_REGULAR_SEASON_WINS_SGP",
            "marketName": "Unknown Team Regular Season Wins",
            "runners": [],
        }

        fetched_at = datetime.now()
        records = vegas_service._parse_fanduel_response(sample_fanduel_response, "2024-25", fetched_at, team_map)

        # Should still have Celtics (among others, but Celtics is the one we know is in team_map)
        assert any(r.team_name == "Boston Celtics" for r in records)

    def test_parse_missing_team_in_db(self, vegas_service, sample_fanduel_response):
        """Test parsing when team is not found in the database map."""
        # Empty team map
        team_map = {}
        fetched_at = datetime.now()

        records = vegas_service._parse_fanduel_response(sample_fanduel_response, "2024-25", fetched_at, team_map)

        assert len(records) == 0

    def test_parse_missing_reg_season_wins(self, vegas_service, team_map):
        """Test parsing when reg season wins market is missing (required field)."""
        response = {
            "attachments": {
                "markets": {
                    "m1": {
                        "marketType": "NBA_CHAMPIONSHIP",
                        "marketName": "NBA Championship Winner",
                        "runners": [
                            {
                                "runnerName": "Boston Celtics",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": 300}},
                            }
                        ],
                    }
                }
            }
        }

        fetched_at = datetime.now()
        records = vegas_service._parse_fanduel_response(response, "2024-25", fetched_at, team_map)

        assert len(records) == 0


class TestWriteProjections:
    """Tests for write_projections method."""

    @pytest.mark.asyncio
    async def test_write_projections_success(
        self,
        vegas_service,
        mock_db_session,
        mock_nba_data_service,
        mock_team_repository,
        sample_fanduel_response,
        team_map,
    ):
        """Test successful fetching and writing of projections."""
        # Arrange
        mock_team_repository.get_all_by_league_slug.return_value = list(team_map.values())

        with patch.object(vegas_service, "_fetch_fanduel_data", return_value=sample_fanduel_response):
            # Act
            count = await vegas_service.write_projections()

            # Assert
            assert count == 1
            mock_db_session.add_all.assert_called_once()
            mock_db_session.commit.assert_called_once()

            records = mock_db_session.add_all.call_args[0][0]
            assert len(records) > 0
            assert any(r.team_name == "Boston Celtics" for r in records)
