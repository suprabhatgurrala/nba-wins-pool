"""Tests for NBAEspnProjectionsService."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.projection import ProjectionMarket
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.projection_repository import ProjectionRepository
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
def mock_projection_repo():
    """Mock ProjectionRepository."""
    repo = AsyncMock(spec=ProjectionRepository)
    return repo


@pytest.fixture
def espn_service(mock_db_session, mock_team_repository, mock_projection_repo):
    """Create NBAEspnProjectionsService with mocked dependencies."""
    return NBAEspnProjectionsService(mock_db_session, mock_team_repository, mock_projection_repo)


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
        """Each ESPN value becomes a quote, stamped with ESPN's own update time."""
        parsed = espn_service._parse_espn_bpi_response(sample_espn_response, team_map)

        assert parsed.season == "2025-26"
        assert parsed.fetched_at == datetime(2026, 1, 5, 15, 32)
        okc_id = team_map["OKC"].id
        quotes = {q.market: q for q in parsed.quotes if q.team_id == okc_id}
        assert quotes[ProjectionMarket.ESPN_WINS].line == pytest.approx(66.12)
        assert quotes[ProjectionMarket.ESPN_BPI].line == pytest.approx(12.12)
        assert quotes[ProjectionMarket.ESPN_PLAYOFF_BPI].line == pytest.approx(11.531)
        assert quotes[ProjectionMarket.MAKE_PLAYOFFS].prob == 1.0
        assert quotes[ProjectionMarket.WIN_CONF].prob == 0.69
        assert quotes[ProjectionMarket.WIN_TITLE].prob == pytest.approx(0.608)

    def test_parse_converts_an_offset_update_time_to_utc(self, espn_service, sample_espn_response, team_map):
        sample_espn_response["lastUpdated"] = "2026-01-05T10:32-05:00"
        parsed = espn_service._parse_espn_bpi_response(sample_espn_response, team_map)
        assert parsed.fetched_at == datetime(2026, 1, 5, 15, 32)

    def test_parse_missing_team_in_db(self, espn_service, sample_espn_response):
        """Test parsing when team is not found in the database map."""
        parsed = espn_service._parse_espn_bpi_response(sample_espn_response, {})
        assert parsed.quotes == []


class TestWriteProjections:
    """Tests for write_projections method."""

    @pytest.mark.asyncio
    async def test_write_projections_success(
        self,
        espn_service,
        mock_db_session,
        mock_team_repository,
        mock_projection_repo,
        sample_espn_response,
        team_map,
    ):
        """A new ESPN update is stored as one fetch."""
        mock_team_repository.get_all_by_league_slug.return_value = list(team_map.values())
        mock_projection_repo.has_fetch.return_value = False

        count = await espn_service.write_projections(use_cached_data=sample_espn_response)

        assert count > 0
        source, season, fetched_at, quotes = mock_projection_repo.add_fetch.call_args.args
        assert (source, season, fetched_at, len(quotes)) == ("espn_bpi", "2025-26", datetime(2026, 1, 5, 15, 32), count)
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_projections_skips_an_update_already_stored(
        self, espn_service, mock_db_session, mock_team_repository, mock_projection_repo, sample_espn_response, team_map
    ):
        mock_team_repository.get_all_by_league_slug.return_value = list(team_map.values())
        mock_projection_repo.has_fetch.return_value = True

        assert await espn_service.write_projections(use_cached_data=sample_espn_response) == 0
        mock_projection_repo.add_fetch.assert_not_called()
        mock_db_session.commit.assert_not_called()
