"""Tests for NBAVegasProjectionsService."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
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
def mock_nba_projections_repo():
    """Mock NBAProjectionsRepository."""
    repo = AsyncMock(spec=NBAProjectionsRepository)
    return repo


@pytest.fixture
def vegas_service(mock_db_session, mock_nba_data_service, mock_team_repository, mock_nba_projections_repo):
    """Create NBAVegasProjectionsService with mocked dependencies."""
    return NBAVegasProjectionsService(
        mock_db_session, mock_nba_data_service, mock_team_repository, mock_nba_projections_repo
    )


@pytest.fixture
def sample_fanduel_response():
    """Sample raw response from FanDuel API."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample-fanduel-response.json"
    with open(fixture_path, "r") as f:
        return json.load(f)


@pytest.fixture
def expected_probs():
    """Expected probabilities fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "expected_fanduel_probs.json"
    with open(fixture_path, "r") as f:
        return json.load(f)


@pytest.fixture
def team_map():
    """Mock team map with all NBA teams."""
    teams = {}
    for team_name, tricode in NBAVegasProjectionsService.FANDUEL_TO_TRICODE.items():
        teams[tricode] = Team(id=uuid.uuid4(), abbreviation=tricode, name=team_name, league=LeagueSlug.NBA)
    return teams


class TestParseFanduelResponse:
    """Tests for _parse_fanduel_response method."""

    def test_probability_calculations(self, vegas_service, sample_fanduel_response, team_map, expected_probs):
        """Test that calculated probabilities match expected values from fixture."""
        # Arrange
        fetched_at = datetime(2024, 10, 20, 12, 0, 0)

        # Act
        records = vegas_service._parse_fanduel_response(sample_fanduel_response, fetched_at, team_map)

        # Assert
        assert len(records) > 0

        for record in records:
            assert record.make_playoffs_prob == pytest.approx(
                expected_probs[record.team_name]["make_playoffs_prob"], abs=1e-6
            )
            assert record.over_wins_prob == pytest.approx(
                expected_probs[record.team_name]["over_reg_season_wins_prob"], abs=1e-6
            )
            assert record.win_conference_prob == pytest.approx(expected_probs[record.team_name]["conf_prob"], abs=1e-6)
            assert record.win_finals_prob == pytest.approx(expected_probs[record.team_name]["title_prob"], abs=1e-6)
