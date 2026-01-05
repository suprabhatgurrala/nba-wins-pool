"""Tests for NBAEspnProjectionsService."""

import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.services.nba_espn_projections_service import NBAEspnProjectionsService


@pytest.fixture
def mock_db_session():
    """Mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def mock_nba_data_service():
    """Mock NbaDataService."""
    service = MagicMock(spec=NbaDataService)
    service.get_current_season.return_value = "2025-26"
    return service


@pytest.fixture
def mock_team_repository():
    """Mock TeamRepository."""
    repo = AsyncMock(spec=TeamRepository)
    return repo


@pytest.fixture
def espn_service(mock_db_session, mock_nba_data_service, mock_team_repository):
    """Create NBAEspnProjectionsService with mocked dependencies."""
    return NBAEspnProjectionsService(mock_db_session, mock_nba_data_service, mock_team_repository)


@pytest.fixture
def sample_espn_response():
    """Sample raw response from ESPN BPI API."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample-espn-bpi-response.json"
    with open(fixture_path, "r") as f:
        return json.load(f)


@pytest.fixture
def team_map():
    """Mock team map."""
    okc = Team(id=uuid.uuid4(), abbreviation="OKC", name="Oklahoma City Thunder", league=LeagueSlug.NBA)
    return {"OKC": okc}


class TestParseEspnBpiResponse:
    """Tests for _parse_espn_bpi_response method."""

    def test_parse_success(self, espn_service, sample_espn_response, team_map):
        """Test successful parsing of ESPN BPI response."""
        # Arrange
        season = "2025-26"

        # Act
        records = espn_service._parse_espn_bpi_response(sample_espn_response, season, team_map)

        # Assert
        assert len(records) > 0
        # Find OKC record
        record = next((r for r in records if r.team_name == "Oklahoma City Thunder"), None)
        assert record is not None
        assert record.season == season
        assert record.team_name == "Oklahoma City Thunder"
        assert record.reg_season_wins == Decimal("66.12")
        # 100% prob -> -250000
        assert record.make_playoffs_odds == -250000
        # 69% prob -> round(-(0.69 / 0.31) * 100) = -223
        assert record.win_conference_odds == -223
        # 60.8% prob -> round(-(0.608 / 0.392) * 100) = -155
        assert record.win_finals_odds == -155
        assert record.projection_date == datetime.fromisoformat("2026-01-05T15:32Z").date()
        assert record.source == "espn_bpi"

    def test_parse_missing_team_in_db(self, espn_service, sample_espn_response):
        """Test parsing when team is not found in the database map."""
        # Empty team map
        team_map = {}
        records = espn_service._parse_espn_bpi_response(sample_espn_response, "2025-26", team_map)
        assert len(records) == 0


class TestWriteProjections:
    """Tests for write_projections method."""

    @pytest.mark.asyncio
    async def test_write_projections_success(
        self, espn_service, mock_db_session, mock_nba_data_service, mock_team_repository, sample_espn_response, team_map
    ):
        """Test successful fetching and writing of projections."""
        # Arrange
        mock_team_repository.get_all_by_league_slug.return_value = list(team_map.values())

        # Act
        count = await espn_service.write_projections(use_cached_data=sample_espn_response)

        # Assert
        assert count > 0
        mock_db_session.add_all.assert_called_once()
        mock_db_session.commit.assert_called_once()

        records = mock_db_session.add_all.call_args[0][0]
        assert any(r.team_name == "Oklahoma City Thunder" for r in records)
